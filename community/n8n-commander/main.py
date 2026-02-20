import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests
from requests.auth import HTTPBasicAuth
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# where we store user's workflow config between sessions
PREFS_FILENAME = "n8n_commander_prefs.json"

# fresh install defaults — no workflows configured yet
DEFAULT_PREFS = {
    "n8n_base_url": "https://your-n8n-instance.app.n8n.cloud",
    "workflows": {},
    "webhook_auth": {},
    "phone_number": "",
    "twilio_account_sid": "",
    "twilio_auth_token": "",
    "twilio_from_number": "",
    "times_used": 0,
}

# user says any of these and we bail out of the conversation
EXIT_WORDS = {"exit", "stop", "quit", "done", "cancel", "bye", "goodbye", "never mind", "nevermind"}

# these trigger the help/listing flow instead of a workflow
HELP_PHRASES = {"help", "what can you do", "list workflows", "what are my workflows", "show workflows"}

# sign up for free at https://n8n.io to get your own webhook URLs
PLACEHOLDER_WEBHOOK = "REPLACE_WITH_YOUR_WEBHOOK_URL"

# prompt we feed to the LLM to figure out which workflow the user wants
# the double braces {{ }} are escaped so .format() doesn't eat them
CLASSIFY_PROMPT = """You are a voice command router. Given the user's spoken input and the list of available workflows, determine:
1. Which workflow to trigger (or "none" if no match)
2. What parameters to extract from the speech
3. A brief confirmation message to read back to the user

Available workflows:
{workflow_list}

User said: "{user_input}"

Return ONLY valid JSON:
{{
  "workflow_id": "string or none",
  "confidence": 0.0 to 1.0,
  "extracted_params": {{}},
  "message_content": "the core message or action description",
  "confirmation_text": "what to say back to confirm"
}}"""


class N8nCommanderCapability(MatchingCapability):
    """Voice-controlled n8n workflow trigger for OpenHome.

    Listens for voice commands, classifies which workflow the user wants
    using keywords + LLM, then fires the matching n8n webhook.
    Supports fire-and-forget and round-trip response workflows.
    """

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    initial_request: Optional[str] = None
    last_utterance: str = ""  # raw text of what user last said, sent in webhook payload

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        """Load trigger hotwords from config.json — standard pattern for all abilities."""
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        """Entry point when the platform matches our hotwords.

        We try a few different attrs to grab the user's original speech
        because different SDK versions expose it differently.
        """
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.initial_request = None

        # try to grab what the user actually said that triggered us
        try:
            self.initial_request = worker.transcription
        except Exception:
            pass
        if not self.initial_request:
            try:
                self.initial_request = worker.last_transcription
            except Exception:
                pass
        if not self.initial_request:
            try:
                self.initial_request = worker.current_transcription
            except Exception:
                pass

        # kick off the main loop as an async task
        self.worker.session_tasks.create(self.run())

    # logging — uses the platform logger so output shows in editor console

    def _log_info(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.info(msg)

    def _log_error(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.error(msg)

    # json helpers

    def _clean_json(self, raw: str) -> str:
        """Strip markdown fences and grab just the JSON object.

        The LLM sometimes wraps its response in ```json ... ``` blocks,
        so we need to peel that off before parsing.
        """
        cleaned = (raw or "").strip().replace("```json", "").replace("```", "").strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            return cleaned[start : end + 1]
        return cleaned

    # prefs management
    # stored via the platform file API (not local disk) so they
    # persist across sessions and devices for each user

    async def load_prefs(self) -> dict:
        """Load user preferences from persistent storage.

        Returns defaults if file doesn't exist yet (first run).
        """
        try:
            exists = await self.capability_worker.check_if_file_exists(
                PREFS_FILENAME, False
            )
            if exists:
                raw = await self.capability_worker.read_file(PREFS_FILENAME, False)
                if raw and raw.strip():
                    return json.loads(raw)
        except Exception as e:
            self._log_error(f"[N8nCommander] Failed to load prefs: {e}")
        return dict(DEFAULT_PREFS)

    async def save_prefs(self, prefs: dict):
        """Save prefs back to persistent storage.

        Important: we have to delete first then write — the platform
        file API appends on write, so writing over an existing JSON
        file would corrupt it without the delete step.
        """
        try:
            if await self.capability_worker.check_if_file_exists(PREFS_FILENAME, False):
                await self.capability_worker.delete_file(PREFS_FILENAME, False)
            await self.capability_worker.write_file(
                PREFS_FILENAME, json.dumps(prefs, indent=2), False
            )
        except Exception as e:
            self._log_error(f"[N8nCommander] Failed to save prefs: {e}")

    # trigger context

    def _best_initial_input(self) -> str:
        """Try to recover the user's trigger phrase.

        Sometimes the trigger phrase itself contains the command
        (e.g. "post to slack that the deploy is done"), so we want
        to capture it and skip asking again.
        Falls back to recent message history if transcription is empty.
        """
        if self.initial_request and self.initial_request.strip():
            return self.initial_request.strip()
        try:
            history = self.worker.agent_memory.full_message_history or []
            for msg in reversed(history):
                role = str(msg.get("role", "")).lower()
                content = str(msg.get("content", "") or "").strip()
                if role == "user" and content:
                    return content
        except Exception:
            pass
        return ""

    # exit and help detection

    def _is_exit(self, text: Optional[str]) -> bool:
        """Check if the user wants to leave."""
        lowered = (text or "").lower().strip()
        if not lowered:
            return False
        return any(word in lowered for word in EXIT_WORDS)

    def _is_help(self, text: Optional[str]) -> bool:
        """Check if the user is asking what we can do."""
        lowered = (text or "").lower().strip()
        if not lowered:
            return False
        return any(phrase in lowered for phrase in HELP_PHRASES)

    # keyword prefilter
    # fast first pass — scan user speech against trigger_phrases
    # defined in each workflow. longer matches score higher.

    def keyword_prefilter(self, user_input: str, workflows: dict) -> List[Tuple[str, int]]:
        """Score each workflow by how many trigger phrases match the input.

        Returns sorted list of (workflow_id, score) — highest first.
        Longer phrase matches get more weight since they're more specific.
        """
        input_lower = (user_input or "").lower()
        scores: Dict[str, int] = {}
        for wf_id, wf in workflows.items():
            score = 0
            for phrase in wf.get("trigger_phrases", []):
                if phrase.lower() in input_lower:
                    score += len(phrase)
            if score > 0:
                scores[wf_id] = score
        return sorted(scores.items(), key=lambda x: x[1], reverse=True)

    # LLM intent classification
    # second pass — send workflow list + user input to the LLM
    # and let it figure out the best match with extracted params

    def build_workflow_list(self, workflows: dict) -> str:
        """Format workflows into a readable list for the LLM prompt."""
        lines = []
        for wf_id, wf in workflows.items():
            lines.append(
                f'- ID: "{wf_id}" | Name: {wf.get("name", wf_id)} | '
                f'Description: {wf.get("description", "No description")} | '
                f'Default params: {json.dumps(wf.get("default_params", {}))}'
            )
        return "\n".join(lines)

    def classify_intent(self, user_input: str, workflows: dict) -> dict:
        """Ask the LLM which workflow matches the user's voice input.

        Note: text_to_text_response() is synchronous (no await).
        Returns a dict with workflow_id, confidence, extracted_params, etc.
        Falls back to a "no match" result if anything goes wrong.
        """
        workflow_list = self.build_workflow_list(workflows)
        prompt = CLASSIFY_PROMPT.format(
            workflow_list=workflow_list, user_input=user_input
        )
        fallback = {
            "workflow_id": "none",
            "confidence": 0.0,
            "extracted_params": {},
            "message_content": "",
            "confirmation_text": "",
        }
        try:
            # sync call — no await here, that's how the SDK works
            raw = self.capability_worker.text_to_text_response(prompt)
            cleaned = self._clean_json(raw)
            parsed = json.loads(cleaned)
            result = {
                "workflow_id": str(parsed.get("workflow_id", "none")).strip(),
                "confidence": float(parsed.get("confidence", 0.0)),
                "extracted_params": parsed.get("extracted_params", {}),
                "message_content": str(parsed.get("message_content", "")),
                "confirmation_text": str(parsed.get("confirmation_text", "")),
            }
            self._log_info(f"[N8nCommander] LLM classified: {result['workflow_id']} "
                           f"(confidence: {result['confidence']:.2f})")
            return result
        except Exception as e:
            self._log_error(f"[N8nCommander] LLM classify error: {e}")
            return fallback

    # classification decision logic
    # combines keyword + LLM results to make a final call:
    # high confidence LLM → trust it
    # medium + keyword agrees → trust it
    # medium + keyword disagrees → ask user
    # keyword only → confirm first

    def resolve_intent(
        self, user_input: str, workflows: dict
    ) -> dict:
        """Two-pass classification: keywords first, then LLM.

        Merges both results and decides whether we're confident enough
        to just go, or need to ask the user for clarification.
        """
        keyword_matches = self.keyword_prefilter(user_input, workflows)
        llm_result = self.classify_intent(user_input, workflows)

        llm_wf = llm_result.get("workflow_id", "none")
        confidence = llm_result.get("confidence", 0.0)

        # high confidence from LLM — just go with it
        if confidence >= 0.8 and llm_wf != "none" and llm_wf in workflows:
            llm_result["source"] = "llm_high_confidence"
            return llm_result

        top_keyword = keyword_matches[0][0] if keyword_matches else None

        # medium confidence — check if keyword agrees
        if confidence >= 0.5 and llm_wf != "none" and llm_wf in workflows:
            if top_keyword and top_keyword == llm_wf:
                # keyword and LLM agree, good enough
                llm_result["source"] = "llm_keyword_agree"
                return llm_result
            elif top_keyword and top_keyword != llm_wf:
                # keyword and LLM disagree — need to ask user
                llm_result["source"] = "ambiguous"
                llm_result["keyword_suggestion"] = top_keyword
                return llm_result
            else:
                # no keyword match but LLM is somewhat confident
                llm_result["source"] = "llm_medium_confidence"
                return llm_result

        # LLM wasn't confident — fall back to keyword match if we have one
        if top_keyword and top_keyword in workflows:
            return {
                "workflow_id": top_keyword,
                "confidence": 0.4,
                "extracted_params": llm_result.get("extracted_params", {}),
                "message_content": llm_result.get("message_content", ""),
                "confirmation_text": llm_result.get("confirmation_text", ""),
                "source": "keyword_only",
            }

        # nothing matched at all
        return {
            "workflow_id": "none",
            "confidence": 0.0,
            "extracted_params": {},
            "message_content": "",
            "confirmation_text": "",
            "source": "no_match",
        }

    # webhook headers (optional auth)

    def build_headers(self, prefs: dict) -> dict:
        """Build request headers, optionally including auth from prefs.

        If the user configured a webhook secret in their prefs,
        we attach it as a custom header so n8n can validate it.
        """
        headers = {"Content-Type": "application/json"}
        auth = prefs.get("webhook_auth", {})
        if (
            auth.get("type") == "header"
            and auth.get("header_name")
            and auth.get("header_value")
        ):
            headers[auth["header_name"]] = auth["header_value"]
        return headers

    # webhook calling

    def call_webhook(
        self,
        prefs: dict,
        workflow_id: str,
        message_content: str,
        extracted_params: dict,
    ) -> dict:
        """POST to the n8n webhook URL for the given workflow.

        Merges default_params from config with whatever the LLM extracted
        from the user's speech. Uses 15s timeout for fire-and-forget,
        30s for workflows that return data.
        """
        workflow = prefs["workflows"][workflow_id]
        webhook_url = workflow["webhook_url"]

        # basic sanity check — don't send to http or garbage URLs
        if not webhook_url.startswith("https://"):
            return {"success": False, "error": "invalid_url"}

        # merge defaults with whatever the LLM pulled from the voice input
        params = {**workflow.get("default_params", {}), **extracted_params}

        # standard payload format — n8n workflow can use any of these fields
        payload = {
            "workflow_id": workflow_id,
            "action": workflow.get("name", workflow_id),
            "message": message_content,
            "params": params,
            "raw_utterance": self.last_utterance,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "openhome_voice",
        }

        headers = self.build_headers(prefs)

        # longer timeout for workflows that send back data
        timeout = 30 if workflow.get("expects_response") else 15

        try:
            response = requests.post(
                webhook_url, json=payload, headers=headers, timeout=timeout
            )
            if response.status_code == 200:
                if workflow.get("expects_response"):
                    try:
                        return {"success": True, "data": response.json()}
                    except json.JSONDecodeError:
                        # got 200 but body wasn't JSON — still a success
                        return {"success": True, "data": None}
                else:
                    # fire-and-forget — don't care about the body
                    return {"success": True, "data": None}
            else:
                self._log_error(
                    f"[N8nCommander] Webhook {workflow_id} returned "
                    f"{response.status_code}: {response.text[:200]}"
                )
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                    "status": response.status_code,
                }
        except requests.exceptions.Timeout:
            return {"success": False, "error": "timeout"}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": "connection_failed"}
        except Exception as e:
            self._log_error(f"[N8nCommander] Webhook call failed: {e}")
            return {"success": False, "error": str(e)}

    # error to speech mapping
    # each error gets a specific spoken message so user knows what went wrong

    def error_to_speech(self, result: dict) -> str:
        """Convert a webhook error into a friendly voice response."""
        error = result.get("error", "")
        status = result.get("status", 0)

        if error == "timeout":
            return (
                "The workflow is taking too long. "
                "It might still be running. Check n8n to confirm."
            )
        if error == "connection_failed":
            return (
                "I can't reach your n8n instance. "
                "Make sure it's running and the URL is correct."
            )
        if error == "invalid_url":
            return (
                "That workflow's webhook URL doesn't look right. "
                "Make sure it starts with https in the preferences file."
            )
        if status == 404:
            return (
                "That workflow's webhook isn't responding. "
                "Make sure the workflow is activated in n8n."
            )
        if status == 401:
            return (
                "The webhook requires authentication. "
                "Check that your credentials are configured in n8n."
            )
        if status == 500:
            return (
                "Something went wrong inside the n8n workflow. "
                "Check the execution log in n8n for details."
            )
        return "Something went wrong with that workflow. Please try again."

    # response handling

    async def handle_webhook_response(self, result: dict, workflow: dict, prefs: dict):
        """Process the webhook result and speak it back to the user.

        For fire-and-forget: just say "done".
        For expects_response: read back the spoken_response from n8n.
        If the response is too long (>300 chars), summarize it and
        optionally text the full version via Twilio.
        """
        # webhook failed — tell user what went wrong
        if not result.get("success"):
            await self.capability_worker.speak(self.error_to_speech(result))
            return

        data = result.get("data")
        workflow_name = workflow.get("name", "the workflow")

        # fire-and-forget or no data came back
        if not workflow.get("expects_response") or data is None:
            await self.capability_worker.speak(f"Done. {workflow_name} triggered.")
            return

        if isinstance(data, dict):
            # n8n reported an error in its own response
            if not data.get("success", True):
                error_msg = data.get("error", "unknown error")
                await self.capability_worker.speak(
                    f"The workflow ran but reported an error: {error_msg}."
                )
                return

            spoken = data.get("spoken_response", "")
            sms_body = data.get("sms_body", "")
            url_field = data.get("url", "")

            if spoken:
                # if response is really long, truncate for voice and text the rest
                if len(spoken) > 300:
                    summary = spoken[:250].rsplit(" ", 1)[0] + "..."
                    await self.capability_worker.speak(summary)
                    if self._has_twilio(prefs):
                        sent = self.send_sms(prefs, spoken)
                        if sent:
                            await self.capability_worker.speak(
                                "I also texted you the full details."
                            )
                else:
                    await self.capability_worker.speak(spoken)
            else:
                await self.capability_worker.speak(
                    "Done. The workflow ran successfully."
                )

            # n8n can also send a separate sms_body for extra info
            if sms_body and self._has_twilio(prefs):
                sent = self.send_sms(prefs, sms_body)
                if sent:
                    await self.capability_worker.speak("I also texted you extra details.")

            # or just a URL the user might want on their phone
            if url_field and self._has_twilio(prefs) and not sms_body:
                sent = self.send_sms(prefs, f"Link from your workflow: {url_field}")
                if sent:
                    await self.capability_worker.speak(
                        "I texted you the link from that workflow."
                    )
        else:
            await self.capability_worker.speak("Done. The workflow ran successfully.")

    # twilio sms (optional)
    # only kicks in when user has configured twilio creds in prefs
    # useful for sending URLs or long text that doesn't work as speech

    def _has_twilio(self, prefs: dict) -> bool:
        """Quick check — are all 4 twilio fields filled in?"""
        return all([
            prefs.get("twilio_account_sid"),
            prefs.get("twilio_auth_token"),
            prefs.get("twilio_from_number"),
            prefs.get("phone_number"),
        ])

    def send_sms(self, prefs: dict, message_body: str) -> bool:
        """Send a text message via Twilio. Returns True if sent ok."""
        account_sid = prefs.get("twilio_account_sid", "")
        auth_token = prefs.get("twilio_auth_token", "")
        from_number = prefs.get("twilio_from_number", "")
        to_number = prefs.get("phone_number", "")

        if not all([account_sid, auth_token, from_number, to_number]):
            self._log_info("[N8nCommander] Twilio not configured, skipping SMS")
            return False

        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"

        try:
            response = requests.post(
                url,
                data={"From": from_number, "To": to_number, "Body": message_body},
                auth=HTTPBasicAuth(account_sid, auth_token),
                timeout=15,
            )
            if response.status_code == 201:
                self._log_info(f"[N8nCommander] SMS sent to {to_number}")
                return True
            else:
                self._log_error(
                    f"[N8nCommander] SMS failed: {response.status_code}"
                )
                return False
        except Exception as e:
            self._log_error(f"[N8nCommander] SMS error: {e}")
            return False

    # help handler

    async def speak_help(self, workflows: dict):
        """List available workflows by name so user can pick one."""
        if not workflows:
            await self.capability_worker.speak(
                "You haven't set up any workflows yet."
            )
            await self.capability_worker.speak(
                "Add your n8n webhook URLs in the preferences file to get started."
            )
            return

        count = len(workflows)
        names = []
        for wf in workflows.values():
            name = wf.get("name", "unnamed")
            names.append(name)

        # only read out the first 5 so we don't bore the user
        display_names = names[:5]

        if count > 1:
            await self.capability_worker.speak(f"You have {count} workflows set up.")
        else:
            await self.capability_worker.speak("You have one workflow set up.")

        await self.capability_worker.speak(", ".join(display_names) + ".")

        if count > 5:
            await self.capability_worker.speak(f"Plus {count - 5} more.")

        await self.capability_worker.speak("Which one would you like?")

    # main conversation loop

    async def run(self):
        """Main loop — handles the full voice conversation flow.

        Flow: greet → listen → classify → confirm → fire webhook → respond → loop
        Every exit path (return, exception) hits the finally block
        which calls resume_normal_flow() to hand control back.
        """
        try:
            # small delay to let the audio pipeline settle
            if self.worker:
                await self.worker.session_tasks.sleep(0.2)

            prefs = await self.load_prefs()
            workflows = prefs.get("workflows", {})

            # no workflows configured — guide the user and exit
            if not workflows:
                await self.capability_worker.speak(
                    "Hey, I'm your automation assistant."
                )
                await self.capability_worker.speak(
                    "You haven't configured any workflows yet. "
                    "Add your n8n webhook URLs in the preferences file to get started."
                )
                # drop a default prefs file so user has a template to fill in
                exists = await self.capability_worker.check_if_file_exists(
                    PREFS_FILENAME, False
                )
                if not exists:
                    await self.save_prefs(DEFAULT_PREFS)
                return

            # greet the user
            count = len(workflows)
            await self.capability_worker.speak(
                "Hey, I'm your automation assistant. "
                "I can trigger your n8n workflows by voice."
            )
            await self.capability_worker.speak(
                f"You have {count} workflow{'s' if count != 1 else ''} set up. "
                "Say help to hear them, or tell me what you need."
            )

            # check if the trigger phrase already contains a command
            # e.g. user said "post to slack that we shipped" — no need to ask again
            initial_input = self._best_initial_input()
            current_input = ""

            if initial_input:
                keyword_hits = self.keyword_prefilter(initial_input, workflows)
                if keyword_hits:
                    current_input = initial_input

            # track consecutive empty inputs so we can auto-exit
            idle_count = 0

            while True:
                # prompt for input if we don't already have something to process
                if not current_input:
                    current_input = await self.capability_worker.run_io_loop(
                        "What would you like to do?"
                    )

                user_text = (current_input or "").strip()
                self.last_utterance = user_text
                current_input = ""  # reset for next iteration

                # user didn't say anything
                if not user_text:
                    idle_count += 1
                    if idle_count >= 2:
                        # been quiet too long — offer to sign off
                        await self.capability_worker.speak(
                            "I'm still here if you need anything. Otherwise I'll sign off."
                        )
                        final = await self.capability_worker.run_io_loop("")
                        if not final or not final.strip() or self._is_exit(final):
                            await self.capability_worker.speak("See you later.")
                            return
                        current_input = final.strip()
                        idle_count = 0
                        continue
                    continue

                idle_count = 0

                # user wants to leave
                if self._is_exit(user_text):
                    await self.capability_worker.speak("See you later.")
                    return

                # user wants to know what we can do
                if self._is_help(user_text):
                    await self.speak_help(workflows)
                    continue

                # --- Intent classification ---
                # filler speech while LLM thinks (this takes a sec)
                await self.capability_worker.speak("One sec, figuring that out.")
                intent = self.resolve_intent(user_text, workflows)
                wf_id = intent.get("workflow_id", "none")
                confidence = intent.get("confidence", 0.0)
                source = intent.get("source", "")

                # couldn't figure out what they want
                if wf_id == "none" or wf_id not in workflows:
                    wf_names = [
                        wf.get("name", wf_id)
                        for wf_id, wf in workflows.items()
                    ]
                    names_str = ", ".join(wf_names[:5])
                    await self.capability_worker.speak(
                        "I'm not sure which workflow to use. "
                        f"Your options are: {names_str}. Which one?"
                    )
                    continue

                # keyword and LLM disagree — ask user to pick
                if source == "ambiguous":
                    keyword_wf = intent.get("keyword_suggestion", "")
                    llm_name = workflows[wf_id].get("name", wf_id)
                    kw_name = workflows.get(keyword_wf, {}).get("name", keyword_wf)
                    clarify = await self.capability_worker.run_io_loop(
                        f"Did you mean {llm_name} or {kw_name}?"
                    )
                    if clarify and clarify.strip():
                        current_input = clarify.strip()
                    continue

                # matched on keyword only (low confidence) — double check
                if source == "keyword_only":
                    wf_name = workflows[wf_id].get("name", wf_id)
                    confirm_text = f"Did you mean {wf_name}?"
                    confirmed = await self.capability_worker.run_confirmation_loop(
                        confirm_text
                    )
                    if not confirmed:
                        await self.capability_worker.speak(
                            "Okay. Which workflow did you want?"
                        )
                        continue

                # --- We have a match, prepare to fire ---
                workflow = workflows[wf_id]
                extracted_params = intent.get("extracted_params", {})
                message_content = intent.get("message_content", "")
                confirmation_text = intent.get("confirmation_text", "")

                # some workflows need explicit user confirmation before firing
                if workflow.get("confirm_before_send", False):
                    if confirmation_text:
                        confirm_msg = confirmation_text + " Go ahead?"
                    else:
                        confirm_msg = (
                            f"I'll trigger {workflow.get('name', wf_id)}. Go ahead?"
                        )
                    confirmed = await self.capability_worker.run_confirmation_loop(
                        confirm_msg
                    )
                    if not confirmed:
                        await self.capability_worker.speak(
                            "Okay, cancelled. What else?"
                        )
                        continue

                # --- Fire the webhook ---
                await self.capability_worker.speak("Standby, running that now.")
                result = self.call_webhook(
                    prefs, wf_id, message_content, extracted_params
                )

                # speak the result back to the user
                await self.handle_webhook_response(result, workflow, prefs)

                # bump the usage counter
                prefs["times_used"] = prefs.get("times_used", 0) + 1
                await self.save_prefs(prefs)

                # ask if they want to do something else
                follow_up = await self.capability_worker.run_io_loop(
                    "Anything else?"
                )
                if not follow_up or not follow_up.strip() or self._is_exit(follow_up):
                    await self.capability_worker.speak("See you later.")
                    return

                current_input = follow_up.strip()

        except Exception as e:
            self._log_error(f"[N8nCommander] Unexpected error: {e}")
            if self.capability_worker:
                await self.capability_worker.speak(
                    "Sorry, something went wrong. Please try again."
                )
        finally:
            # always hand control back to the platform — no matter what
            self.capability_worker.resume_normal_flow()
