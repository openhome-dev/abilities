import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests
from requests.auth import HTTPBasicAuth
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

PREFS_FILENAME = "n8n_commander_prefs.json"

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

EXIT_WORDS = {"exit", "stop", "quit", "done", "cancel", "bye", "goodbye", "never mind", "nevermind"}

HELP_PHRASES = {"help", "what can you do", "list workflows", "what are my workflows", "show workflows"}

# Replace with your own n8n webhook URL from https://n8n.io
PLACEHOLDER_WEBHOOK = "REPLACE_WITH_YOUR_WEBHOOK_URL"

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
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    initial_request: Optional[str] = None
    last_utterance: str = ""

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.initial_request = None
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
        self.worker.session_tasks.create(self.run())

    # ── Logging ──────────────────────────────────────────────────────

    def _log_info(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.info(msg)

    def _log_error(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.error(msg)

    # ── JSON Helpers ─────────────────────────────────────────────────

    def _clean_json(self, raw: str) -> str:
        cleaned = (raw or "").strip().replace("```json", "").replace("```", "").strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            return cleaned[start : end + 1]
        return cleaned

    # ── Prefs Management ─────────────────────────────────────────────

    async def load_prefs(self) -> dict:
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
        try:
            if await self.capability_worker.check_if_file_exists(PREFS_FILENAME, False):
                await self.capability_worker.delete_file(PREFS_FILENAME, False)
            await self.capability_worker.write_file(
                PREFS_FILENAME, json.dumps(prefs, indent=2), False
            )
        except Exception as e:
            self._log_error(f"[N8nCommander] Failed to save prefs: {e}")

    # ── Trigger Context ──────────────────────────────────────────────

    def _best_initial_input(self) -> str:
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

    # ── Exit / Help Detection ────────────────────────────────────────

    def _is_exit(self, text: Optional[str]) -> bool:
        lowered = (text or "").lower().strip()
        if not lowered:
            return False
        return any(word in lowered for word in EXIT_WORDS)

    def _is_help(self, text: Optional[str]) -> bool:
        lowered = (text or "").lower().strip()
        if not lowered:
            return False
        return any(phrase in lowered for phrase in HELP_PHRASES)

    # ── Keyword Prefilter (Phase 1) ──────────────────────────────────

    def keyword_prefilter(self, user_input: str, workflows: dict) -> List[Tuple[str, int]]:
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

    # ── LLM Intent Classification (Phase 2) ──────────────────────────

    def build_workflow_list(self, workflows: dict) -> str:
        lines = []
        for wf_id, wf in workflows.items():
            lines.append(
                f'- ID: "{wf_id}" | Name: {wf.get("name", wf_id)} | '
                f'Description: {wf.get("description", "No description")} | '
                f'Default params: {json.dumps(wf.get("default_params", {}))}'
            )
        return "\n".join(lines)

    def classify_intent(self, user_input: str, workflows: dict) -> dict:
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

    # ── Classification Decision Logic ────────────────────────────────

    def resolve_intent(
        self, user_input: str, workflows: dict
    ) -> dict:
        keyword_matches = self.keyword_prefilter(user_input, workflows)
        llm_result = self.classify_intent(user_input, workflows)

        llm_wf = llm_result.get("workflow_id", "none")
        confidence = llm_result.get("confidence", 0.0)

        if confidence >= 0.8 and llm_wf != "none" and llm_wf in workflows:
            llm_result["source"] = "llm_high_confidence"
            return llm_result

        top_keyword = keyword_matches[0][0] if keyword_matches else None

        if confidence >= 0.5 and llm_wf != "none" and llm_wf in workflows:
            if top_keyword and top_keyword == llm_wf:
                llm_result["source"] = "llm_keyword_agree"
                return llm_result
            elif top_keyword and top_keyword != llm_wf:
                llm_result["source"] = "ambiguous"
                llm_result["keyword_suggestion"] = top_keyword
                return llm_result
            else:
                llm_result["source"] = "llm_medium_confidence"
                return llm_result

        if top_keyword and top_keyword in workflows:
            return {
                "workflow_id": top_keyword,
                "confidence": 0.4,
                "extracted_params": llm_result.get("extracted_params", {}),
                "message_content": llm_result.get("message_content", ""),
                "confirmation_text": llm_result.get("confirmation_text", ""),
                "source": "keyword_only",
            }

        return {
            "workflow_id": "none",
            "confidence": 0.0,
            "extracted_params": {},
            "message_content": "",
            "confirmation_text": "",
            "source": "no_match",
        }

    # ── Webhook Headers (Phase 8) ────────────────────────────────────

    def build_headers(self, prefs: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        auth = prefs.get("webhook_auth", {})
        if (
            auth.get("type") == "header"
            and auth.get("header_name")
            and auth.get("header_value")
        ):
            headers[auth["header_name"]] = auth["header_value"]
        return headers

    # ── Webhook Calling (Phase 3) ────────────────────────────────────

    def call_webhook(
        self,
        prefs: dict,
        workflow_id: str,
        message_content: str,
        extracted_params: dict,
    ) -> dict:
        workflow = prefs["workflows"][workflow_id]
        webhook_url = workflow["webhook_url"]

        if not webhook_url.startswith("https://"):
            return {"success": False, "error": "invalid_url"}

        params = {**workflow.get("default_params", {}), **extracted_params}

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
                        return {"success": True, "data": None}
                else:
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

    # ── Error-to-Speech Mapping (Phase 7) ────────────────────────────

    def error_to_speech(self, result: dict) -> str:
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

    # ── Response Handling (Phase 6) ──────────────────────────────────

    async def handle_webhook_response(self, result: dict, workflow: dict, prefs: dict):
        if not result.get("success"):
            await self.capability_worker.speak(self.error_to_speech(result))
            return

        data = result.get("data")
        workflow_name = workflow.get("name", "the workflow")

        if not workflow.get("expects_response") or data is None:
            await self.capability_worker.speak(f"Done. {workflow_name} triggered.")
            return

        if isinstance(data, dict):
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

            if sms_body and self._has_twilio(prefs):
                sent = self.send_sms(prefs, sms_body)
                if sent:
                    await self.capability_worker.speak("I also texted you extra details.")

            if url_field and self._has_twilio(prefs) and not sms_body:
                sent = self.send_sms(prefs, f"Link from your workflow: {url_field}")
                if sent:
                    await self.capability_worker.speak(
                        "I texted you the link from that workflow."
                    )
        else:
            await self.capability_worker.speak("Done. The workflow ran successfully.")

    # ── Twilio SMS (Optional) ────────────────────────────────────────

    def _has_twilio(self, prefs: dict) -> bool:
        return all([
            prefs.get("twilio_account_sid"),
            prefs.get("twilio_auth_token"),
            prefs.get("twilio_from_number"),
            prefs.get("phone_number"),
        ])

    def send_sms(self, prefs: dict, message_body: str) -> bool:
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

    # ── Help Handler ─────────────────────────────────────────────────

    async def speak_help(self, workflows: dict):
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

        display_names = names[:5]

        if count > 1:
            await self.capability_worker.speak(f"You have {count} workflows set up.")
        else:
            await self.capability_worker.speak("You have one workflow set up.")

        await self.capability_worker.speak(", ".join(display_names) + ".")

        if count > 5:
            await self.capability_worker.speak(f"Plus {count - 5} more.")

        await self.capability_worker.speak("Which one would you like?")

    # ── Main Conversation Loop (Phase 5) ─────────────────────────────

    async def run(self):
        try:
            if self.worker:
                await self.worker.session_tasks.sleep(0.2)

            prefs = await self.load_prefs()
            workflows = prefs.get("workflows", {})

            # Phase 0: Detect empty workflows
            if not workflows:
                await self.capability_worker.speak(
                    "Hey, I'm your automation assistant."
                )
                await self.capability_worker.speak(
                    "You haven't configured any workflows yet. "
                    "Add your n8n webhook URLs in the preferences file to get started."
                )
                # Create default prefs file on first run
                exists = await self.capability_worker.check_if_file_exists(
                    PREFS_FILENAME, False
                )
                if not exists:
                    await self.save_prefs(DEFAULT_PREFS)
                return

            # Entry message
            count = len(workflows)
            await self.capability_worker.speak(
                f"Hey, I'm your automation assistant. "
                f"I can trigger your n8n workflows by voice."
            )
            await self.capability_worker.speak(
                f"You have {count} workflow{'s' if count != 1 else ''} set up. "
                f"Say help to hear them, or tell me what you need."
            )

            # Check if the initial trigger already contains a command
            initial_input = self._best_initial_input()
            current_input = ""

            # See if the trigger phrase itself contains a workflow command
            if initial_input:
                keyword_hits = self.keyword_prefilter(initial_input, workflows)
                if keyword_hits:
                    current_input = initial_input

            # Main loop
            idle_count = 0
            while True:
                # Get user input if we don't already have it
                if not current_input:
                    current_input = await self.capability_worker.run_io_loop(
                        "What would you like to do?"
                    )

                user_text = (current_input or "").strip()
                self.last_utterance = user_text
                current_input = ""

                # Empty input
                if not user_text:
                    idle_count += 1
                    if idle_count >= 2:
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

                # Exit check
                if self._is_exit(user_text):
                    await self.capability_worker.speak("See you later.")
                    return

                # Help check
                if self._is_help(user_text):
                    await self.speak_help(workflows)
                    continue

                # Classify intent
                await self.capability_worker.speak("One sec, figuring that out.")
                intent = self.resolve_intent(user_text, workflows)
                wf_id = intent.get("workflow_id", "none")
                confidence = intent.get("confidence", 0.0)
                source = intent.get("source", "")

                # No match
                if wf_id == "none" or wf_id not in workflows:
                    wf_names = [
                        wf.get("name", wf_id)
                        for wf_id, wf in workflows.items()
                    ]
                    names_str = ", ".join(wf_names[:5])
                    await self.capability_worker.speak(
                        f"I'm not sure which workflow to use. "
                        f"Your options are: {names_str}. Which one?"
                    )
                    continue

                # Ambiguous match — ask user to pick
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

                # Low confidence — ask for confirmation
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

                # We have a valid workflow — execute it
                workflow = workflows[wf_id]
                extracted_params = intent.get("extracted_params", {})
                message_content = intent.get("message_content", "")
                confirmation_text = intent.get("confirmation_text", "")

                # Phase 4: Confirmation loop
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

                # Phase 3 & 6: Execute webhook
                await self.capability_worker.speak("Standby, running that now.")
                result = self.call_webhook(
                    prefs, wf_id, message_content, extracted_params
                )

                # Handle response
                await self.handle_webhook_response(result, workflow, prefs)

                # Update usage count
                prefs["times_used"] = prefs.get("times_used", 0) + 1
                await self.save_prefs(prefs)

                # Continue loop
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
            self.capability_worker.resume_normal_flow()
