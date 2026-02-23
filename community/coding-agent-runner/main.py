"""OpenHome ability – voice-triggered coding task execution via webhook.

Flow: ask → confirm → refine prompt → call webhook → speak result.
"""

import asyncio

import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

WEBHOOK_URL = "YOUR_WEBHOOK_URL_HERE"
WEBHOOK_TOKEN = "YOUR_WEBHOOK_TOKEN_HERE"
REQUEST_TIMEOUT_SECONDS = 180
EXIT_WORDS = {"stop", "cancel", "exit", "quit", "never mind"}

TAG = "[CodingAgentRunner]"


class CodingAgentRunnerCapability(MatchingCapability):
    """Voice ability that sends coding tasks to an external webhook."""

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            # 1) Guard: ensure webhook is configured.
            if WEBHOOK_URL in ("", "YOUR_WEBHOOK_URL_HERE") \
                    or WEBHOOK_TOKEN in ("", "YOUR_WEBHOOK_TOKEN_HERE"):
                await self.capability_worker.speak(
                    "This coding agent runner is not configured yet. "
                    "Please set the webhook URL and token in the ability code."
                )
                return

            # 2) Ask for the coding task.
            await self.capability_worker.speak(
                "Tell me the coding task you'd like to run."
            )
            task = await self.capability_worker.user_response()

            if not task:
                await self.capability_worker.speak(
                    "I didn't catch that. Please try again."
                )
                return

            lowered = task.lower().strip()
            if any(lowered == w or lowered.startswith(f"{w} ") for w in EXIT_WORDS):
                await self.capability_worker.speak("Okay, canceled.")
                return

            # 3) Confirm before running.
            if not await self.capability_worker.run_confirmation_loop(
                "Got it. Want me to run that now?"
            ):
                await self.capability_worker.speak("Okay, I won't run it.")
                return

            # 4) Refine transcription → call the webhook.
            prompt = self._refine_prompt(task)
            await self.capability_worker.speak(
                "Running your coding task now. This may take up to a few minutes."
            )
            result = await self._call_webhook(prompt)

            if not result or not result.get("ok"):
                await self.capability_worker.speak(
                    "I couldn't complete that coding task. "
                    "Check your webhook server logs."
                )
                return

            # 5) Speak the result.
            spoken = self._rewrite_for_voice(
                result.get("summary") or "Task finished but returned no summary."
            )
            await self.capability_worker.speak(spoken)

            if result.get("artifact_path"):
                await self.capability_worker.speak(
                    "I also saved the full output in the run artifacts."
                )

        except Exception as err:
            self.worker.editor_logging_handler.error(
                f"{TAG} unexpected error: {err}"
            )
            await self.capability_worker.speak(
                "Something went wrong while running the coding task."
            )
        finally:
            self.capability_worker.resume_normal_flow()

    async def _call_webhook(self, prompt: str) -> dict | None:
        """POST the task to the webhook; return parsed JSON or None."""
        try:
            resp = await asyncio.to_thread(
                requests.post,
                WEBHOOK_URL,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {WEBHOOK_TOKEN}",
                },
                json={"prompt": prompt},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, dict):
                raise ValueError("response is not a JSON object")
        except Exception as err:
            self.worker.editor_logging_handler.error(
                f"{TAG} webhook failed: {err}"
            )
            return None
        return payload

    def _refine_prompt(self, raw: str) -> str:
        """Use the LLM to clean up a voice transcription into a clear coding task."""
        try:
            text = self.capability_worker.text_to_text_response(
                "The following is a voice transcription of a coding task. "
                "Clean it up into a clear, actionable prompt for a coding agent. "
                "Fix transcription errors, remove filler words, and keep the intent. "
                "Return only the refined prompt, nothing else.\n\n"
                f"Transcription:\n{raw}",
                self.worker.agent_memory.full_message_history,
            )
            return (text or "").strip() or raw
        except Exception:
            return raw

    def _rewrite_for_voice(self, raw: str) -> str:
        """Use the LLM to rewrite a raw summary into spoken-friendly text."""
        try:
            text = self.capability_worker.text_to_text_response(
                "Rewrite this coding result for spoken voice. "
                "Use 1-2 short conversational sentences. "
                "No list numbers, markdown, file paths, or code snippets. "
                "Keep only the key outcome and one optional follow-up.\n\n"
                f"Result:\n{raw}",
                self.worker.agent_memory.full_message_history,
            )
            cleaned = (text or "").replace("```", "").strip()
            return cleaned or raw
        except Exception:
            return raw
