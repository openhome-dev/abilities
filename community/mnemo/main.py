"""
Mnemo — voice-first study companion. VERSION MARKER v8
Fixes:
- "stop" during the detail/repeat follow-up now exits the whole quiz.
- Word-boundary matching so "good" no longer matches "go" (was causing
  Mnemo to replay when the user said "good" to end the session).
"""

import json
import re

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


# ═══════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════

STUDY_LOG_FILE = "mnemo_study_log.txt"
NUM_QUESTIONS = 5
NUM_PROBES = 2
MAX_HISTORY = 10
MAX_WEAK_SPOTS_CARRIED = 4
MAX_NOTES_CHARS = 1500
MIN_NOTES_WORDS = 25
DEFAULT_CLARITY = 6
MAX_FOLLOWUP_LOOPS = 5   # safety cap on detail/repeat loop

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
# Not hardcoded - fetched at runtime via get_api_keys(). Add these two keys in
# OpenHome Settings -> API Keys (names must match exactly) to enable the
# optional email recap; without them, the recap offer is skipped entirely.
SENDER_EMAIL_KEY = "mnemo_sender_email"
SENDER_PASSWORD_KEY = "mnemo_sender_password"

EXIT_WORDS = frozenset({
    "stop", "exit", "quit", "cancel", "bye", "leave", "bail", "later",
})
CONTINUE_WORDS = frozenset({
    "again", "yes", "yeah", "sure", "another", "more", "one more", "go", "yep", "yup",
})
AFFIRMATIVE = frozenset({"yes", "yeah", "sure", "please", "email", "send", "yep", "yup"})

# Follow-up loop after wrong/skipped answer
DETAIL_WORDS = frozenset({
    "more", "detail", "details", "explain", "explanation", "why", "how",
    "elaborate", "deeper", "yes", "yeah", "sure", "please",
})
REPEAT_WORDS = frozenset({
    "repeat", "again", "one more", "say again", "say that again",
    "one more time", "come again",
})
MOVE_ON_WORDS = frozenset({
    "next", "keep going", "continue", "move on", "go on", "skip",
    "no thanks", "i'm good", "im good", "no", "nope", "done",
    "next question", "go", "onward",
})

TEACH_TRIGGERS = ("teach me about", "teach me", "let me explain", "i'll explain",
                  "explain to you", "feynman")
QUIZ_WITH_TOPIC = ("quiz me on", "quiz me about", "test me on", "ask me about",
                   "quiz on", "quiz me with")
QUIZ_NO_TOPIC = ("quiz me", "study time", "test me")


# ═══════════════════════════════════════════════════════════════════════
# Prompts — using string concatenation to avoid brace-escape issues
# ═══════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = (
    "You are Mnemo — a chill senpai study buddy. "
    "Voice-friendly responses only, no markdown. "
    "When asked to return JSON, return raw JSON only, no code fences, no extra text."
)

_QUIZ_JSON_SHAPE = (
    'The JSON must have this exact shape: a top-level key "questions" '
    'whose value is a list of objects. Each object must have three string keys: '
    '"q" (the question), "answer" (correct answer in 1-2 sentences), '
    'and "concept" (a 2-4 word sub-concept label).'
)

_JUDGE_JSON_SHAPE = (
    'The JSON must have exactly two keys: "correct" (boolean true or false), '
    'and "feedback" (one chill sentence under 20 words).'
)

_FEYNMAN_JSON_SHAPE = (
    'The JSON must have four keys: "clarity_score" (int 1 to 10), '
    '"strengths" (short phrase), "gaps" (list of specific concept gaps), '
    'and "probes" (list of probing questions, each under 20 words).'
)


def build_quiz_prompt(n: int, topic: str) -> str:
    return (
        "Generate exactly " + str(n) + " quiz questions on: " + repr(topic) + ". "
        "Mix difficulty: 2 easy, 2 medium, 1 hard. "
        "Return raw JSON only. " + _QUIZ_JSON_SHAPE + " "
        "Voice-friendly, family-friendly."
    )


def build_judge_prompt(correct: str, user_answer: str) -> str:
    return (
        "The correct answer is: " + repr(correct) + ". "
        "The student said: " + repr(user_answer) + ". "
        "Judge if the student is meaningfully correct (accept near-misses, synonyms, partial credit). "
        "Return raw JSON only. " + _JUDGE_JSON_SHAPE
    )


def build_feynman_prompt(topic: str, explanation: str) -> str:
    return (
        "The student is teaching you about: " + repr(topic) + ". "
        "Their explanation was: " + repr(explanation) + ". "
        "Analyze clarity and correctness. Return raw JSON only. " + _FEYNMAN_JSON_SHAPE
    )


def build_wrap_quiz_prompt(score: int, total: int, topic: str, weak: str) -> str:
    return (
        "The student scored " + str(score) + " out of " + str(total) + " on " + topic + ". "
        "Weak spots: " + weak + ". "
        "Write 2 casual chill sentences (under 40 words) — celebrate wins, be real about misses."
    )


def build_wrap_feynman_prompt(topic: str, initial: int, final: int, weak: str) -> str:
    return (
        "The student explained " + repr(topic) + ". "
        "Initial clarity: " + str(initial) + "/10. Final: " + str(final) + "/10. "
        "Weak spots left: " + weak + ". "
        "Write 2 casual chill sentences (under 40 words) — celebrate wins, be real about gaps."
    )


def build_detail_prompt(question_text: str, correct: str) -> str:
    return (
        "A student got this quiz question wrong: " + repr(question_text) + ". "
        "The correct answer was: " + repr(correct) + ". "
        "Give a chill, casual, voice-friendly explanation in 2 to 3 sentences "
        "so the student really understands the concept. "
        "Use everyday examples if helpful. No markdown. Family-friendly."
    )


def build_more_detail_prompt(question_text: str, correct: str, previous: str) -> str:
    return (
        "A student is learning this concept: " + repr(question_text) + ". "
        "Correct answer: " + repr(correct) + ". "
        "You already explained it once like this: " + repr(previous) + ". "
        "The student wants MORE detail. Give a different, deeper 2-3 sentence explanation "
        "with a fresh angle — maybe a real-world example, a common misconception, or how it "
        "connects to other concepts. No markdown. Family-friendly."
    )


# ═══════════════════════════════════════════════════════════════════════
# Capability
# ═══════════════════════════════════════════════════════════════════════

class MnemoCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.qa_loop())

    async def qa_loop(self):
        # ↓↓↓ VERSION MARKER — if you don't see this in logs, code isn't loaded ↓↓↓
        self._log_info("=== Mnemo v8 session started ===")
        try:
            await self._run()
        except Exception as e:
            self._log_error("session_crashed", e)
            try:
                await self.capability_worker.speak("Something glitched on my side. Handing back.")
            except Exception:
                pass
        finally:
            try:
                self.capability_worker.resume_normal_flow()
            except Exception:
                pass

    async def _run(self):
        history = await self._load_history()
        prior_weak = self._collect_recent_weak_spots(history)

        initial = await self._get_initial_utterance()
        self._log_info(f"initial utterance: {initial!r}")

        intent, topic = self._parse_intent(initial)
        self._log_info(f"parsed intent={intent!r} topic={topic!r}")

        if intent == "teach" and topic:
            await self._run_feynman(topic)
        elif intent == "quiz" and topic:
            await self._run_quiz(topic, topic)
        elif intent == "teach":
            await self._collect_topic_and_teach()
        elif intent == "quiz":
            await self._collect_topic_and_quiz(prior_weak)
        else:
            await self._mode_picker(prior_weak)

        await self._offer_replay()

    # ------------------------------------------------------------------

    async def _get_initial_utterance(self) -> str:
        try:
            transcription = await self.capability_worker.wait_for_complete_transcription()
            return transcription or ""
        except Exception as e:
            self._log_info(f"initial transcription unavailable: {e}")
            return ""

    def _parse_intent(self, utterance: str) -> tuple:
        if not utterance:
            return "unknown", ""
        u = utterance.lower().strip()

        for kw in TEACH_TRIGGERS:
            if kw in u:
                return "teach", self._extract_after(u, kw)

        for kw in QUIZ_WITH_TOPIC:
            if kw in u:
                return "quiz", self._extract_after(u, kw)

        for kw in QUIZ_NO_TOPIC:
            if kw in u:
                return "quiz", ""

        return "unknown", ""

    @staticmethod
    def _extract_after(utterance: str, keyword: str) -> str:
        try:
            return utterance.split(keyword, 1)[1].strip(" ?.,!:'\"")
        except (IndexError, AttributeError):
            return ""

    # ------------------------------------------------------------------

    async def _mode_picker(self, prior_weak: list):
        if prior_weak:
            weak_list = ", ".join(prior_weak)
            await self.capability_worker.speak(
                f"welcome back. Weak spots last time: {weak_list}. "
                "I can quiz you, or you can teach me something. Which vibe?"
            )
        else:
            await self.capability_worker.speak(
                "Hey, I'm Mnemo, your voice study buddy. "
                "I've got two modes. Quiz Me: I ask you questions on any topic, score you, "
                "and reveal every answer with more detail if you want. "
                "Teach Me: you explain a concept out loud and I probe your understanding which is Feynman-style. "
                "I also remember your weak spots across sessions. So quiz me, or teach me?"
            )

        choice = await self._listen()
        if self._is_exit(choice):
            await self.capability_worker.speak("All good, catch you next time.")
            return

        if choice and self._matches_any(choice, ("teach", "explain", "feynman", "second")):
            await self._collect_topic_and_teach()
        else:
            await self._collect_topic_and_quiz(prior_weak)

    async def _collect_topic_and_quiz(self, prior_weak: list):
        await self.capability_worker.speak(
            "Cool. What topic? "
        )
        raw = await self._listen()
        if not raw or self._is_exit(raw):
            await self.capability_worker.speak("All good, catch you next time.")
            return
        topic, display = self._prepare_topic(raw, prior_weak)
        await self._run_quiz(topic, display)

    async def _collect_topic_and_teach(self):
        await self.capability_worker.speak("Nice, let's do it. What concept you wanna teach me?")
        topic = await self._listen()
        if not topic or self._is_exit(topic):
            await self.capability_worker.speak("All good, catch you next time.")
            return
        await self._run_feynman(topic)

    def _prepare_topic(self, raw: str, prior_weak: list) -> tuple:
        r = raw.strip()

        if len(r.split()) > MIN_NOTES_WORDS:
            topic = "the following study material — quiz strictly from this: " + r[:MAX_NOTES_CHARS]
            return topic, "your notes"

        low = r.lower()
        if prior_weak and self._matches_any(low, ("drill", "weak", "those", "yes", "yeah", "sure")):
            topic = r + " — focus on: " + ", ".join(prior_weak)
            return topic, "your weak spots"

        return r, r

    # ------------------------------------------------------------------

    async def _run_quiz(self, topic: str, display_topic: str):
        await self.capability_worker.speak(f"Aight, five questions on {display_topic}. Let's cook.")

        try:
            questions = self._generate_questions(topic)
        except Exception as e:
            self._log_error("generate_questions", e)
            questions = []

        if not questions:
            await self.capability_worker.speak("My brain froze on that one, try me again in a sec.")
            return

        score = 0
        weak_spots: list = []

        for i, q in enumerate(questions, start=1):
            question_text = (q.get("q") or q.get("question") or "").strip()
            correct = (q.get("answer") or q.get("a") or "").strip()
            concept = (q.get("concept") or q.get("topic") or "").strip()
            if not question_text:
                continue

            await self.capability_worker.speak(f"Question {i}. {question_text}")
            user_ans = await self._listen()

            # --- Skipped ---
            if not user_ans:
                await self.capability_worker.speak("No worries, skipping.")
                if concept:
                    weak_spots.append(concept)
                if correct:
                    await self.capability_worker.speak(f"The answer is: {correct}")
                    should_exit = await self._offer_detail_or_repeat(question_text, correct)
                    if should_exit:
                        await self.capability_worker.speak("Aight, bailing out. Later.")
                        await self._save_and_email("quiz", display_topic, f"{score}/{len(questions)}", weak_spots)
                        return
                continue

            # --- Exit mid-quiz ---
            if self._is_exit(user_ans):
                await self.capability_worker.speak("Aight, bailing out early. Later.")
                await self._save_and_email("quiz", display_topic, f"{score}/{len(questions)}", weak_spots)
                return

            # --- Judged ---
            try:
                is_correct, feedback = self._judge(correct, user_ans)
            except Exception as e:
                self._log_error("judge", e)
                is_correct, feedback = False, "Let's come back to that."

            if is_correct:
                score += 1
                await self.capability_worker.speak(feedback)
            else:
                if concept:
                    weak_spots.append(concept)
                if correct:
                    await self.capability_worker.speak(f"{feedback} The answer is: {correct}")
                    should_exit = await self._offer_detail_or_repeat(question_text, correct)
                    if should_exit:
                        await self.capability_worker.speak("Aight, bailing out. Later.")
                        await self._save_and_email("quiz", display_topic, f"{score}/{len(questions)}", weak_spots)
                        return
                else:
                    await self.capability_worker.speak(feedback)

        weak_spots = self._dedupe(weak_spots)
        wrap = self._call_llm(
            build_wrap_quiz_prompt(score, len(questions), display_topic,
                                   ", ".join(weak_spots) if weak_spots else "nothing — you were locked in"),
            fallback="Nice work overall — catch the weak spots next round.",
        )
        await self.capability_worker.speak(
            f"Alright, results. {score} out of {len(questions)}. {wrap}"
        )
        await self._save_and_email("quiz", display_topic, f"{score}/{len(questions)}", weak_spots)

    async def _offer_detail_or_repeat(self, question_text: str, correct: str) -> bool:
        """
        Loop offering detail/repeat until user says move on (or hits safety cap).
        Tracks the last-spoken utterance so 'repeat' says the same thing back.
        Returns True if the user asked to exit the whole quiz (not just move on).
        """
        if not correct:
            return False

        last_spoken = f"The answer is: {correct}"
        previous_detail = ""

        for iteration in range(MAX_FOLLOWUP_LOOPS):
            await self.capability_worker.speak(
                "Want more detail, want me to repeat, or should we keep going?"
            )
            response = await self._listen()

            if not response:
                return False  # silence → move on to next question

            r = response.lower()
            self._log_info(f"followup iteration {iteration} response: {r!r}")

            # 0. EXIT check has HIGHEST priority — bail out of the whole quiz
            if self._is_exit(r):
                return True

            # 1. Move on to next question
            if self._matches_any(r, MOVE_ON_WORDS):
                return False

            # 2. Repeat: say the last thing again
            if self._matches_any(r, REPEAT_WORDS):
                await self.capability_worker.speak(last_spoken)
                continue

            # 3. More detail: generate a fresh angle each iteration
            if self._matches_any(r, DETAIL_WORDS):
                if previous_detail:
                    detailed = self._call_llm(
                        build_more_detail_prompt(question_text, correct, previous_detail),
                        fallback="Same core idea , think of a real-world example you know.",
                    )
                else:
                    detailed = self._call_llm(
                        build_detail_prompt(question_text, correct),
                        fallback="Basically, that's the core of it.",
                    )
                await self.capability_worker.speak(detailed)
                previous_detail = detailed
                last_spoken = detailed
                continue

            # 4. Unrecognized: assume user wants to move on
            return False

        return False

    def _generate_questions(self, topic: str) -> list:
        prompt = build_quiz_prompt(NUM_QUESTIONS, topic)
        raw = self._call_llm(prompt)
        self._log_info(f"quiz raw (first 400): {raw[:400]!r}")

        data = self._parse_json(raw)
        self._log_info(f"quiz parsed type: {type(data).__name__}")

        if isinstance(data, dict):
            self._log_info(f"quiz keys: {list(data.keys())[:10]}")

        questions = None
        if isinstance(data, dict):
            for key in ("questions", '"questions"', "Questions", "quiz", "items", "results", "data"):
                if key in data:
                    questions = data[key]
                    break

        if questions is None and isinstance(data, list):
            questions = data

        if isinstance(questions, str):
            try:
                questions = json.loads(questions)
            except (json.JSONDecodeError, ValueError):
                questions = []

        if not isinstance(questions, list):
            self._log_info(f"questions not a list, got: {type(questions).__name__}")
            return []

        questions = [q for q in questions if isinstance(q, dict)]
        return questions[:NUM_QUESTIONS]

    def _judge(self, correct: str, user_answer: str) -> tuple:
        raw = self._call_llm(build_judge_prompt(correct, user_answer))
        data = self._parse_json(raw)

        if not isinstance(data, dict):
            tokens = [t for t in correct.lower().split() if len(t) > 3]
            is_correct = bool(tokens) and any(t in user_answer.lower() for t in tokens)
            return is_correct, "Yeah, nailed it." if is_correct else "Not quite, no worries."

        is_correct = bool(data.get("correct", False))
        feedback = (data.get("feedback") or "").strip() or (
            "Yeah, nailed it." if is_correct else "Not quite, no worries."
        )
        return is_correct, feedback

    # ------------------------------------------------------------------

    async def _run_feynman(self, topic: str):
        await self.capability_worker.speak(
            f"Aight, teach me {topic}. Take your time and go for it."
        )

        explanation = await self._listen()
        if not explanation:
            await self.capability_worker.speak("Nothing came through, try again another time.")
            return
        if self._is_exit(explanation):
            await self.capability_worker.speak("All good, catch you next time.")
            return

        try:
            analysis = self._analyze_explanation(topic, explanation)
        except Exception as e:
            self._log_error("analyze_explanation", e)
            analysis = {}

        initial = self._safe_int(analysis.get("clarity_score"), DEFAULT_CLARITY)
        strengths = analysis.get("strengths") or "the core idea"
        gaps = list(analysis.get("gaps") or [])
        probes = list(analysis.get("probes") or [])
        if not probes:
            probes = [
                f"How would you explain {topic} to someone who's never heard of it?",
                f"What's the one part of {topic} you're least sure of?",
            ]
        probes = probes[:NUM_PROBES]

        await self.capability_worker.speak(
            f"Nice. Tracking at {initial} out of 10. You had {strengths} down. "
            f"Got {len(probes)} things to sharpen up."
        )

        answered_well = 0
        for i, probe in enumerate(probes, start=1):
            await self.capability_worker.speak(f"Question {i}. {probe}")
            ans = await self._listen()
            if not ans:
                await self.capability_worker.speak("Skipping.")
                continue
            if self._is_exit(ans):
                await self.capability_worker.speak("Later.")
                await self._save_and_email("teach", topic, f"{initial}/10", gaps)
                return

            try:
                is_correct, feedback = self._judge(f"a clear explanation of {topic}", ans)
            except Exception as e:
                self._log_error("judge_feynman", e)
                is_correct, feedback = False, "Let's come back to that."

            if is_correct:
                answered_well += 1
            await self.capability_worker.speak(feedback)

        bonus = round((answered_well / max(1, len(probes))) * 2)
        final = min(10, initial + int(bonus))
        remaining_weak = gaps if answered_well < len(probes) else []

        wrap = self._call_llm(
            build_wrap_feynman_prompt(
                topic, initial, final,
                ", ".join(remaining_weak) if remaining_weak else "nothing — clean explanation"
            ),
            fallback="Nice work — few gaps to sharpen next round.",
        )
        await self.capability_worker.speak(f"Final clarity: {final} out of 10. {wrap}")
        await self._save_and_email("teach", topic, f"{final}/10", remaining_weak)

    def _analyze_explanation(self, topic: str, explanation: str) -> dict:
        raw = self._call_llm(build_feynman_prompt(topic, explanation))
        self._log_info(f"feynman raw (first 400): {raw[:400]!r}")
        data = self._parse_json(raw)
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------

    async def _offer_replay(self):
        await self.capability_worker.speak("Wanna go again or you good?")
        response = await self._listen()
        if response and self._matches_any(response, CONTINUE_WORDS):
            await self._run()
            return
        await self.capability_worker.speak("Cool, catch you next session.")

    # ------------------------------------------------------------------

    async def _save_and_email(self, mode: str, topic: str, score: str, weak: list):
        await self._save_session(mode, topic, score, weak)
        await self._offer_email(mode, topic, score, weak)

    async def _offer_email(self, mode: str, topic: str, score: str, weak: list):
        sender_email = self.capability_worker.get_api_keys(SENDER_EMAIL_KEY)
        sender_password = self.capability_worker.get_api_keys(SENDER_PASSWORD_KEY)
        if not sender_email or not sender_password:
            return

        await self.capability_worker.speak(
            "Want me to email you the recap so you can review later?"
        )
        response = await self._listen()
        if not response or not self._matches_any(response, AFFIRMATIVE):
            return

        await self.capability_worker.speak("Cool. What's your email?")
        raw_email = await self._listen()
        if not raw_email:
            await self.capability_worker.speak("Didn't catch it, skipping.")
            return

        recipient = self._normalize_email(raw_email)
        if not self._looks_like_email(recipient):
            await self.capability_worker.speak("Hmm, that didn't sound like a valid email, skipping.")
            return

        subject = f"Your Mnemo session on {topic}"
        body = self._compose_email(mode, topic, score, weak)
        sent = self._try_send(sender_email, sender_password, recipient, subject, body)
        if sent:
            await self.capability_worker.speak(f"Sent to {recipient}. Check your inbox.")
        else:
            await self.capability_worker.speak("Email had a hiccup, but I've saved the recap here.")

    @staticmethod
    def _normalize_email(raw: str) -> str:
        cleaned = raw.lower().strip()
        cleaned = re.sub(r"\s+at\s+", "@", cleaned)
        cleaned = re.sub(r"\s+dot\s+", ".", cleaned)
        cleaned = re.sub(r"\s+", "", cleaned)
        return cleaned

    @staticmethod
    def _looks_like_email(candidate: str) -> bool:
        return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", candidate or ""))

    @staticmethod
    def _compose_email(mode: str, topic: str, score: str, weak: list) -> str:
        weak_str = ", ".join(weak) if weak else "nothing — you were locked in."
        return (
            "Hey — here's your Mnemo recap.\n\n"
            "Mode: " + mode.title() + "\n"
            "Topic: " + topic + "\n"
            "Score: " + score + "\n"
            "Weak spots to review: " + weak_str + "\n\n"
            "Come back and drill these next time. Triggers: 'mnemo', 'quiz me', 'teach me'.\n\n"
            "— Mnemo, your chill study buddy"
        )

    def _try_send(self, sender_email: str, sender_password: str, recipient: str, subject: str, body: str) -> bool:
        try:
            return bool(self.capability_worker.send_email(
                host=SMTP_HOST,
                port=SMTP_PORT,
                sender_email=sender_email,
                sender_password=sender_password,
                receiver_email=recipient,
                cc_emails=[],
                subject=subject,
                body=body,
                attachment_paths=[],
            ))
        except Exception as e:
            self._log_error("email_send", e)
            return False

    # ------------------------------------------------------------------

    async def _load_history(self) -> list:
        try:
            exists = await self.capability_worker.check_if_file_exists(STUDY_LOG_FILE, False)
            if not exists:
                return []
            raw = await self.capability_worker.read_file(STUDY_LOG_FILE, False)
            return self._parse_history_lines(raw or "")
        except Exception as e:
            self._log_info(f"history load failed: {e}")
            return []

    @staticmethod
    def _parse_history_lines(raw: str) -> list:
        out = []
        for line in raw.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    async def _save_session(self, mode: str, topic: str, score: str, weak: list):
        try:
            entry = json.dumps({"mode": mode, "topic": topic, "score": score, "weak_spots": weak})
            existing = ""
            file_exists = await self.capability_worker.check_if_file_exists(STUDY_LOG_FILE, False)
            if file_exists:
                existing = await self.capability_worker.read_file(STUDY_LOG_FILE, False) or ""
            lines = [ln for ln in existing.strip().split("\n") if ln.strip()]
            lines.append(entry)
            lines = lines[-MAX_HISTORY:]

            # write_file APPENDS - since we already read the existing content above
            # and are about to write it back out in full, the file must be deleted
            # first or every session would duplicate all prior history on top of
            # itself (rather than replace it).
            if file_exists:
                await self.capability_worker.delete_file(STUDY_LOG_FILE, False)
            await self.capability_worker.write_file(
                STUDY_LOG_FILE, "\n".join(lines) + "\n", False
            )
        except Exception as e:
            self._log_error("save_session", e)

    @staticmethod
    def _collect_recent_weak_spots(history: list) -> list:
        collected: list = []
        for session in history[-3:]:
            for w in session.get("weak_spots") or []:
                if w and w not in collected:
                    collected.append(w)
        return collected[:MAX_WEAK_SPOTS_CARRIED]

    # ------------------------------------------------------------------

    def _call_llm(self, user_prompt: str, fallback: str = "") -> str:
        try:
            # text_to_text_response() rejects a "system"/"system_prompt" kwarg on
            # this host build, so the system prompt is folded into the prompt text
            # itself instead of passed as a separate argument.
            full_prompt = SYSTEM_PROMPT + "\n\n" + user_prompt
            response = self.capability_worker.text_to_text_response(full_prompt)
            return (response or "").strip()
        except Exception as e:
            self._log_error("llm_call", e)
            return fallback

    @staticmethod
    def _parse_json(raw: str):
        if not raw:
            return None
        cleaned = raw.strip()

        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```\s*$", "", cleaned)
            cleaned = cleaned.strip()

        try:
            result = json.loads(cleaned)
            if isinstance(result, dict):
                return result
            if isinstance(result, list):
                return {"questions": result}
        except (json.JSONDecodeError, ValueError):
            pass

        try:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end > start:
                candidate = cleaned[start: end + 1]
                result = json.loads(candidate)
                if isinstance(result, dict):
                    return result
        except (json.JSONDecodeError, ValueError):
            pass

        try:
            start = cleaned.find("[")
            end = cleaned.rfind("]")
            if start != -1 and end > start:
                candidate = cleaned[start: end + 1]
                result = json.loads(candidate)
                if isinstance(result, list):
                    return {"questions": result}
        except (json.JSONDecodeError, ValueError):
            pass

        return None

    async def _listen(self) -> str:
        try:
            response = await self.capability_worker.user_response()
            return (response or "").strip()
        except Exception as e:
            self._log_error("user_response", e)
            return ""

    @staticmethod
    def _matches_any(text: str, keywords) -> bool:
        """
        Whole-word / whole-phrase match. 'go' matches 'go' but NOT 'good' or 'gone'.
        Multi-word phrases like 'i'm good' also work.
        """
        if not text:
            return False
        normalized = text.lower().strip()
        for kw in keywords:
            pattern = r'(?<!\w)' + re.escape(kw) + r'(?!\w)'
            if re.search(pattern, normalized):
                return True
        return False

    @classmethod
    def _is_exit(cls, text: str) -> bool:
        return cls._matches_any(text, EXIT_WORDS)

    @staticmethod
    def _safe_int(value, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _dedupe(items: list) -> list:
        return list(dict.fromkeys(items))

    def _log_info(self, message: str):
        try:
            self.worker.editor_logging_handler.info(f"[Mnemo] {message}")
        except Exception:
            pass

    def _log_error(self, context: str, exc: Exception):
        try:
            self.worker.editor_logging_handler.info(
                f"[Mnemo] {context} failed: {type(exc).__name__}: {exc}"
            )
        except Exception:
            pass
