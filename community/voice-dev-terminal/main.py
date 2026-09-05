from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

HOTWORDS = {
    "terminal", "run command", "open terminal", "execute command",
    "dev terminal", "developer terminal", "run a command",
}

DANGER_TOKENS = {"rm", "rmdir", "sudo", "shutdown", "reboot", "dd", "mkfs", "kill", "pkill"}

EXIT_WORDS = {"done", "bye", "goodbye"}
EXIT_PHRASES = ["that's all", "close terminal", "never mind", "all done", "exit terminal"]

CMD_SYSTEM_PROMPT = """You are a macOS terminal command generator. Convert the user's spoken request into a single shell command for zsh/bash.

Rules:
- Return ONLY the shell command — no explanation, no markdown, no backticks, no quotes
- Compatible with macOS (zsh/bash)
- Do not use sudo unless explicitly requested
- Use conversation history to resolve relative references like "do it again" or "with verbose"

Examples:
"list files" -> ls -la
"git status" -> git status
"check disk space" -> df -h
"find python files" -> find . -name "*.py"
"recent commits" -> git log --oneline -10
"what's running on port 3000" -> lsof -i :3000

Return ONLY the command, nothing else."""

SUMMARY_SYSTEM_PROMPT = """You translate raw terminal output into a short spoken reply.

Rules:
- 1 to 3 sentences, natural speech only
- Extract the key facts; never paste raw output verbatim
- If output is empty or blank, say the command finished with no output
- If there is an error, say what went wrong in plain terms
- Answer what the user actually asked for"""


class VoiceDevTerminal(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    def does_match(self, text: str) -> bool:
        t = text.lower()
        return any(w in t for w in HOTWORDS)

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self._run())

    async def _run(self):
        try:
            trigger = await self.capability_worker.wait_for_complete_transcription()
            history = []

            inline = self._strip_trigger(trigger)
            if inline:
                await self._handle_command(inline, history)
            else:
                await self.capability_worker.speak("Terminal ready. What do you need?")

            while True:
                utterance = await self.capability_worker.user_response()
                if not utterance:
                    continue
                if self._is_exit(utterance):
                    await self.capability_worker.speak("Got it.")
                    break
                await self._handle_command(utterance, history)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[VoiceDevTerminal] {e}")
        finally:
            self.capability_worker.resume_normal_flow()

    async def _handle_command(self, utterance: str, history: list):
        cmd = self._generate_command(utterance, history)
        if not cmd:
            await self.capability_worker.speak("I couldn't generate a command for that.")
            return

        self.worker.editor_logging_handler.info(f"[VoiceDevTerminal] cmd: {cmd}")

        if self._is_dangerous(cmd):
            confirmed = await self.capability_worker.run_confirmation_loop(
                f"That runs: {cmd}. Confirm?"
            )
            if not confirmed:
                await self.capability_worker.speak("Cancelled.")
                return

        await self.capability_worker.speak("Running that now.")

        try:
            response = await self.capability_worker.exec_local_command(cmd, timeout=30.0)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[VoiceDevTerminal] exec error: {e}")
            await self.capability_worker.speak("That command timed out or failed.")
            return

        output = response.get("data", "") if isinstance(response, dict) else str(response)
        self.worker.editor_logging_handler.info(f"[VoiceDevTerminal] output: {output[:300]}")

        history.append({"role": "user", "content": utterance})
        history.append({"role": "assistant", "content": cmd})

        spoken = self._summarize_output(utterance, cmd, output, history)
        await self.capability_worker.speak(spoken)

    def _generate_command(self, utterance: str, history: list) -> str:
        raw = self.capability_worker.text_to_text_response(
            utterance, history, CMD_SYSTEM_PROMPT
        )
        return (raw or "").strip()

    def _summarize_output(self, utterance: str, cmd: str, output: str, history: list) -> str:
        prompt = (
            f"User asked: {utterance}\n"
            f"Command run: {cmd}\n"
            f"Output:\n{output or '(no output)'}"
        )
        raw = self.capability_worker.text_to_text_response(
            prompt, history, SUMMARY_SYSTEM_PROMPT
        )
        return (raw or "Command completed.").strip()

    def _is_dangerous(self, cmd: str) -> bool:
        return bool(set(cmd.split()) & DANGER_TOKENS)

    def _is_exit(self, text: str) -> bool:
        t = text.lower().strip()
        if any(p in t for p in EXIT_PHRASES):
            return True
        words = t.split()
        return len(words) <= 2 and bool(set(words) & EXIT_WORDS)

    def _strip_trigger(self, trigger: str) -> str:
        cleaned = trigger.lower()
        for hw in HOTWORDS:
            cleaned = cleaned.replace(hw, "")
        cleaned = cleaned.strip(" ,.-")
        return cleaned if len(cleaned) > 3 else ""
