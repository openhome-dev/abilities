import re

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# MEDITATION & BREATHING GUIDE
# A voice-guided breathing exercise and meditation ability. Supports box
# breathing, 4-7-8 breathing, and LLM-generated guided meditations with
# timed pauses using session_tasks.sleep().
# =============================================================================

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave",
}

TECHNIQUE_PROMPT = (
    "The user wants a breathing or meditation exercise. Classify their request.\n"
    "Return ONLY one of: box, fourseventeight, meditation, unknown\n"
    "Rules:\n"
    "- 'box breathing', 'square breathing', '4 4 4 4' -> box\n"
    "- '4 7 8', 'four seven eight', 'relaxing breath' -> fourseventeight\n"
    "- 'meditation', 'guided', 'mindfulness', 'body scan', 'relax' -> meditation\n"
    "- If unclear -> unknown\n"
    "Input: {text}"
)

DURATION_PROMPT = (
    "The user specified how long they want to meditate. "
    "Extract the number of minutes as a single integer. "
    "If they say '2 minutes' return 2. If '5' return 5. If '10 minutes' return 10. "
    "If unclear, return 5. Return ONLY the number.\n"
    "Input: {text}"
)

MEDITATION_PROMPT = (
    "Generate a short, calming guided meditation segment for voice. "
    "This is segment {segment} of {total}. Keep it to 2-3 sentences. "
    "Use a gentle, soothing tone. Focus on relaxation, body awareness, "
    "and present-moment awareness. Do not use bullet points or formatting."
)


class MeditationBreathingGuideCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            self.worker.editor_logging_handler.info(
                "[MeditationGuide] Ability started"
            )

            await self.capability_worker.speak(
                "Welcome to your breathing and meditation guide. "
                "I can lead you through box breathing, 4-7-8 breathing, "
                "or a guided meditation. Which would you like?"
            )

            user_input = await self.capability_worker.user_response()

            if not user_input or any(
                w in (user_input or "").lower() for w in EXIT_WORDS
            ):
                await self.capability_worker.speak(
                    "No worries. Come back when you're ready to relax."
                )
                return

            technique = self._classify_technique(user_input)

            if technique == "unknown":
                await self.capability_worker.speak(
                    "I'll start with box breathing, a great all-purpose technique."
                )
                technique = "box"

            await self.capability_worker.speak(
                "How many minutes would you like? 2, 5, or 10?"
            )
            duration_input = await self.capability_worker.user_response()
            minutes = self._parse_duration(duration_input)

            self.worker.editor_logging_handler.info(
                f"[MeditationGuide] Technique: {technique}, Duration: {minutes}min"
            )

            if technique == "box":
                await self._run_box_breathing(minutes)
            elif technique == "fourseventeight":
                await self._run_478_breathing(minutes)
            else:
                await self._run_guided_meditation(minutes)

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[MeditationGuide] Unexpected error: {e}"
            )
            await self.capability_worker.speak(
                "Something went wrong. Let's try again next time."
            )
        finally:
            self.worker.editor_logging_handler.info(
                "[MeditationGuide] Ability ended"
            )
            self.capability_worker.resume_normal_flow()

    async def _run_box_breathing(self, minutes: int):
        cycle_seconds = 16  # 4+4+4+4
        total_cycles = max(1, (minutes * 60) // cycle_seconds)

        await self.capability_worker.speak(
            f"Starting box breathing for about {minutes} minutes. "
            "Each cycle has four equal phases: breathe in, hold, breathe out, hold. "
            "Let's begin."
        )

        await self.worker.session_tasks.sleep(2)

        for cycle in range(1, total_cycles + 1):
            await self.capability_worker.speak("Breathe in.")
            await self.worker.session_tasks.sleep(4)

            await self.capability_worker.speak("Hold.")
            await self.worker.session_tasks.sleep(4)

            await self.capability_worker.speak("Breathe out.")
            await self.worker.session_tasks.sleep(4)

            await self.capability_worker.speak("Hold.")
            await self.worker.session_tasks.sleep(4)

        await self.capability_worker.speak(
            f"Session complete. You did {total_cycles} cycles of box breathing. "
            "Great job. Take a moment to notice how you feel."
        )

    async def _run_478_breathing(self, minutes: int):
        cycle_seconds = 19  # 4+7+8
        total_cycles = max(1, (minutes * 60) // cycle_seconds)

        await self.capability_worker.speak(
            f"Starting 4-7-8 breathing for about {minutes} minutes. "
            "Breathe in for 4, hold for 7, and breathe out slowly for 8. "
            "Let's begin."
        )

        await self.worker.session_tasks.sleep(2)

        for cycle in range(1, total_cycles + 1):
            await self.capability_worker.speak("Breathe in.")
            await self.worker.session_tasks.sleep(4)

            await self.capability_worker.speak("Hold.")
            await self.worker.session_tasks.sleep(7)

            await self.capability_worker.speak("Breathe out slowly.")
            await self.worker.session_tasks.sleep(8)

        await self.capability_worker.speak(
            f"Session complete. You did {total_cycles} cycles of 4-7-8 breathing. "
            "This technique is great for calming your nervous system. Well done."
        )

    async def _run_guided_meditation(self, minutes: int):
        segments = max(2, minutes)

        await self.capability_worker.speak(
            f"Starting a {minutes}-minute guided meditation. "
            "Find a comfortable position and close your eyes."
        )

        await self.worker.session_tasks.sleep(3)

        for i in range(1, segments + 1):
            try:
                prompt = (
                    f"This is segment {i} of {segments} in a guided meditation."
                )
                guidance = self.capability_worker.text_to_text_response(
                    prompt,
                    system_prompt=MEDITATION_PROMPT.format(
                        segment=i, total=segments
                    ),
                )
                await self.capability_worker.speak(guidance)
            except Exception as e:
                self.worker.editor_logging_handler.error(
                    f"[MeditationGuide] Segment error: {e}"
                )
                await self.capability_worker.speak(
                    "Continue to breathe deeply and relax."
                )

            pause = max(10, (minutes * 60) // segments - 10)
            await self.worker.session_tasks.sleep(pause)

        await self.capability_worker.speak(
            "Your meditation is complete. Slowly bring your awareness back. "
            "Wiggle your fingers and toes. When you're ready, gently open your eyes. "
            "Well done."
        )

    def _classify_technique(self, text: str) -> str:
        if not text:
            return "unknown"
        lower = text.lower()

        if "box" in lower or "square" in lower:
            return "box"
        if "4-7-8" in lower or "478" in lower or "four seven eight" in lower:
            return "fourseventeight"
        if any(w in lower for w in ("meditation", "guided", "mindful", "body scan")):
            return "meditation"

        try:
            result = self.capability_worker.text_to_text_response(
                TECHNIQUE_PROMPT.format(text=text)
            )
            cleaned = result.strip().lower().rstrip(".")
            if cleaned in ("box", "fourseventeight", "meditation"):
                return cleaned
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[MeditationGuide] Technique classification error: {e}"
            )

        return "unknown"

    def _parse_duration(self, text: str) -> int:
        if not text:
            return 5

        match = re.search(r"(\d+)", text)
        if match:
            val = int(match.group(1))
            if 1 <= val <= 30:
                return val
            return 5

        try:
            result = self.capability_worker.text_to_text_response(
                DURATION_PROMPT.format(text=text)
            )
            val = int(result.strip())
            if 1 <= val <= 30:
                return val
        except (ValueError, Exception):
            pass

        return 5
