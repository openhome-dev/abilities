"""OpenHome ability that proxies coding tasks to an external Codex webhook.

Conversation flow:
1) Ask for task.
2) Confirm intent.
3) Call webhook.
4) Speak result.

Client/server example:
- Client: OpenHome WebUI/voice runtime executing this ability.
- Server: any webhook server implementation exposing POST /run.
"""

import json
import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# Configure these directly before uploading to OpenHome WebUI.
WEBHOOK_URL = "YOUR_WEBHOOK_URL_HERE"
WEBHOOK_TOKEN = "YOUR_WEBHOOK_TOKEN_HERE"
REQUEST_TIMEOUT_SECONDS = 180
EXIT_WORDS = {"stop", "cancel", "exit", "quit", "never mind"}
MAX_LOG_PREVIEW_CHARS = 120
VOICE_SUMMARY_MAX_INPUT_CHARS = 3000
MAX_SPOKEN_SUMMARY_CHARS = 420


class CodexTaskRunnerCapability(MatchingCapability):
    """Ability entrypoint that coordinates speech UX and webhook execution."""

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        """Load ability metadata from config.json."""
        import os

        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        """OpenHome SDK hook; starts async ability flow."""
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.editor_logging_handler.info(
            "[CodexTaskRunner] capability called; starting async run task"
        )
        self.worker.session_tasks.create(self.run())

    def _preview(self, text: str) -> str:
        """Return compact preview string for logs."""
        compact = " ".join(text.split())
        if len(compact) <= MAX_LOG_PREVIEW_CHARS:
            return compact
        return f"{compact[:MAX_LOG_PREVIEW_CHARS]}..."

    def _is_configured(self) -> bool:
        """Return True when placeholders were replaced with real values."""
        return (
            WEBHOOK_URL
            and WEBHOOK_URL != "YOUR_WEBHOOK_URL_HERE"
            and WEBHOOK_TOKEN
            and WEBHOOK_TOKEN != "YOUR_WEBHOOK_TOKEN_HERE"
        )

    def _to_conversational_summary(self, raw_summary: str) -> str:
        """Rewrite structured webhook summary into short natural speech."""
        rewrite_prompt = (
            "Rewrite this coding result for spoken voice. "
            "Use 1-2 short conversational sentences. "
            "Do not read list numbers, markdown, file paths, or command snippets. "
            "Keep only the key outcome and one optional follow-up.\n\n"
            f"Result:\n{raw_summary[:VOICE_SUMMARY_MAX_INPUT_CHARS]}"
        )

        try:
            rewritten = self.capability_worker.text_to_text_response(
                rewrite_prompt,
                self.worker.agent_memory.full_message_history,
            )
            cleaned = (rewritten or "").replace("```", "").strip()
            if not cleaned:
                return raw_summary
            if len(cleaned) > MAX_SPOKEN_SUMMARY_CHARS:
                return f"{cleaned[:MAX_SPOKEN_SUMMARY_CHARS - 3].rstrip()}..."
            return cleaned
        except Exception as err:
            self.worker.editor_logging_handler.warning(
                f"[CodexTaskRunner] voice summary rewrite failed: {err}"
            )
            return raw_summary

    async def _call_webhook(self, user_request: str) -> dict | None:
        """Call webhook and return parsed JSON payload on success."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {WEBHOOK_TOKEN}",
        }

        self.worker.editor_logging_handler.info(
            "[CodexTaskRunner] sending webhook request "
            f"url={WEBHOOK_URL} prompt_len={len(user_request)}"
        )

        try:
            webhook_response = requests.post(
                WEBHOOK_URL,
                headers=headers,
                json={"prompt": user_request},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except Exception as err:
            self.worker.editor_logging_handler.error(
                f"[CodexTaskRunner] webhook request failed: {err}"
            )
            return None

        self.worker.editor_logging_handler.info(
            "[CodexTaskRunner] webhook response received "
            f"status={webhook_response.status_code}"
        )
        if webhook_response.status_code != 200:
            self.worker.editor_logging_handler.error(
                "[CodexTaskRunner] webhook non-200 response: "
                f"{webhook_response.status_code} {webhook_response.text}"
            )
            return None

        try:
            response_payload = webhook_response.json()
        except Exception as err:
            self.worker.editor_logging_handler.error(
                f"[CodexTaskRunner] invalid JSON response: {err}"
            )
            return None

        if not isinstance(response_payload, dict):
            self.worker.editor_logging_handler.error(
                "[CodexTaskRunner] webhook response is not an object"
            )
            return None

        return response_payload

    async def run(self):
        """Main conversation flow from user prompt to spoken result."""
        try:
            self.worker.editor_logging_handler.info(
                "[CodexTaskRunner] session started"
            )

            if not self._is_configured():
                self.worker.editor_logging_handler.error(
                    "[CodexTaskRunner] configuration error: replace webhook placeholders"
                )
                await self.capability_worker.speak(
                    "This Codex task runner is not configured yet. "
                    "Please set WEBHOOK_URL and WEBHOOK_TOKEN placeholders."
                )
                return

            # 2) Gather user task and handle fast cancel path.
            await self.capability_worker.speak(
                "Tell me the coding task you want Codex to run."
            )
            user_request = await self.capability_worker.user_response()

            if not user_request:
                self.worker.editor_logging_handler.warning(
                    "[CodexTaskRunner] user_request empty"
                )
                await self.capability_worker.speak(
                    "I didn't catch that. Please try again."
                )
                return

            self.worker.editor_logging_handler.info(
                "[CodexTaskRunner] user_request received "
                f"preview='{self._preview(user_request)}'"
            )

            lowered = user_request.lower().strip()
            if any(word in lowered for word in EXIT_WORDS):
                self.worker.editor_logging_handler.info(
                    "[CodexTaskRunner] exit word detected; canceling request"
                )
                await self.capability_worker.speak("Okay, canceled.")
                return

            # 3) Explicit confirmation before external execution.
            request_preview = self._preview(user_request)
            self.worker.editor_logging_handler.info(
                "[CodexTaskRunner] confirmation requested "
                f"preview='{request_preview}'"
            )
            confirmed = await self.capability_worker.run_confirmation_loop(
                "Got it. Want me to run Codex on that now?"
            )
            self.worker.editor_logging_handler.info(
                f"[CodexTaskRunner] confirmation_result={confirmed}"
            )
            if not confirmed:
                await self.capability_worker.speak("Okay, I won't run it.")
                return

            # 4) Execute request via webhook.
            await self.capability_worker.speak(
                "Running Codex now. This may take up to a few minutes."
            )
            webhook_result = await self._call_webhook(user_request)

            if not webhook_result or not webhook_result.get("ok"):
                self.worker.editor_logging_handler.error(
                    "[CodexTaskRunner] webhook returned failure payload"
                )
                await self.capability_worker.speak(
                    "I couldn't complete that Codex run right now. "
                    "Please check your webhook server logs."
                )
                return

            raw_summary = webhook_result.get("summary", "")
            if not raw_summary:
                raw_summary = "Codex finished, but the webhook returned no summary text."
            self.worker.editor_logging_handler.info(
                "[CodexTaskRunner] webhook success "
                f"request_id={webhook_result.get('request_id', '')} "
                "summary_len="
                f"{len(raw_summary)} artifact_path={webhook_result.get('artifact_path', '')}"
            )

            spoken_summary = self._to_conversational_summary(raw_summary)

            await self.capability_worker.speak(spoken_summary)

            artifact_path = webhook_result.get("artifact_path")
            if artifact_path:
                await self.capability_worker.speak(
                    "I also saved the full output in the run artifacts."
                )

        except Exception as err:
            self.worker.editor_logging_handler.error(
                f"[CodexTaskRunner] unexpected error: {err}"
            )
            await self.capability_worker.speak(
                "Something went wrong while running the coding task."
            )
        finally:
            # Always return control to normal personality flow.
            self.worker.editor_logging_handler.info(
                "[CodexTaskRunner] session finished; resuming normal flow"
            )
            self.capability_worker.resume_normal_flow()
