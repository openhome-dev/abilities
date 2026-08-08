import json
import shlex

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

HERMES_CHECK_COMMAND = "hermes --version"
HERMES_TIMEOUT_SECONDS = 180.0
HERMES_TARGET_ID = None

EXIT_WORDS = (
    "stop",
    "exit",
    "quit",
    "cancel",
    "never mind",
    "no thanks",
)

REJECT_PHRASES = (
    "rm -rf /",
    "format disk",
    "erase disk",
    "wipe the drive",
    "delete everything",
    "disable security",
    "steal credentials",
    "exfiltrate",
    "malware",
    "ransomware",
)

CONFIRM_PHRASES = (
    "delete",
    "remove",
    "overwrite",
    "shutdown",
    "restart",
    "reboot",
    "install",
    "uninstall",
    "update",
    "upgrade",
    "deploy",
    "commit",
    "push",
    "merge",
    "send",
    "email",
    "purchase",
    "buy",
    "payment",
    "run command",
    "execute command",
    "modify files",
    "change files",
)

VOICE_SUMMARY_SYSTEM_PROMPT = """
You rewrite local Hermes Agent output for a voice speaker.
Rules:
- Use one or two short conversational sentences.
- Say the outcome first.
- Do not use markdown, bullets, code blocks, JSON, stack traces, or long paths.
- If the task failed, say what to check next in plain language.
""".strip()

HERMES_TASK_PREFIX = """
You are Hermes Agent, running from an OpenHome voice Ability.
Complete the user's request using your normal tools and return a concise final result.
If you cannot safely complete it, explain the blocker clearly.
Keep the final answer suitable for a voice response.
""".strip()


class HermesAgentCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change the register capability tag.
    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            user_request = await self.capability_worker.wait_for_complete_transcription()
            user_request = (user_request or "").strip()

            if not user_request:
                await self.capability_worker.speak("What should I ask Hermes to do?")
                user_request = await self.capability_worker.user_response()
                user_request = (user_request or "").strip()

            if not user_request:
                await self.capability_worker.speak("I didn't catch a task for Hermes.")
                return

            if self._is_exit(user_request):
                await self.capability_worker.speak("Okay, cancelled.")
                return

            risk = self._risk_level(user_request)
            if risk == "reject":
                await self.capability_worker.speak(
                    "I can't send that request to a local agent safely."
                )
                return

            if risk == "confirm":
                confirmed = await self.capability_worker.run_confirmation_loop(
                    "That may change your local system. Should Hermes run it?"
                )
                if not confirmed:
                    await self.capability_worker.speak("Okay, I won't run it.")
                    return

            if not await self._hermes_is_available():
                await self.capability_worker.speak(
                    "Hermes is not available on the linked computer yet. Check setup."
                )
                return

            await self.capability_worker.speak(
                "Sending that to Hermes. This may take a minute."
            )
            hermes_result = await self._run_hermes(user_request)
            spoken = self._summarize_for_voice(user_request, hermes_result)
            await self.capability_worker.speak(spoken)
        except Exception as err:
            self.worker.editor_logging_handler.error(
                f"Hermes Agent ability failed: {err}"
            )
            await self.capability_worker.speak(
                "Something went wrong while talking to Hermes. Check the logs."
            )
        finally:
            self.capability_worker.resume_normal_flow()

    async def _hermes_is_available(self) -> bool:
        try:
            response = await self._exec_local(HERMES_CHECK_COMMAND, timeout=15.0)
            text = self._response_text(response).lower()
        except Exception as err:
            self.worker.editor_logging_handler.error(
                f"Hermes availability check failed: {err}"
            )
            return False

        if not text:
            return False
        failure_markers = (
            "command not found",
            "not recognized",
            "no such file",
            "hermes: not found",
        )
        return not any(marker in text for marker in failure_markers)

    async def _run_hermes(self, user_request: str) -> str:
        prompt = f"{HERMES_TASK_PREFIX}\n\nUser request:\n{user_request}"
        command = "hermes chat -q " + shlex.quote(prompt)
        response = await self._exec_local(command, timeout=HERMES_TIMEOUT_SECONDS)
        return self._response_text(response)

    async def _exec_local(self, command: str, timeout: float):
        if HERMES_TARGET_ID:
            return await self.capability_worker.exec_local_command(
                command,
                target_id=HERMES_TARGET_ID,
                timeout=timeout,
            )
        return await self.capability_worker.exec_local_command(
            command,
            timeout=timeout,
        )

    def _is_exit(self, text: str) -> bool:
        lower = text.lower()
        return any(word in lower for word in EXIT_WORDS)

    def _risk_level(self, text: str) -> str:
        lower = text.lower()
        if any(phrase in lower for phrase in REJECT_PHRASES):
            return "reject"
        if any(phrase in lower for phrase in CONFIRM_PHRASES):
            return "confirm"
        return "safe"

    def _response_text(self, response) -> str:
        if isinstance(response, dict):
            for key in ("data", "stdout", "output", "message", "error"):
                value = response.get(key)
                if value:
                    if isinstance(value, (dict, list)):
                        return json.dumps(value)
                    return str(value)
            return json.dumps(response)
        return str(response or "")

    def _summarize_for_voice(self, user_request: str, hermes_result: str) -> str:
        raw = (hermes_result or "").strip()
        if not raw:
            return "Hermes finished, but didn't return a result."

        prompt = (
            "User asked OpenHome to delegate this to Hermes:\n"
            f"{user_request}\n\n"
            "Hermes returned:\n"
            f"{raw[:3000]}\n\n"
            "Rewrite the result for spoken voice."
        )
        try:
            spoken = self.capability_worker.text_to_text_response(
                prompt,
                [],
                VOICE_SUMMARY_SYSTEM_PROMPT,
            )
        except Exception as err:
            self.worker.editor_logging_handler.error(
                f"Hermes result summarization failed: {err}"
            )
            spoken = raw

        cleaned = (spoken or raw).replace("```json", "").replace("```", "")
        cleaned = " ".join(cleaned.split())
        return cleaned[:600] or "Hermes finished."
