import os
import json
import logging
from typing import Optional, Dict, Any, List

import trackingmore
import re
import requests

# Try importing OpenHome SDK symbols. If not available at static-check time,
# provide lightweight fallbacks so the file remains importable for tests.
try:
    from openhome import Capability
    from openhome import editor_logging_handler
except Exception:
    # Fallbacks for static editing / testing
    class Capability:
        def __init__(self, *args, **kwargs):
            pass

    def editor_logging_handler():
        return logging.StreamHandler()


logger = logging.getLogger('package_tracker')
logger.setLevel(logging.DEBUG)
try:
    handler = editor_logging_handler()
except Exception:
    handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
if not logger.handlers:
    logger.addHandler(handler)


class PackageTracker(Capability):
    def register_capability(self) -> Dict[str, Any]:
        """Register capability metadata for OpenHome."""
        return {
            'unique_name': 'package_tracker',
            'hotwords': [
                'track my package',
                "where's my package",
                'package status',
                'tracking'
            ]
        }

    def __init__(self):
        super().__init__()
        # Load config
        self.root = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.join(self.root, 'config.json')
        self.packages_path = os.path.join(self.root, 'packages.json')
        self.config = self._load_json(self.config_path, default={})

        api_key = self.config.get('trackingmore_api_key')
        if api_key:
            trackingmore.api_key = api_key
        else:
            logger.warning('trackingmore_api_key not set in config.json')

        # Load persisted packages
        self.packages = self._load_json(self.packages_path, default={'packages': []}).get('packages', [])

    # ----------------- Persistence helpers -----------------
    def _load_json(self, path: str, default: Any):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return default
        except Exception as e:
            logger.error('Failed to load %s: %s', path, e)
            return default

    def _save_packages(self):
        try:
            with open(self.packages_path, 'w', encoding='utf-8') as f:
                json.dump({'packages': self.packages}, f, indent=2)
        except Exception as e:
            logger.error('Failed to save packages.json: %s', e)

    # ----------------- Capability runtime -----------------
    def call(self, agent, user_input: str):
        """
        Main entrypoint called by the OpenHome agent.
        - Use the built-in LLM to classify intent (add, check, list, remove).
        - Always call `agent.resume_normal_flow()` before returning.
        """
        try:
            # Lightweight keyword pre-check to quickly route common requests
            text = (user_input or '').lower()
            # Prepare extraction defaults to avoid UnboundLocalError later
            extracted_number = None
            extracted_name = None
            # Quick regex extraction for numeric tracking numbers in the user's text
            if user_input:
                m = re.search(r"\b(\d{8,})\b", user_input)
                if m:
                    extracted_number = m.group(1)
            if any(x in text for x in ('add', 'track', 'save', 'remember')):
                intent = 'add'
            elif any(x in text for x in ('where', 'status', 'check', 'how is', 'track status')):
                intent = 'check'
            elif any(x in text for x in ('list', 'show', 'my packages')):
                intent = 'list'
            elif any(x in text for x in ('remove', 'delete', 'forget')):
                intent = 'remove'
            else:
                # Ask the built-in LLM for classification & extraction
                try:
                    prompt = (
                        'Classify the user intent into one of [add, check, list, remove]. '
                        'If add or remove or check, extract tracking_number and friendly_name when present. '
                        f'User input: "{user_input}"\nRespond as JSON with keys: intent, tracking_number, friendly_name (use null when absent).'
                    )
                    resp = agent.llm.text_to_text(prompt)
                    # Expect JSON back — be forgiving
                    parsed = json.loads(resp) if resp else {}
                    intent = parsed.get('intent')
                    extracted_number = parsed.get('tracking_number')
                    extracted_name = parsed.get('friendly_name')
                except Exception:
                    # Fallback
                    intent = 'check'
                    extracted_number = None
                    extracted_name = None

            # Route
            if intent == 'add':
                # Try to extract with LLM or prompt if not previously extracted
                if not extracted_number:
                    extracted_number = self._ask_for_tracking_number(agent, user_input)
                return self.handle_add_package(agent, extracted_number, extracted_name)
            elif intent == 'check':
                identifier = extracted_number if 'extracted_number' in locals() and extracted_number else None
                if not identifier:
                    identifier = self._ask_for_tracking_number(agent, user_input)
                return self.handle_check_status(agent, identifier)
            elif intent == 'list':
                return self.handle_list_packages(agent)
            elif intent == 'remove':
                # Prefer an extracted numeric tracking number
                identifier = extracted_number if extracted_number else None
                # If we don't have a number, try to extract a friendly name first
                if not identifier:
                    extracted_name = self._ask_for_friendly_name(agent, user_input)
                    if extracted_name:
                        identifier = extracted_name
                    else:
                        # Finally, prompt for a tracking number interactively
                        identifier = self._ask_for_tracking_number(agent, user_input)
                return self.handle_remove_package(agent, identifier)
            else:
                self._respond(agent, 'Sorry, I did not understand. I can add, check, list or remove packages. Which would you like?')
        except Exception as e:
            logger.exception('Unhandled error in call(): %s', e)
            self._respond(agent, 'Sorry, something went wrong while handling your request.')
        finally:
            try:
                agent.resume_normal_flow()
            except Exception:
                # Ensure we never raise from resume_normal_flow issues
                logger.debug('agent.resume_normal_flow() failed or is unavailable')

    # ----------------- Small helpers for conversation -----------------
    def _respond(self, agent, text: str):
        # Prefer the agent's speak/respond API when available
        try:
            if hasattr(agent, 'respond'):
                agent.respond(text)
                return
            if hasattr(agent, 'say'):
                agent.say(text)
                return
            if hasattr(agent, 'speaker') and hasattr(agent.speaker, 'speak'):
                agent.speaker.speak(text)
                return
        except Exception:
            logger.debug('agent response method not available or failed')
        # Fallback to logging
        logger.info(text)

    def _ask_for_tracking_number(self, agent, context_text: Optional[str]) -> Optional[str]:
        # Delegates to the LLM to extract a tracking number, otherwise prompts user.
        try:
            prompt = f'Extract a tracking number from this text if present: "{context_text}". Return just the tracking number or empty.'
            resp = agent.llm.text_to_text(prompt)
            if resp:
                candidate = resp.strip().strip('"')
                if candidate:
                    return candidate
        except Exception:
            logger.debug('LLM extraction failed')
        # If agent has a prompt/ask method, ask the user and return answer
        try:
            if hasattr(agent, 'ask'):
                ans = agent.ask('Please tell me the tracking number.')
                if ans:
                    cand = ans.strip()
                    # Confirm extraction
                    if self._confirm(agent, f'You said tracking number {cand}. Is that correct?'):
                        return cand
                    return None
            if hasattr(agent, 'prompt'):
                ans = agent.prompt('Please tell me the tracking number.')
                if ans:
                    cand = ans.strip()
                    if self._confirm(agent, f'You said tracking number {cand}. Is that correct?'):
                        return cand
                    return None
        except Exception:
            logger.debug('agent ask/prompt failed')

        # Fallback: tell user we need the number
        try:
            self._respond(agent, 'Please tell me the tracking number.')
        except Exception:
            pass
        return None

    def _confirm(self, agent, prompt: str, default: bool = False) -> bool:
        """Ask the user a yes/no question and interpret the response."""
        try:
            # Prefer agent.ask / prompt
            for fn in ('ask', 'prompt'):
                if hasattr(agent, fn):
                    resp = getattr(agent, fn)(prompt + ' (yes/no)')
                    if not resp:
                        continue
                    r = str(resp).strip().lower()
                    if r.startswith('y') or r in ('yes', 'sure', 'ok'):
                        return True
                    if r.startswith('n') or r in ('no', 'nah', 'cancel'):
                        return False
            # Use LLM as a fallback
            if hasattr(agent, 'llm') and hasattr(agent.llm, 'text_to_text'):
                resp = agent.llm.text_to_text(prompt + ' Answer yes or no.')
                if resp:
                    r = str(resp).strip().lower()
                    if r.startswith('y'):
                        return True
                    if r.startswith('n'):
                        return False
        except Exception:
            logger.debug('Confirmation prompt failed')
        return default

    def _ask_for_friendly_name(self, agent, context_text: Optional[str]) -> Optional[str]:
        try:
            prompt = f'Extract a friendly name for a package from this text if present: "{context_text}". Return just the name or empty.'
            resp = agent.llm.text_to_text(prompt)
            if resp:
                return resp.strip().strip('"')
        except Exception:
            logger.debug('LLM extraction failed for friendly name')
        try:
            if hasattr(agent, 'ask'):
                ans = agent.ask('What would you like to call this package?')
                if ans:
                    return ans.strip()
        except Exception:
            logger.debug('agent ask failed for friendly name')
        return None

    # ----------------- Action handlers -----------------
    def handle_add_package(self, agent, tracking_number: Optional[str], friendly_name: Optional[str] = None):
        # Ensure we have a valid tracking number
        if not tracking_number:
            tracking_number = self._ask_for_tracking_number(agent, None)
            if not tracking_number:
                self._respond(agent, 'I need a tracking number to add a package. Let me know when you have one.')
                return

        # Confirm before proceeding
        if not self._confirm(agent, f'I will add tracking number {tracking_number}. Is that correct?'):
            self._respond(agent, 'Okay, I will not add that. If you want to add a different package, tell me the number.')
            return

        # Ask for a friendly name if missing
        if not friendly_name:
            try:
                if hasattr(agent, 'ask'):
                    ans = agent.ask('What would you like to call this package? (e.g. "Mom\'s gift")')
                    if ans:
                        friendly_name = ans.strip()
            except Exception:
                pass

        # Preview and ask to save
        preview_name = friendly_name or tracking_number
        if not self._confirm(agent, f'Create tracking for "{preview_name}" ({tracking_number}) and save to your list?'):
            self._respond(agent, 'OK — I will not save that package.')
            return
        # Call TrackingMore to create tracking (best-effort; errors handled)
        try:
            params = {'tracking_number': tracking_number}
            if friendly_name:
                params['title'] = friendly_name
            tracking_resp = trackingmore.tracking.create_tracking(params)

            # Save locally, include courier_code if present in response
            courier_code = None
            try:
                # SDK responses vary: check common shapes
                if isinstance(tracking_resp, dict):
                    data = tracking_resp.get('data') or tracking_resp.get('tracking') or tracking_resp
                    if isinstance(data, dict):
                        courier_code = data.get('courier_code')
                    elif isinstance(data, list) and data:
                        courier_code = data[0].get('courier_code')
            except Exception:
                courier_code = None

            entry = {
                'friendly_name': friendly_name or tracking_number,
                'tracking_number': tracking_number,
                'courier_code': courier_code
            }
            # Avoid duplicates
            if not any(p['tracking_number'] == tracking_number for p in self.packages):
                self.packages.append(entry)
                self._save_packages()
            self._respond(agent, f'Added package "{entry["friendly_name"]}" to your tracked list.')
            logger.info('TrackingMore response: %s', tracking_resp)
        except Exception as e:
            # Handle TrackingMore-specific exceptions if available, otherwise generic
            if hasattr(trackingmore, 'exception') and hasattr(trackingmore.exception, 'TrackingMoreException') and isinstance(e, trackingmore.exception.TrackingMoreException):
                logger.exception('TrackingMore API error adding package: %s', e)
                self._respond(agent, f"I couldn't add that package due to an API error: {str(e)}")
            else:
                logger.exception('Error adding package: %s', e)
                self._respond(agent, f'Sorry, I could not add that package: {str(e)}')

    def handle_check_status(self, agent, identifier: Optional[str]):
        logger.debug(f"DEBUG: identifier received = {identifier}")
        if not identifier:
            # Ask which package
            try:
                if hasattr(agent, 'ask'):
                    identifier = agent.ask('Which package would you like to check? You can say a friendly name or tracking number.')
            except Exception:
                pass
            if not identifier:
                self._respond(agent, 'Which package would you like to check?')
                return

        # Resolve identifier to tracking number (may return multiple matches)
        matches = [p for p in self.packages if identifier.lower() in (p.get('friendly_name') or '').lower() or identifier == p.get('tracking_number')]
        if len(matches) > 1:
            # Ask user to choose
            options = '\n'.join([f'{i+1}. {m["friendly_name"]} — {m["tracking_number"]}' for i, m in enumerate(matches)])
            choice = None
            try:
                choice = agent.ask(f'I found multiple packages matching that. Which one did you mean?\n{options}\nReply with the number.')
            except Exception:
                pass
            try:
                idx = int(choice) - 1
                tracking_number = matches[idx]['tracking_number']
            except Exception:
                self._respond(agent, 'I did not get which package to check.')
                return
        elif len(matches) == 1:
            tracking_number = matches[0]['tracking_number']
        else:
            tracking_number = self._resolve_tracking_number(identifier)

        if not tracking_number:
            self._respond(agent, 'I could not find that package in your saved list.')
            return

        try:
            # Determine courier_code from stored package or attempt re-detect
            courier_code = None
            for p in self.packages:
                if p.get('tracking_number') == tracking_number:
                    courier_code = p.get('courier_code')
                    break

            if not courier_code:
                # Try SDK detect if available
                try:
                    detect = trackingmore.courier.detect({'tracking_number': tracking_number})
                    if isinstance(detect, list) and detect:
                        courier_code = detect[0].get('courier_code')
                except Exception:
                    courier_code = None

            # Use REST API to fetch status
            api_key = self.config.get('trackingmore_api_key') or os.getenv('TRACKINGMORE_API_KEY')
            if not api_key:
                self._respond(agent, 'API key not configured; cannot fetch live status.')
                return

            url = 'https://api.trackingmore.com/v4/trackings/get'
            params = {'tracking_numbers': tracking_number}
            if courier_code:
                params['courier_code'] = courier_code

            headers = {'Content-Type': 'application/json', 'Tracking-Api-Key': api_key}
            try:
                r = requests.get(url, params=params, headers=headers, timeout=10)
            except Exception as e:
                logger.exception('HTTP request failed: %s', e)
                self._respond(agent, 'Network error while contacting the tracking API.')
                return

            if r.status_code != 200:
                self._respond(agent, f'Tracking API returned status {r.status_code}: {r.text}')
                return

            try:
                resp_json = r.json()
            except Exception as e:
                logger.exception('Invalid JSON from tracking API: %s', e)
                self._respond(agent, 'Received invalid response from tracking API.')
                return

            # Normalize tracking data
            tracking_data = None
            if 'data' in resp_json:
                d = resp_json['data']
                if isinstance(d, list) and d:
                    tracking_data = d[0]
                elif isinstance(d, dict):
                    tracking_data = d
            else:
                tracking_data = resp_json

            if not tracking_data:
                self._respond(agent, 'No tracking information was returned.')
                return

            # Extract human-friendly status
            status_text = None
            # delivery_status (common), substatus, latest_event, or origin_info.trackinfo
            if isinstance(tracking_data, dict):
                status_text = tracking_data.get('delivery_status') or tracking_data.get('substatus')
                if not status_text:
                    # try latest_event or trackinfo
                    latest = None
                    if tracking_data.get('latest_event'):
                        latest = tracking_data.get('latest_event')
                    elif tracking_data.get('trackinfo'):
                        if isinstance(tracking_data.get('trackinfo'), list) and tracking_data.get('trackinfo'):
                            latest = tracking_data.get('trackinfo')[-1]
                    elif tracking_data.get('origin_info') and tracking_data.get('origin_info').get('trackinfo'):
                        ti = tracking_data.get('origin_info').get('trackinfo')
                        if isinstance(ti, list) and ti:
                            latest = ti[-1]
                    if latest:
                        if isinstance(latest, dict):
                            status_text = latest.get('status_description') or latest.get('status') or str(latest)
                        else:
                            status_text = str(latest)

            if not status_text:
                # fallback to raw json
                status_text = str(tracking_data)

            # Speak the result
            self._respond(agent, f'Latest status for {tracking_number}: {status_text}')
            logger.info('Status for %s: %s', tracking_number, tracking_data)
        except Exception as e:
            logger.exception('Error checking status: %s', e)
            self._respond(agent, 'Sorry, I could not retrieve the package status right now.')

    def handle_list_packages(self, agent):
        if not self.packages:
            self._respond(agent, 'You have no tracked packages.')
            return
        lines = [f'{idx+1}. {p.get("friendly_name") or p.get("tracking_number")} — {p.get("tracking_number")}' for idx, p in enumerate(self.packages)]
        text = 'Here are your tracked packages:\n' + '\n'.join(lines)
        self._respond(agent, text)

    def handle_remove_package(self, agent, identifier: Optional[str]):
        logger.info('handle_remove_package identifier=%r', identifier)
        if not identifier:
            try:
                if hasattr(agent, 'ask'):
                    identifier = agent.ask('Which package should I remove? You can say a friendly name or tracking number.')
            except Exception:
                pass
            if not identifier:
                self._respond(agent, 'Which package should I remove?')
                return

        # Find matches
        matches = [p for p in self.packages if identifier.lower() in (p.get('friendly_name') or '').lower() or identifier == p.get('tracking_number')]
        if not matches:
            self._respond(agent, 'I could not find that package to remove.')
            return
        if len(matches) > 1:
            options = '\n'.join([f'{i+1}. {m["friendly_name"]} — {m["tracking_number"]}' for i, m in enumerate(matches)])
            choice = None
            try:
                choice = agent.ask(f'I found multiple packages. Which one should I remove?\n{options}\nReply with the number.')
            except Exception:
                pass
            try:
                idx = int(choice) - 1
                to_remove = matches[idx]
            except Exception:
                self._respond(agent, 'I did not understand which package to remove.')
                return
        else:
            to_remove = matches[0]

        # Confirm removal
        if not self._confirm(agent, f'Are you sure you want to remove {to_remove.get(',
