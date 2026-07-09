from typing import Optional

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# Wake phrases treated as "trigger only, no question yet" without an LLM call.
WAKE_PHRASES = frozenset({
    "hermes",
    "hey hermes",
    "ask hermes",
    "hermes please",
    "question for hermes",
    "talk to hermes",
    "open hermes",
})

# Classifier verdict labels.
INTENT_QUESTION = "QUESTION"
INTENT_BARE = "BARE"
INTENT_EXIT = "EXIT"

# Timeout (seconds) for a single round-trip to Hermes via the local bridge.
HERMES_REQUEST_TIMEOUT = 180.0

# Spoken prompts and fallbacks.
PROMPT_ASK = "Hermes here. What would you like to ask?"
PROMPT_WORKING = "One moment."
PROMPT_SENDING = "Asking Hermes."
PROMPT_GOODBYE = "Okay, leaving Hermes. Goodbye."
PROMPT_NOT_HEARD = (
    "I didn't catch that. You can ask another question, or say stop to exit."
)
ERROR_UNREACHABLE = (
    "I couldn't reach Hermes. Make sure the bridge is running on your computer."
)
ERROR_EMPTY = "Hermes did not return anything for that."

# Prompt templates for the built-in OpenHome LLM.
TRIGGER_CLASSIFIER_PROMPT = (
    "You are an intent classifier for a voice assistant. The user just "
    "activated the 'Hermes' ability. Decide whether their utterance contains "
    "an actual question or task for Hermes, or whether it is ONLY the "
    "trigger/wake phrase with no request.\n"
    "Reply with exactly one word: QUESTION or BARE.\n\n"
    'Utterance: "{utterance}"\n'
    "Answer:"
)
EXIT_CLASSIFIER_PROMPT = (
    "You are an intent classifier for a voice assistant conversation with the "
    "'Hermes' ability. Decide if the user wants to STOP / EXIT the Hermes "
    "session (e.g. 'stop', 'exit', 'that's all', 'goodbye', 'never mind', "
    "'quit', 'I'm done', 'thanks that's it'), or whether they are asking "
    "ANOTHER question for Hermes.\n"
    "Reply with exactly one word: EXIT or CONTINUE.\n\n"
    'User said: "{utterance}"\n'
    "Answer:"
)
SPEAKABLE_REWRITE_PROMPT = (
    "Rewrite the following assistant output as a short, natural spoken response "
    "for a voice assistant. Rules:\n"
    "- Sound conversational, like speaking to a person.\n"
    "- No markdown, no bullet points, no code blocks, no file paths, no tables, "
    "no URLs, no special symbols.\n"
    "- Convert units and numbers into words a person would say aloud "
    "(e.g. '158G' -> 'about 158 gigabytes').\n"
    "- Keep it brief: 1-3 sentences. Summarize lists instead of reading every "
    "item, unless the user clearly asked for the full list.\n"
    "- Do not add information that is not in the output.\n\n"
    'The user asked: "{question}"\n\n'
    "Assistant output:\n{output}\n\n"
    "Spoken response:"
)


class HermesCapability(MatchingCapability):
    """Voice ability that relays questions to a local Hermes Agent."""

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register capability}}

    def _classify_trigger_intent(self, utterance: str) -> str:
        """Return ``INTENT_QUESTION`` if the wake utterance already contains a
        request, otherwise ``INTENT_BARE``."""
        normalized = (utterance or "").strip().lower().rstrip(".!?,")
        if normalized in WAKE_PHRASES:
            return INTENT_BARE

        prompt = TRIGGER_CLASSIFIER_PROMPT.format(utterance=utterance)
        try:
            verdict = self.capability_worker.text_to_text_response(prompt)
        except Exception:
            # Heuristic fallback: more than a few words implies a real question.
            return INTENT_QUESTION if len(normalized.split()) > 3 else INTENT_BARE
        return INTENT_QUESTION if INTENT_QUESTION in (verdict or "").upper() else INTENT_BARE

    def _is_exit_intent(self, utterance: str) -> bool:
        """Return ``True`` when the user wants to leave the Hermes session."""
        if not (utterance or "").strip():
            return False

        prompt = EXIT_CLASSIFIER_PROMPT.format(utterance=utterance)
        try:
            verdict = self.capability_worker.text_to_text_response(prompt)
        except Exception:
            return False
        return INTENT_EXIT in (verdict or "").upper()

    def _to_speakable(self, raw_output: str, question: str) -> str:
        """Rewrite raw Hermes output into a concise, TTS-friendly reply."""
        raw_output = (raw_output or "").strip()
        if not raw_output:
            return ERROR_EMPTY

        prompt = SPEAKABLE_REWRITE_PROMPT.format(question=question, output=raw_output)
        try:
            spoken = self.capability_worker.text_to_text_response(prompt)
        except Exception:
            spoken = ""
        spoken = (spoken or "").strip()
        return spoken or raw_output

    @staticmethod
    def _extract_reply(response: object) -> str:
        """Pull the reply text out of an ``exec_local_command`` response."""
        if isinstance(response, dict):
            return response.get("data") or response.get("error") or ""
        if isinstance(response, str):
            return response
        return ""

    async def _query_hermes(self, question: str) -> str:
        """Send a question to the local bridge and return a speakable reply."""
        try:
            response = await self.capability_worker.exec_local_command(
                question, timeout=HERMES_REQUEST_TIMEOUT
            )
        except Exception as error:
            self.worker.editor_logging_handler.error(f"Hermes request failed: {error}")
            return ERROR_UNREACHABLE

        self.worker.editor_logging_handler.info(response)
        return self._to_speakable(self._extract_reply(response), question)

    async def run(self) -> None:
        """Main conversation flow: classify trigger, loop, exit on intent."""
        wake_utterance = await self.capability_worker.wait_for_complete_transcription()

        if self._classify_trigger_intent(wake_utterance) == INTENT_QUESTION:
            await self.capability_worker.speak(PROMPT_SENDING)
            await self.capability_worker.speak(await self._query_hermes(wake_utterance))
        else:
            await self.capability_worker.speak(PROMPT_ASK)

        while True:
            utterance = await self.capability_worker.user_response()

            if not (utterance or "").strip():
                await self.capability_worker.speak(PROMPT_NOT_HEARD)
                continue

            if self._is_exit_intent(utterance):
                await self.capability_worker.speak(PROMPT_GOODBYE)
                break

            await self.capability_worker.speak(PROMPT_WORKING)
            await self.capability_worker.speak(await self._query_hermes(utterance))

        self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker) -> None:
        """Entry point invoked by OpenHome when the ability is triggered."""
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())