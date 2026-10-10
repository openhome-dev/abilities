import requests
from datetime import datetime
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

VENICE_BASE = "https://api.venice.ai/api/v1"
VENICE_MODEL = "abliteration-abliterated-model-large-v2"
STORAGE_KEY = "voice_shadow_sessions"
MAX_SESSIONS = 10

HOTWORDS = {
    "shadow my idea", "shadow this idea", "voice shadow",
    "brutal feedback", "be brutally honest", "tear this apart",
    "tear apart my", "honest critique", "find the flaws",
    "stress test my", "reality check my", "poke holes in",
    "what's wrong with my", "whats wrong with my",
    "sanity check my", "honest feedback on",
}

EXIT_WORDS = {"stop", "exit", "bye", "goodbye"}
EXIT_PHRASES = {
    "that's all", "all done", "never mind", "i'm done", "no thanks",
    "no more", "i quit", "let's stop", "i'm done here",
}

CRITIQUE_PROMPT = (
    "You are a candid advisor reviewing someone's idea before the world tears it apart. "
    "Respond in exactly 4 spoken sentences — no bullet points, no headers, pure prose: "
    "1. The single biggest flaw in the core logic. "
    "2. The first objection anyone who hears this will immediately raise. "
    "3. The key assumption being made that could be completely wrong. "
    "4. The one element that actually has real potential. "
    "Rules: no hedging words, no 'however' or 'that said' or 'with some refinement'. "
    "Be specific. Keep it under 100 words — it will be read aloud."
)

DRILLDOWN_PROMPT = (
    "You gave honest feedback on an idea. The person wants to go deeper on one specific point. "
    "Be equally direct and specific — no softening. Under 60 words — it will be spoken aloud."
)


class VoiceShadow(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    def does_match(self, text: str) -> bool:
        t = text.lower()
        return any(hw in t for hw in HOTWORDS)

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self._run())

    async def _run(self):
        try:
            self._venice_key = self.capability_worker.get_api_keys("venice_api_key") or ""
            await self.capability_worker.wait_for_complete_transcription()

            await self.capability_worker.speak(
                "Ready. Pitch me the idea — startup, plan, decision, anything."
            )

            outer_running = True
            while outer_running:
                idea = await self.capability_worker.user_response()
                if not idea or self._is_exit(idea):
                    break

                if len(idea.split()) < 8:
                    await self.capability_worker.speak(
                        "Give me a bit more — what exactly are you proposing?"
                    )
                    idea = await self.capability_worker.user_response()
                    if not idea or self._is_exit(idea):
                        break

                await self.capability_worker.speak("Give me a second.")

                critique = self._call_venice(CRITIQUE_PROMPT, f"Idea: {idea}")
                if not critique:
                    await self.capability_worker.speak(
                        "I couldn't reach my analysis engine — try again in a moment."
                    )
                    break

                await self.capability_worker.speak(critique)
                self._save_session(idea, critique)

                while True:
                    await self.capability_worker.speak(
                        "Want me to dig into any of that? Or bring me another idea."
                    )
                    followup = await self.capability_worker.user_response()
                    if not followup or self._is_exit(followup):
                        outer_running = False
                        break

                    intent = self._classify_intent(followup)
                    if intent == "EXIT":
                        outer_running = False
                        break
                    elif intent == "NEW_IDEA":
                        idea = followup
                        if len(idea.split()) < 8:
                            await self.capability_worker.speak(
                                "Give me a bit more — what exactly are you proposing?"
                            )
                            idea = await self.capability_worker.user_response()
                            if not idea or self._is_exit(idea):
                                outer_running = False
                                break
                        await self.capability_worker.speak("Give me a second.")
                        critique = self._call_venice(CRITIQUE_PROMPT, f"Idea: {idea}")
                        if not critique:
                            await self.capability_worker.speak(
                                "I couldn't reach my analysis engine — try again in a moment."
                            )
                            outer_running = False
                            break
                        await self.capability_worker.speak(critique)
                        self._save_session(idea, critique)
                    else:
                        answer = self._call_venice(
                            DRILLDOWN_PROMPT,
                            f"Original idea: {idea}\nFeedback given: {critique}\nQuestion: {followup}",
                        )
                        await self.capability_worker.speak(
                            answer or "I don't have more to add on that point."
                        )

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[VoiceShadow] Error: {e}")
        finally:
            self.capability_worker.resume_normal_flow()

    def _call_venice(self, system_prompt: str, user_content: str) -> str:
        headers = {
            "Authorization": f"Bearer {self._venice_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": VENICE_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "venice_parameters": {
                "include_venice_system_prompt": False,
                "enable_web_search": "off",
            },
        }
        try:
            resp = requests.post(
                f"{VENICE_BASE}/chat/completions", headers=headers, json=payload, timeout=30
            )
            if resp.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"[VoiceShadow] Venice error: {resp.status_code}"
                )
                return ""
            return (
                (resp.json().get("choices") or [{}])[0]
                .get("message", {})
                .get("content") or ""
            ).strip()
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[VoiceShadow] Venice call failed: {e!r}")
            return ""

    def _classify_intent(self, text: str) -> str:
        raw = (
            self.capability_worker.text_to_text_response(
                "Classify this response as exactly one of: DRILL, NEW_IDEA, EXIT.\n"
                "DRILL = asking about a specific point in the feedback just given.\n"
                "NEW_IDEA = presenting an entirely new idea to evaluate.\n"
                "EXIT = done, wants to stop.\n"
                "Reply with ONLY the label, nothing else.\n"
                f"Input: {text}"
            )
            or "DRILL"
        ).strip().upper().split()[0]
        return raw if raw in {"DRILL", "NEW_IDEA", "EXIT"} else "DRILL"

    def _save_session(self, idea: str, critique: str):
        raw = self.capability_worker.get_single_key(STORAGE_KEY)
        stored = (raw.get("value", raw) if raw else {}) or {}
        sessions = stored.get("sessions", [])
        sessions.append({
            "idea": idea,
            "critique": critique,
            "timestamp": datetime.utcnow().isoformat(),
        })
        if len(sessions) > MAX_SESSIONS:
            sessions = sessions[-MAX_SESSIONS:]
        data = {"sessions": sessions}
        try:
            result = self.capability_worker.create_key(STORAGE_KEY, data)
            if not (result or {}).get("success"):
                self.capability_worker.update_key(STORAGE_KEY, data)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[VoiceShadow] Save error: {e!r}")

    def _is_exit(self, text: str) -> bool:
        if not text:
            return True
        t = text.lower().strip()
        if any(p in t for p in EXIT_PHRASES):
            return True
        tokens = set(t.split())
        return bool(tokens & EXIT_WORDS)
