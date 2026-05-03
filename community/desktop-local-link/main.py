import json
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

PREFERENCES_FILE = "user_preferences.md"

SCRIPT_MAP = {
    "pause spotify": "spotify.py --pause",
    "spotify pause": "spotify.py --pause",

    "lofi": "spotify.py lofi",
    "lo-fi": "spotify.py lofi",
    "lo fi": "spotify.py lofi",
    "focus music": "spotify.py focus music",
    "deep focus": "spotify.py deep focus",
    "chill": "spotify.py chill",
    "hype": "spotify.py hype",
    "beast mode": "spotify.py beast mode",
    "energy": "spotify.py energy",
    "classical": "spotify.py classical",

    "spotify play": "spotify.py",
    "open spotify": "spotify.py",
    "spotify": "spotify.py",

    "do not disturb": "do_not_disturb_on.py",
    "focus mode": "do_not_disturb_on.py",
    "dnd": "do_not_disturb_on.py",
    "stop focus": "do_not_disturb_off.py",
    "disable do not disturb": "do_not_disturb_off.py",

    "close slack": "close_slack.py",
    "quit slack": "close_slack.py",
    "close messages": "close_messages.py",
    "quit messages": "close_messages.py",
    "open vscode": "open_vscode.py",
    "open vs code": "open_vscode.py",
    "vscode": "open_vscode.py",
    "open terminal": "open_terminal.py",
    "terminal": "open_terminal.py",

    # bonus features
    "pomodoro": "pomodoro.py",
    "start timer": "pomodoro.py",
    "start study timer": "pomodoro.py",
    "timer": "pomodoro.py",

    "clean workspace": "clean_workspace.py",
    "clean up workspace": "clean_workspace.py",

    "open calendar": "open_calendar.py",
    "calendar": "open_calendar.py",

    "lock in": "lock_in.py",
    "lock-in": "lock_in.py",
    "focus session": "lock_in.py",

    "take note": "take_note.py",
    "note": "take_note.py",
}


def bullet_to_script(bullet: str):
    lower = bullet.lower()
    for keyword, script in SCRIPT_MAP.items():
        if keyword in lower:
            return script
    return None


class DesktopCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register capability}}

    def _llm(self, prompt: str) -> str:
        return (self.capability_worker.text_to_text_response(prompt) or "").strip()

    def _classify_mode(self, frontmost_app: str, running_apps: list, safari_tabs: list) -> str:
        result = self._llm(
            "You are classifying what mode a person is currently in based on their open apps and browser tabs.\n"
            "Pick EXACTLY ONE of these five modes:\n"
            "- coding: writing or running code, using an IDE or terminal\n"
            "- studying: reading papers, watching lectures, doing homework, research\n"
            "- meeting: on a call or actively communicating via Zoom, Slack, Teams, etc.\n"
            "- creating: writing documents, designing, making content\n"
            "- browsing: general web surfing, YouTube, social media, nothing specific\n\n"
            "Reply with ONLY the single mode word, nothing else.\n\n"
            f"Frontmost app: {frontmost_app}\n"
            f"Running apps: {', '.join(running_apps)}\n"
            f"Open tabs: {', '.join(safari_tabs[:20])}\n"
        )
        mode = (result or "browsing").strip().lower()
        if mode not in {"coding", "studying", "meeting", "creating", "browsing"}:
            return "browsing"
        return mode

    def _extract_mode_from_utterance(self, utterance: str) -> str:
        result = self._llm(
            "Extract the mode being referenced in this utterance.\n"
            "Return ONLY one of these exact strings, or NONE if no mode is mentioned:\n"
            "coding, studying, meeting, creating, browsing\n\n"
            f"User said: {utterance}"
        ).strip().lower()
        return result if result != "none" and result else ""

    def _extract_action_bullets(self, utterance: str) -> list:
        raw = self._llm(
            "Extract all actions or preferences from this message as a markdown bullet list.\n"
            "Each bullet should be one short, clear action — no combining multiple actions in one bullet.\n"
            "Strip filler phrases like 'remember that', 'whenever I am in X mode', 'desktop'.\n"
            "Normalize wording into short imperative or descriptive phrases.\n"
            "No commentary, only bullets.\n\n"
            f"User said: {utterance}"
        ).strip()

        bullets = []
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("- "):
                value = line[2:].strip()
                if value:
                    bullets.append(value)
        return bullets

    def _load_preferences(self, raw: str) -> tuple:
        general_prefs = []
        mode_prefs = {}
        current_mode = None

        for line in raw.splitlines():
            stripped = line.strip()

            if stripped.startswith("## ") and stripped.lower().endswith(" mode"):
                current_mode = stripped[3:-5].strip().lower()
                mode_prefs.setdefault(current_mode, [])

            elif stripped.startswith("- "):
                value = stripped[2:].strip()
                if value:
                    if current_mode:
                        mode_prefs[current_mode].append(value)
                    else:
                        general_prefs.append(value)

        return general_prefs, mode_prefs

    def _save_preferences(self, general_prefs: list, mode_prefs: dict) -> str:
        lines = ["# User Preferences"]

        if general_prefs:
            lines.append("")
            for p in general_prefs:
                lines.append(f"- {p}")

        for mode, bullets in mode_prefs.items():
            if not bullets:
                continue

            lines.append("")
            lines.append(f"## {mode.title()} Mode")
            for b in bullets:
                lines.append(f"- {b}")

        return "\n".join(lines) + "\n"

    async def _get_desktop_state(self):
        cw = self.capability_worker
        response = await cw.exec_local_command("python3 user_detect.py")

        inner = response.get("data") or response if isinstance(response, dict) else {}
        stdout = (inner.get("stdout") or "").strip()

        try:
            detected = json.loads(stdout)
        except Exception:
            return None

        return {
            "frontmost_app": detected.get("frontmost_app") or "unknown",
            "running_apps": detected.get("running_apps") or [],
            "safari_tabs": detected.get("safari_tabs") or [],
        }

    async def _get_mode(self):
        state = await self._get_desktop_state()
        if not state:
            return None

        mode = self._classify_mode(
            state["frontmost_app"],
            state["running_apps"],
            state["safari_tabs"],
        )

        return mode

    async def _get_mode_and_state(self):
        state = await self._get_desktop_state()
        if not state:
            return None

        mode = self._classify_mode(
            state["frontmost_app"],
            state["running_apps"],
            state["safari_tabs"],
        )

        return mode, state

    async def _handle_detect(self):
        cw = self.capability_worker

        result = await self._get_mode_and_state()
        if not result:
            await cw.speak("Sorry, I couldn't read the desktop state.")
            return

        mode, state = result

        self.worker.editor_logging_handler.info(f"Detected mode: {mode}")

        explanation = self._llm(
            "You are explaining why a user's desktop was classified into a mode.\n"
            "Keep it concise, natural, and under 2 sentences.\n"
            "Say what mode they are in, mention the most relevant apps/tabs, and why.\n\n"
            f"Mode: {mode}\n"
            f"Frontmost app: {state['frontmost_app']}\n"
            f"Running apps: {', '.join(state['running_apps'])}\n"
            f"Safari tabs: {', '.join(state['safari_tabs'][:15])}\n"
        ).strip()

        if not explanation:
            apps = ", ".join(state["running_apps"][:5]) or "your open apps"
            explanation = (
                f"You are in {mode} mode because your frontmost app is "
                f"{state['frontmost_app']} and you have {apps} open."
            )

        await cw.speak(explanation)

    async def _handle_summary(self):
        cw = self.capability_worker

        result = await self._get_mode_and_state()
        if not result:
            await cw.speak("Sorry, I couldn't read the desktop state.")
            return

        mode, state = result

        summary = self._llm(
            "Briefly summarize the user's current desktop state.\n"
            "Mention the main open apps, the likely mode/category, and a short reason why.\n"
            "Keep it under 3 sentences.\n"
            "Do not mention raw JSON or internal implementation details.\n\n"
            f"Detected mode: {mode}\n"
            f"Frontmost app: {state['frontmost_app']}\n"
            f"Running apps: {', '.join(state['running_apps'])}\n"
            f"Open Safari tabs: {', '.join(state['safari_tabs'][:20])}\n"
        ).strip()

        if not summary:
            apps = ", ".join(state["running_apps"][:8]) or "no obvious apps"
            summary = (
                f"You have {apps} open. "
                f"This looks like {mode} mode because your frontmost app is {state['frontmost_app']}."
            )

        await cw.speak(summary)

    async def _handle_remember(self, utterance: str):
        cw = self.capability_worker

        mode = self._extract_mode_from_utterance(utterance)
        if not mode:
            await cw.speak("I couldn't tell which mode you meant.")
            return

        bullets = self._extract_action_bullets(utterance)
        if not bullets:
            await cw.speak("I couldn't figure out what to save.")
            return

        if await cw.check_if_file_exists(PREFERENCES_FILE, False):
            raw = await cw.read_file(PREFERENCES_FILE, False)
            general_prefs, mode_prefs = self._load_preferences(raw)
        else:
            general_prefs, mode_prefs = [], {}

        existing = mode_prefs.get(mode, [])
        existing_lower = {b.lower() for b in existing}

        added = [b for b in bullets if b.lower() not in existing_lower]
        mode_prefs[mode] = existing + added

        content = self._save_preferences(general_prefs, mode_prefs)

        if await cw.check_if_file_exists(PREFERENCES_FILE, False):
            await cw.delete_file(PREFERENCES_FILE, False)

        await cw.write_file(PREFERENCES_FILE, content, False)

        label = mode.title() + " Mode"

        if not added:
            await cw.speak("Those preferences are already saved.")
        elif len(added) == 1:
            await cw.speak(f"Got it, saved for {label}: {added[0]}.")
        else:
            await cw.speak(
                f"Got it, saved for {label}: "
                + ", ".join(added[:-1])
                + f", and {added[-1]}."
            )

    async def _handle_execute(self, utterance: str):
        cw = self.capability_worker

        explicit_mode = self._extract_mode_from_utterance(
            utterance.replace("execute", "").strip()
        )

        if explicit_mode:
            mode = explicit_mode
            self.worker.editor_logging_handler.info(f"Using explicit mode: {mode}")
        else:
            mode = await self._get_mode()
            if not mode:
                await cw.speak("Sorry, I couldn't detect your current mode.")
                return
            self.worker.editor_logging_handler.info(f"Using detected mode: {mode}")

        if not await cw.check_if_file_exists(PREFERENCES_FILE, False):
            await cw.speak(f"No preferences saved yet for {mode} mode.")
            return

        raw = await cw.read_file(PREFERENCES_FILE, False)
        _, mode_prefs = self._load_preferences(raw)

        bullets = mode_prefs.get(mode, [])

        if not bullets:
            await cw.speak(f"No preferences saved for {mode} mode.")
            return

        await cw.speak(f"Running {mode} mode setup.")

        ran = []
        skipped = []

        for bullet in bullets:
            script = bullet_to_script(bullet)

            if script:
                self.worker.editor_logging_handler.info(f"Running {script} for: {bullet}")
                await cw.exec_local_command(f"python3 {script}")
                ran.append(bullet)
            else:
                self.worker.editor_logging_handler.info(f"No script found for: {bullet}")
                skipped.append(bullet)

        if ran:
            await cw.speak(f"Done. Ran {len(ran)} action{'s' if len(ran) != 1 else ''}.")

        if skipped:
            await cw.speak(f"Couldn't find scripts for: {', '.join(skipped)}.")

    def _is_summary_question(self, utterance: str) -> bool:
        lower = utterance.lower()

        summary_phrases = [
            "what kind of apps",
            "what apps",
            "which apps",
            "what am i running",
            "what do i have open",
            "what is open",
            "summarize my desktop",
            "summarize what i'm doing",
            "what mode am i in and why",
            "why am i in",
            "what category",
        ]

        return any(phrase in lower for phrase in summary_phrases)

    async def _handle_clear_preferences(self, utterance: str):
        cw = self.capability_worker

        explicit_mode = self._extract_mode_from_utterance(utterance)

        if explicit_mode:
            mode = explicit_mode
        else:
            mode = await self._get_mode()
            if not mode:
                await cw.speak("Sorry, I couldn't detect your current mode.")
                return

        await cw.speak(
            f"You are in {mode} mode and you have told me to clear everything. "
            f"Going into {PREFERENCES_FILE} and removing tasks."
        )

        if not await cw.check_if_file_exists(PREFERENCES_FILE, False):
            await cw.speak("There is no preferences file yet.")
            return

        raw = await cw.read_file(PREFERENCES_FILE, False)
        general_prefs, mode_prefs = self._load_preferences(raw)

        if mode not in mode_prefs or not mode_prefs[mode]:
            await cw.speak(f"There are no saved tasks for {mode} mode.")
            return

        removed_count = len(mode_prefs[mode])
        mode_prefs.pop(mode, None)

        content = self._save_preferences(general_prefs, mode_prefs)

        await cw.delete_file(PREFERENCES_FILE, False)
        await cw.write_file(PREFERENCES_FILE, content, False)

        await cw.speak(
            f"Done. Removed {removed_count} saved task"
            f"{'s' if removed_count != 1 else ''} for {mode} mode."
        )


    def _is_clear_preferences_request(self, utterance: str) -> bool:
        lower = utterance.lower()
        return (
            "clear all preferences" in lower
            or "clear preferences" in lower
            or "delete preferences" in lower
            or "remove preferences" in lower
            or "clear all tasks" in lower
            or "delete all tasks" in lower
            or "remove all tasks" in lower
        )

    async def _handle_read_preferences(self, utterance: str):
        cw = self.capability_worker

        explicit_mode = self._extract_mode_from_utterance(utterance)

        if explicit_mode:
            mode = explicit_mode
        else:
            mode = await self._get_mode()
            if not mode:
                await cw.speak("Sorry, I couldn't detect your current mode.")
                return

        await cw.speak(
            f"You are in {mode} mode. "
            f"Going into {PREFERENCES_FILE} and reading your saved tasks."
        )

        if not await cw.check_if_file_exists(PREFERENCES_FILE, False):
            await cw.speak("There is no preferences file yet.")
            return

        raw = await cw.read_file(PREFERENCES_FILE, False)
        _, mode_prefs = self._load_preferences(raw)

        bullets = mode_prefs.get(mode, [])

        if not bullets:
            await cw.speak(f"You do not have any saved preferences for {mode} mode.")
            return

        if len(bullets) == 1:
            await cw.speak(
                f"For {mode} mode, you have one saved task: {bullets[0]}."
            )
        else:
            task_text = ", ".join(bullets[:-1]) + f", and {bullets[-1]}"
            await cw.speak(
                f"For {mode} mode, your saved tasks are: {task_text}."
            )

    def _is_read_preferences_request(self, utterance: str) -> bool:
        lower = utterance.lower()

        return (
            ("what are my" in lower and "preferences" in lower)
            or ("what are my" in lower and "tasks" in lower)
            or ("read back" in lower and "preferences" in lower)
            or ("read back" in lower and "tasks" in lower)
            or ("list" in lower and "preferences" in lower)
            or ("list" in lower and "tasks" in lower)
            or ("show" in lower and "preferences" in lower)
            or ("show" in lower and "tasks" in lower)
            or ("saved preferences" in lower)
            or ("saved tasks" in lower)
        )

    async def perform_action(self):
        cw = self.capability_worker

        utterance = await cw.wait_for_complete_transcription()
        self.worker.editor_logging_handler.info(f"Utterance: {utterance}")

        lower = utterance.lower()

        if self._is_clear_preferences_request(utterance):
            await self._handle_clear_preferences(utterance)
        elif "execute" in lower:
            await self._handle_execute(utterance)
        elif "remember" in lower:
            await self._handle_remember(utterance)
        else:
            await self._handle_detect()

        cw.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.perform_action())