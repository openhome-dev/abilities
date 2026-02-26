import json
import re

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# LANGUAGE PHRASE HELPER
# A voice-first travel phrase translator. Users say a phrase and a target
# language, and the LLM provides a translation with phonetic pronunciation
# and cultural tips. Supports multi-turn conversation with language memory.
# =============================================================================

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave",
}

TRANSLATE_SYSTEM_PROMPT = (
    "You are a travel phrase translator. Given a phrase and target language, "
    "provide: 1) the translation, 2) a phonetic pronunciation guide, "
    "3) a brief cultural tip if relevant. Keep responses concise for voice. "
    "Format as natural speech, not bullet points."
)

EXTRACT_LANGUAGE_PROMPT = (
    "The user wants to translate something. Extract the target language and "
    "phrase from their input. Return ONLY valid JSON with no markdown fences.\n"
    'Format: {{"language": "<target language>", "phrase": "<phrase to translate>"}}\n'
    "If no language is mentioned, set language to null.\n"
    "If no phrase is mentioned, set phrase to null.\n"
    "Examples:\n"
    '"How do you say thank you in Japanese" -> {{"language": "Japanese", "phrase": "thank you"}}\n'
    '"Translate hello to French" -> {{"language": "French", "phrase": "hello"}}\n'
    '"Say good morning in Spanish" -> {{"language": "Spanish", "phrase": "good morning"}}\n'
)


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


class LanguagePhraseHelperCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    current_language: str = None

    # Do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.current_language = None
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            self.worker.editor_logging_handler.info(
                "[LanguagePhraseHelper] Ability started"
            )

            await self.capability_worker.speak(
                "I can help you translate phrases for travel. "
                "What phrase would you like to translate, and into which language?"
            )

            idle_count = 0

            for _ in range(20):
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    idle_count += 1
                    if idle_count >= 2:
                        await self.capability_worker.speak(
                            "I'll close the translator. Come back anytime!"
                        )
                        break
                    await self.capability_worker.speak(
                        "I'm listening. What phrase would you like to translate?"
                    )
                    continue

                idle_count = 0

                if any(word in user_input.lower() for word in EXIT_WORDS):
                    await self.capability_worker.speak(
                        "Happy travels! Goodbye."
                    )
                    break

                extracted = self._extract_request(user_input)
                language = extracted.get("language") or self.current_language
                phrase = extracted.get("phrase")

                if not language:
                    lang_input = await self.capability_worker.run_io_loop(
                        "Which language would you like that translated to?"
                    )
                    if not lang_input or any(
                        w in lang_input.lower() for w in EXIT_WORDS
                    ):
                        await self.capability_worker.speak("Goodbye!")
                        break
                    language = lang_input.strip()

                if not phrase:
                    phrase_input = await self.capability_worker.run_io_loop(
                        f"What phrase would you like translated to {language}?"
                    )
                    if not phrase_input or any(
                        w in phrase_input.lower() for w in EXIT_WORDS
                    ):
                        await self.capability_worker.speak("Goodbye!")
                        break
                    phrase = phrase_input.strip()

                self.current_language = language

                prompt = (
                    f"Translate this phrase to {language}: \"{phrase}\"\n"
                    f"Provide the translation, phonetic pronunciation, "
                    f"and any relevant cultural tip."
                )

                try:
                    response = self.capability_worker.text_to_text_response(
                        prompt, system_prompt=TRANSLATE_SYSTEM_PROMPT
                    )
                    await self.capability_worker.speak(response)
                except Exception as e:
                    self.worker.editor_logging_handler.error(
                        f"[LanguagePhraseHelper] Translation error: {e}"
                    )
                    await self.capability_worker.speak(
                        "Sorry, I had trouble translating that. Try again?"
                    )

                await self.capability_worker.speak(
                    "Want to translate another phrase? "
                    "You can also switch languages anytime."
                )

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[LanguagePhraseHelper] Unexpected error: {e}"
            )
            await self.capability_worker.speak(
                "Something went wrong. Closing the translator."
            )
        finally:
            self.worker.editor_logging_handler.info(
                "[LanguagePhraseHelper] Ability ended"
            )
            self.capability_worker.resume_normal_flow()

    def _extract_request(self, user_input: str) -> dict:
        try:
            raw = self.capability_worker.text_to_text_response(
                f"User said: {user_input}",
                system_prompt=EXTRACT_LANGUAGE_PROMPT,
            )
            clean = _strip_json_fences(raw)
            return json.loads(clean)
        except (json.JSONDecodeError, Exception) as e:
            self.worker.editor_logging_handler.error(
                f"[LanguagePhraseHelper] Extraction error: {e}"
            )
            return {"language": None, "phrase": user_input}
