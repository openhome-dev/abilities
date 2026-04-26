import json
import random
import re
from datetime import datetime
from typing import Optional

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# DECISION JOURNAL — Interactive Skill
# Triggered by hotwords like "decision journal" or "what decisions have I made".
# Reads from decision_journal.json (written by background.py) and lets the user
# review past decisions, record outcomes, run reflective sessions, surface
# decision-making patterns, add items manually, and manage the journal.
# =============================================================================

JOURNAL_FILE = "decision_journal.json"
REFLECT_DEPTH_CAP = 2    # max reflective exchanges per session
EXPLORE_DEPTH_CAP = 3    # max recursive explores per session
PATTERN_MIN_DECISIONS = 5  # min decisions needed for pattern analysis

HOTWORDS = {
    "decision journal", "my decisions", "my decision journal",
    "what decisions have i made", "show my decisions",
    "my recent decisions", "decisions i've made",
    "how did that decision turn out", "update a decision",
    "record an outcome", "decision outcome",
    "how have i been deciding", "my decision patterns",
    "what patterns do you see in my decisions",
    "reflect on a decision", "help me reflect on a decision",
    "add a decision", "log a decision",
    "clear my decisions",
    "notify me when you capture a decision",
    "stop notifying me about decisions",
    "decision stats", "my decision stats",
}

# Whole-word exit detection — "no, reflect on the second one" must NOT exit
_EXIT_PATTERN = re.compile(
    r'\b(stop|exit|quit|done|cancel|bye|goodbye|never\s*mind|no\s*thanks|'
    r"that'?s\s*all|nothing|nah)\b",
    re.IGNORECASE,
)

ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
}

CATEGORY_ORDER = ["career", "financial", "health", "relationship", "personal", "other"]

SENTIMENT_MAP = {
    "good": "positive", "great": "positive", "right": "positive",
    "yes": "positive", "worked": "positive", "worth it": "positive",
    "positive": "positive",
    "bad": "negative", "wrong": "negative", "mistake": "negative",
    "regret": "negative", "no": "negative", "negative": "negative",
    "mixed": "mixed", "okay": "mixed", "so-so": "mixed", "alright": "mixed",
    "too soon": "too_soon", "not yet": "too_soon", "still": "too_soon",
    "early": "too_soon",
}


def _empty_journal_data() -> dict:
    """Single shared factory — used in all three _load_journal paths."""
    return {
        "decisions": [],
        "history": [],
        "settings": {
            "notify_on_capture": False,
            "last_brief_date": "",
            "last_nudge_date": "",
        },
        "stats": {"total_captured": 0, "total_with_outcomes": 0},
        "meta": {"last_processed_length": 0},
    }


def _infer_category(text: str) -> str:
    """Lightweight keyword-based category inference for manually-added decisions."""
    t = text.lower()
    if any(w in t for w in ("job", "career", "work", "promotion", "startup", "company", "hire", "fired", "quit", "resign")):
        return "career"
    if any(w in t for w in ("money", "invest", "buy", "purchase", "save", "loan", "rent", "mortgage", "financial", "salary", "budget")):
        return "financial"
    if any(w in t for w in ("health", "doctor", "surgery", "diet", "exercise", "gym", "therapy", "medication", "medical")):
        return "health"
    if any(w in t for w in ("relationship", "partner", "marry", "divorce", "friend", "family", "date", "move in", "break up")):
        return "relationship"
    if any(w in t for w in ("learn", "study", "hobby", "travel", "move", "habit", "routine", "personal")):
        return "personal"
    return "other"


class DecisionJournalCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    # ------------------------------------------------------------------
    # Hotword matching
    # ------------------------------------------------------------------

    def does_match(self, text: str) -> bool:
        t = text.lower().strip()
        return any(hw in t for hw in HOTWORDS)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_exit(self, text: str) -> bool:
        """Whole-word exit check — standalone 'no' exits, 'no, reflect on it' does not."""
        if not text or not text.strip():
            return True
        stripped = text.strip().rstrip(".,!?").strip().lower()
        if stripped == "no":
            return True
        return bool(_EXIT_PATTERN.search(text))

    def _pending_outcome(self, data: dict) -> list:
        return [d for d in data.get("decisions", []) if d.get("status") == "pending_outcome"]

    def _outcome_recorded(self, data: dict) -> list:
        return [d for d in data.get("decisions", []) if d.get("status") == "outcome_recorded"]

    def _classify_intent(self, text: str) -> str:
        t = text.lower()
        # Destructive first
        if any(kw in t for kw in ("clear", "delete", "wipe", "remove")) and "all" in t:
            return "CLEAR_ALL"
        # Toggle notifications
        if any(kw in t for kw in ("stop notif", "no notif", "disable notif")):
            return "TOGGLE_NOTIFY_OFF"
        if any(kw in t for kw in ("notify me", "let me know when", "real-time", "real time")):
            return "TOGGLE_NOTIFY_ON"
        # Pattern analysis
        if any(kw in t for kw in ("pattern", "how have i been deciding", "tendency", "tendencies", "what do you see")):
            return "PATTERN"
        # Outcome recording
        if any(kw in t for kw in ("outcome", "how did it go", "how did that", "update a decision", "turned out", "record an outcome")):
            return "OUTCOME"
        # Reflection
        if any(kw in t for kw in ("reflect", "help me think", "why did i", "dive into")):
            return "REFLECT"
        # History
        if any(kw in t for kw in ("history", "past decisions", "already resolved", "already answered")):
            return "HISTORY"
        # Add manually — catches both "add a decision" and "add to my decision journal"
        if any(kw in t for kw in ("add a decision", "log a decision", "record a decision", "save a decision")) \
                or (("add" in t or "log" in t) and "decision" in t):
            return "ADD"
        # Stats
        if any(kw in t for kw in ("stats", "how many decisions", "decision count")):
            return "STATS"
        # Default
        return "LIST"

    def _select_decision(self, decisions: list, hint: str) -> Optional[dict]:
        """
        Pick a decision from hint text.
        Priority: explicit number → ordinal word → 'random' → keyword overlap → first pending_outcome → first item.
        """
        if not decisions:
            return None
        t = hint.lower()

        # Explicit digit
        num_match = re.search(r'\b(\d+)\b', hint)
        if num_match:
            idx = int(num_match.group(1)) - 1
            if 0 <= idx < len(decisions):
                return decisions[idx]

        # Ordinal words
        for word, idx in ORDINALS.items():
            if word in t:
                real_idx = idx - 1
                if 0 <= real_idx < len(decisions):
                    return decisions[real_idx]

        # Random
        if "random" in t or "surprise" in t:
            return random.choice(decisions)

        # Keyword overlap
        hint_words = set(re.findall(r'\b[a-z]+\b', t))
        best_item, best_overlap = None, 0
        for item in decisions:
            item_words = set(re.findall(r'\b[a-z]+\b', item.get("summary", "").lower()))
            overlap = len(hint_words & item_words)
            if overlap > best_overlap:
                best_overlap = overlap
                best_item = item
        if best_item and best_overlap > 0:
            return best_item

        # Prefer pending_outcome, else first
        pending = [d for d in decisions if d.get("status") == "pending_outcome"]
        return pending[0] if pending else decisions[0]

    def _build_decision_list(self, decisions: list) -> str:
        """Flat numbered list, capped at 10 for voice readability."""
        capped = decisions[:10]
        parts = [f"{i + 1}. {item['summary']}" for i, item in enumerate(capped)]
        result = ". ".join(parts)
        if len(decisions) > 10:
            result += f". And {len(decisions) - 10} more."
        return result

    def _build_grouped_list(self, decisions: list) -> str:
        """Group by category for clarity; fall back to flat list if single category."""
        capped = decisions[:10]
        groups: dict = {}
        for item in capped:
            cat = item.get("category", "other")
            if cat not in groups:
                groups[cat] = []
            groups[cat].append(item)

        if len(groups) == 1:
            return self._build_decision_list(decisions)

        parts = []
        idx = 1
        for cat in CATEGORY_ORDER:
            if cat not in groups:
                continue
            group_items = groups[cat]
            n = len(group_items)
            heading = f"{n} {cat} {'decision' if n == 1 else 'decisions'}"
            nums = [f"{idx + j}. {item['summary']}" for j, item in enumerate(group_items)]
            parts.append(f"{heading}: {'. '.join(nums)}")
            idx += n

        result = ". ".join(parts)
        if len(decisions) > 10:
            result += f". And {len(decisions) - 10} more."
        return result

    def _infer_outcome_sentiment(self, reply: str) -> str:
        """Map user's natural language reply to a sentiment label.

        Uses whole-word matching for short keywords to avoid substring traps:
        "no" matches "know", "yes" matches "yesterday", etc.
        Multi-word phrases ("too soon", "not yet", "worth it") are checked first
        since they are unambiguous and more specific than single words.
        """
        t = reply.lower()

        # Multi-word phrases first — unambiguous, checked before single words
        MULTI_WORD = [
            ("too soon", "too_soon"),
            ("not yet", "too_soon"),
            ("worth it", "positive"),
            ("so-so", "mixed"),
        ]
        for phrase, sentiment in MULTI_WORD:
            if phrase in t:
                return sentiment

        # Single-word keywords — whole-word only via regex to prevent "know"→"no", etc.
        SINGLE_WORD = [
            (r"\bgood\b", "positive"),
            (r"\bgreat\b", "positive"),
            (r"\bright\b", "positive"),
            (r"\byes\b", "positive"),
            (r"\bworked\b", "positive"),
            (r"\bpositive\b", "positive"),
            (r"\bbad\b", "negative"),
            (r"\bwrong\b", "negative"),
            (r"\bmistake\b", "negative"),
            (r"\bregret\b", "negative"),
            (r"\bnegative\b", "negative"),
            (r"\bno\b", "negative"),
            (r"\bmixed\b", "mixed"),
            (r"\bokay\b", "mixed"),
            (r"\balright\b", "mixed"),
            (r"\bstill\b", "too_soon"),
            (r"\bearly\b", "too_soon"),
        ]
        for pattern, sentiment in SINGLE_WORD:
            if re.search(pattern, t):
                return sentiment

        # Spirit-level fallbacks
        if any(w in t for w in ("love", "happy", "glad", "thrilled", "perfect", "amazing")):
            return "positive"
        if any(w in t for w in ("hate", "awful", "terrible", "horrible")):
            return "negative"
        return "mixed"

    def _strip_json_fences(self, raw: str) -> str:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            ).strip()
        return raw

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    async def _load_journal(self) -> dict:
        try:
            exists = await self.capability_worker.check_if_file_exists(JOURNAL_FILE, False)
            if not exists:
                return _empty_journal_data()
            raw = await self.capability_worker.read_file(JOURNAL_FILE, False)
            if not raw or not raw.strip():
                return _empty_journal_data()
            return json.loads(raw)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[DecisionJournal] Load error: {e}")
            return _empty_journal_data()

    async def _save_journal(self, data: dict):
        try:
            exists = await self.capability_worker.check_if_file_exists(JOURNAL_FILE, False)
            if exists:
                await self.capability_worker.delete_file(JOURNAL_FILE, False)
            await self.capability_worker.write_file(
                JOURNAL_FILE, json.dumps(data, indent=2), False
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[DecisionJournal] Save error: {e}")

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------

    async def _handle_list(self, data: dict):
        all_decisions = data.get("decisions", [])

        if not all_decisions:
            await self.capability_worker.speak(
                "Your decision journal is empty — just talk naturally and I'll capture "
                "your decisions as you make them."
            )
            return

        pending = self._pending_outcome(data)
        count = len(all_decisions)
        pending_count = len(pending)

        grouped = self._build_grouped_list(all_decisions)
        msg = f"You have {count} {'decision' if count == 1 else 'decisions'} logged. {grouped}."
        if pending_count:
            msg += (
                f" {pending_count} {'still need' if pending_count > 1 else 'still needs'} "
                "an outcome recorded."
            )
        await self.capability_worker.speak(msg)

        await self.capability_worker.speak(
            "Want me to review one, record an outcome, or show your decision patterns? "
            "Say a number, a keyword, or stop."
        )
        reply = await self.capability_worker.user_response()
        if self._is_exit(reply):
            return

        # Route reply
        r = reply.lower()
        if any(kw in r for kw in ("outcome", "how did", "turned out", "record")):
            await self._handle_outcome(data, reply)
        elif any(kw in r for kw in ("pattern", "tendency", "how have")):
            await self._handle_pattern(data)
        elif any(kw in r for kw in ("reflect", "why did", "think through")):
            await self._handle_reflect(data, reply)
        else:
            await self._handle_explore(data, reply)

    async def _handle_explore(self, data: dict, hint: str = "", depth: int = 0):
        # Reload fresh data to catch any daemon additions
        data = await self._load_journal()

        if depth >= EXPLORE_DEPTH_CAP:
            await self.capability_worker.speak(
                "You've been on quite a decision journey! Come back anytime to keep reflecting."
            )
            return

        all_decisions = data.get("decisions", [])
        if not all_decisions:
            await self.capability_worker.speak(
                "Your decision journal is empty — nothing to review yet."
            )
            return

        selected = self._select_decision(all_decisions, hint)
        if selected is None:
            selected = all_decisions[0]

        summary = selected["summary"]
        category = selected.get("category", "other")
        alternatives = selected.get("alternatives", [])
        decision_type = selected.get("decision_type", "made")
        captured_at = selected.get("captured_at", "")
        outcome_sentiment = selected.get("outcome_sentiment")

        # Build spoken read-back
        date_str = ""
        if captured_at:
            try:
                dt = datetime.fromisoformat(captured_at)
                date_str = f" — captured {dt.strftime('%B %d')}"
            except Exception:
                pass

        alt_str = ""
        if alternatives:
            alt_str = f" You were weighing: {', '.join(alternatives)}."

        outcome_str = ""
        if outcome_sentiment and outcome_sentiment != "too_soon":
            outcome_str = f" Outcome: {outcome_sentiment}."
        elif selected.get("status") == "pending_outcome":
            outcome_str = " No outcome recorded yet."

        msg = f"{summary}{date_str}. Category: {category}.{alt_str}{outcome_str}"

        if decision_type == "deliberating":
            msg += " You were still weighing this when I captured it — has anything changed?"

        await self.capability_worker.speak(msg)

        # Offer next action
        if selected.get("status") == "pending_outcome":
            await self.capability_worker.speak(
                "Want to record an outcome, reflect on this decision, or hear another? Say a number, a keyword, or stop."
            )
        else:
            await self.capability_worker.speak(
                "Want to reflect on this, hear another decision, or stop?"
            )

        reply = await self.capability_worker.user_response()
        if self._is_exit(reply):
            return

        r = reply.lower()
        if any(kw in r for kw in ("outcome", "how did", "record", "turned out")):
            await self._handle_outcome(data, selected["summary"])
        elif any(kw in r for kw in ("reflect", "why", "think")):
            await self._handle_reflect(data, selected["summary"])
        else:
            await self._handle_explore(data, reply, depth + 1)

    async def _handle_outcome(self, data: dict, hint: str = ""):
        # Reload fresh data
        data = await self._load_journal()
        pending = self._pending_outcome(data)

        # Also include history items without outcomes if user asks about an old one
        all_resolvable = pending + [
            d for d in data.get("history", [])
            if d.get("status") == "pending_outcome"
        ]

        if not all_resolvable:
            await self.capability_worker.speak(
                "All your decisions already have outcomes recorded — your journal is up to date!"
            )
            return

        # Only auto-select when the hint has genuine keyword overlap with a decision
        # summary. Generic trigger phrases like "record an outcome" have no overlap
        # with decision summaries and must not silently pick the first item.
        selected = None
        if hint:
            hint_words = set(re.findall(r'\b[a-z]+\b', hint.lower()))
            best_overlap, best_item = 0, None
            for item in all_resolvable:
                item_words = set(re.findall(r'\b[a-z]+\b', item.get("summary", "").lower()))
                if item_words and hint_words:
                    ov = len(hint_words & item_words) / max(len(hint_words), len(item_words), 1)
                    if ov > best_overlap:
                        best_overlap, best_item = ov, item
            # Require at least one meaningful overlapping word
            if best_overlap > 0:
                selected = best_item

        # No meaningful match — ask user to pick (or auto-pick when only one option)
        if selected is None:
            if len(all_resolvable) == 1:
                selected = all_resolvable[0]
            else:
                count = min(len(all_resolvable), 5)
                top = all_resolvable[:count]
                list_str = self._build_decision_list(top)
                await self.capability_worker.speak(
                    f"Which decision? Here are the ones without outcomes: {list_str}. "
                    "Say a number or a keyword."
                )
                reply = await self.capability_worker.user_response()
                if self._is_exit(reply):
                    return
                selected = self._select_decision(top, reply) or top[0]

        summary = selected["summary"]
        await self.capability_worker.speak(
            f"How did '{summary}' turn out — good call, bad call, mixed, or still too soon to tell?"
        )

        sentiment_reply = await self.capability_worker.user_response()
        if self._is_exit(sentiment_reply):
            return

        sentiment = self._infer_outcome_sentiment(sentiment_reply)

        reflection = None
        if sentiment != "too_soon":
            reflection_reply = await self.capability_worker.run_io_loop(
                "One sentence — what did you learn from it?"
            )
            if reflection_reply and not self._is_exit(reflection_reply):
                reflection = reflection_reply.strip()

        # Update the decision in data
        now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        updated = False
        for item in data["decisions"]:
            if item["id"] == selected["id"]:
                item["outcome_sentiment"] = sentiment
                item["outcome_at"] = now_str if sentiment != "too_soon" else None
                item["reflection"] = reflection
                item["status"] = "outcome_recorded" if sentiment != "too_soon" else "pending_outcome"
                if sentiment != "too_soon":
                    data["stats"]["total_with_outcomes"] = (
                        data["stats"].get("total_with_outcomes", 0) + 1
                    )
                updated = True
                break

        # Also check history
        if not updated:
            for item in data.get("history", []):
                if item["id"] == selected["id"]:
                    item["outcome_sentiment"] = sentiment
                    item["outcome_at"] = now_str if sentiment != "too_soon" else None
                    item["reflection"] = reflection
                    item["status"] = "outcome_recorded" if sentiment != "too_soon" else "pending_outcome"
                    if sentiment != "too_soon":
                        data["stats"]["total_with_outcomes"] = (
                            data["stats"].get("total_with_outcomes", 0) + 1
                        )
                    break

        await self._save_journal(data)

        if sentiment == "too_soon":
            await self.capability_worker.speak(
                f"Got it — I'll check back on '{summary}' in a couple of weeks."
            )
        else:
            sentiment_word = {"positive": "a good call", "negative": "a tough lesson", "mixed": "a mixed one"}.get(sentiment, "noted")
            await self.capability_worker.speak(
                f"Got it — marked '{summary}' as {sentiment_word}."
                + (" Saved your reflection too." if reflection else "")
            )

    async def _handle_reflect(self, data: dict, hint: str = "", depth: int = 0):
        # Reload fresh data
        data = await self._load_journal()

        if depth >= REFLECT_DEPTH_CAP:
            await self.capability_worker.speak(
                "Great reflection session — that's a good place to pause. "
                "Say 'decision journal' anytime to continue."
            )
            return

        all_decisions = data.get("decisions", []) + data.get("history", [])
        if not all_decisions:
            await self.capability_worker.speak("Your decision journal is empty — nothing to reflect on yet.")
            return

        selected = self._select_decision(all_decisions, hint) or all_decisions[0]
        summary = selected["summary"]
        category = selected.get("category", "other")
        alternatives = selected.get("alternatives", [])
        outcome_sentiment = selected.get("outcome_sentiment", "not yet recorded")
        decision_type = selected.get("decision_type", "made")

        # Generate one thoughtful reflective question
        reflect_prompt = (
            f"User's decision: {summary}\n"
            f"Category: {category}\n"
            f"Alternatives considered: {', '.join(alternatives) if alternatives else 'none mentioned'}\n"
            f"Outcome: {outcome_sentiment}\n"
            f"Decision type: {decision_type}\n\n"
            "Ask one thoughtful, open-ended reflective question to help the user examine this decision deeper. "
            "One sentence only. Curious, not judgmental. Spoken aloud. "
            "Focus on what they learned, how they felt, or what they'd do differently."
        )

        try:
            question = self.capability_worker.text_to_text_response(reflect_prompt)
        except Exception:
            question = f"Looking back at your decision to {summary} — what stands out most to you now?"

        await self.capability_worker.speak(question)
        user_answer = await self.capability_worker.user_response()
        if self._is_exit(user_answer):
            return

        # Generate a brief insight acknowledging their answer
        insight_prompt = (
            f"The user decided: {summary}\n"
            f"When asked: {question}\n"
            f"They said: {user_answer}\n\n"
            "Respond with a 2-3 sentence empathetic insight that acknowledges their answer "
            "and adds one useful perspective. Spoken aloud. No bullet points."
        )

        try:
            insight = self.capability_worker.text_to_text_response(insight_prompt)
        except Exception:
            insight = "That's a really honest reflection — the awareness itself is valuable."

        await self.capability_worker.speak(insight)

        # Offer to go deeper (up to REFLECT_DEPTH_CAP)
        if depth + 1 < REFLECT_DEPTH_CAP:
            await self.capability_worker.speak("Want to go deeper on this, or are you good?")
            reply = await self.capability_worker.user_response()
            if not self._is_exit(reply):
                await self._handle_reflect(data, selected["summary"], depth + 1)

    async def _handle_pattern(self, data: dict):
        all_decisions = data.get("decisions", []) + data.get("history", [])

        if len(all_decisions) < PATTERN_MIN_DECISIONS:
            remaining = PATTERN_MIN_DECISIONS - len(all_decisions)
            await self.capability_worker.speak(
                f"I need a few more decisions before I can spot meaningful patterns — "
                f"just {remaining} more. Keep talking and I'll keep capturing."
            )
            return

        # Build formatted decision list for LLM
        lines = []
        for d in all_decisions[-30:]:  # Cap at 30 most recent for context length
            outcome = d.get("outcome_sentiment") or "no outcome yet"
            lines.append(
                f"- [{d.get('category', 'other')}] {d['summary']} "
                f"(type: {d.get('decision_type', 'made')}, outcome: {outcome})"
            )
        formatted = "\n".join(lines)

        pattern_prompt = (
            f"Here are decisions made by this user (most recent last):\n{formatted}\n\n"
            "Identify 2-3 genuine, specific patterns in HOW this person makes decisions. "
            "Be honest and concrete. Good examples:\n"
            "- 'You tend to act quickly on career decisions but overthink financial ones'\n"
            "- 'Most of your health decisions happen right after big life events'\n"
            "- 'You almost always land on the simpler option after deliberating too long'\n\n"
            "3-4 sentences. No bullet points. Spoken aloud. Insightful, not generic."
        )

        try:
            insight = self.capability_worker.text_to_text_response(pattern_prompt)
        except Exception:
            insight = (
                "Based on your decisions so far, you seem to act decisively when it matters most. "
                "Keep capturing and I'll give you a richer picture over time."
            )

        await self.capability_worker.speak(insight)

        # Inject into personality
        try:
            self.capability_worker.update_personality_agent_prompt(
                f"[Decision pattern insight]: {insight[:200]}"
            )
        except Exception:
            pass

    async def _handle_add(self, data: dict, trigger_text: str):
        # Try to extract decision from trigger text
        topic = ""
        t = trigger_text.lower()
        add_markers = [
            "add a decision", "log a decision", "record a decision", "save a decision",
            "add", "log", "record", "save",
        ]
        for marker in add_markers:
            if marker in t:
                idx = t.index(marker) + len(marker)
                after = trigger_text[idx:].strip().lstrip(",:- ").strip()
                if len(after.split()) >= 3:
                    topic = after[:200]
                    break

        if not topic:
            reply = await self.capability_worker.run_io_loop(
                "What decision did you make, or what are you deciding between?"
            )
            if self._is_exit(reply) or not reply:
                return
            topic = reply.strip()[:200]

        if not topic:
            await self.capability_worker.speak("I didn't catch a decision. No worries!")
            return

        # Dedup check
        topic_words = set(re.findall(r'\b[a-z]+\b', topic.lower()))
        for existing in data.get("decisions", []):
            existing_words = set(re.findall(r'\b[a-z]+\b', existing.get("summary", "").lower()))
            if existing_words:
                overlap = len(topic_words & existing_words) / max(len(topic_words), len(existing_words), 1)
                if overlap >= 0.60:
                    await self.capability_worker.speak(
                        "That decision is already in your journal! Say 'decision journal' to review it."
                    )
                    return

        # Ask for category — always start from keyword inference so even if user
        # exits the question we still get the best available category label.
        category = _infer_category(topic)
        cat_reply = await self.capability_worker.run_io_loop(
            "What category — career, financial, health, relationship, or personal?"
        )
        if cat_reply and not self._is_exit(cat_reply):
            cat_reply_lower = cat_reply.lower()
            for cat in ["career", "financial", "health", "relationship", "personal"]:
                if cat in cat_reply_lower:
                    category = cat
                    break

        # Ask for alternatives (optional)
        alt_reply = await self.capability_worker.run_io_loop(
            "Any alternatives you were weighing? Say them or say skip."
        )
        alternatives = []
        if alt_reply and not self._is_exit(alt_reply) and "skip" not in alt_reply.lower():
            # Parse comma or "or" separated alternatives
            alts = re.split(r',|\bor\b', alt_reply, flags=re.IGNORECASE)
            alternatives = [a.strip() for a in alts if len(a.strip()) > 2][:4]

        # Infer decision type
        decision_type = "deliberating" if any(
            kw in topic.lower() for kw in ["torn", "deciding", "leaning", "weighing", "between"]
        ) else "made"

        entry = {
            "id": str(int(datetime.now().timestamp() * 1000)),
            "summary": topic,
            "raw": trigger_text[:500],
            "decision_type": decision_type,
            "category": category,
            "alternatives": alternatives,
            "significance": "medium",
            "captured_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "outcome": None,
            "outcome_at": None,
            "outcome_sentiment": None,
            "reflection": None,
            "status": "pending_outcome",
        }
        data.setdefault("decisions", []).append(entry)
        data["stats"]["total_captured"] = data["stats"].get("total_captured", 0) + 1

        # Overflow
        if len(data["decisions"]) > 50:
            resolved = [d for d in data["decisions"] if d.get("status") == "outcome_recorded"]
            oldest = min(
                resolved if resolved else data["decisions"],
                key=lambda x: x.get("captured_at", "")
            )
            data["decisions"].remove(oldest)
            data.setdefault("history", []).append(oldest)

        if len(data.get("history", [])) > 100:
            data["history"] = data["history"][-100:]

        await self._save_journal(data)

        pending_count = len(self._pending_outcome(data))
        await self.capability_worker.speak(
            f"Logged! You now have {pending_count} "
            f"{'decision' if pending_count == 1 else 'decisions'} without outcomes. "
            "Say 'decision journal' anytime to reflect or record outcomes."
        )

    async def _handle_history(self, data: dict):
        resolved_queue = self._outcome_recorded(data)
        resolved_history = [d for d in data.get("history", []) if d.get("outcome_sentiment")]
        all_resolved = resolved_queue + resolved_history

        if not all_resolved:
            await self.capability_worker.speak(
                "No outcomes recorded yet — start by saying 'record an outcome' after reviewing a decision."
            )
            return

        # Sort by outcome_at descending, fallback to captured_at
        all_resolved_sorted = sorted(
            all_resolved,
            key=lambda x: x.get("outcome_at") or x.get("captured_at", ""),
            reverse=True,
        )
        recent = all_resolved_sorted[:5]

        parts = []
        for i, item in enumerate(recent):
            sentiment_label = {
                "positive": "good call",
                "negative": "tough lesson",
                "mixed": "mixed",
            }.get(item.get("outcome_sentiment", ""), "recorded")
            parts.append(f"{i + 1}. {item['summary']} — {sentiment_label}")

        await self.capability_worker.speak(
            f"Here are your {len(recent)} most recently resolved decisions. {'. '.join(parts)}."
        )

        total_captured = data["stats"].get("total_captured", 0)
        total_with_outcomes = data["stats"].get("total_with_outcomes", 0)
        if total_captured > 0:
            await self.capability_worker.speak(
                f"You've recorded outcomes for {total_with_outcomes} of {total_captured} "
                f"{'decision' if total_captured == 1 else 'decisions'} total."
            )

    async def _handle_stats(self, data: dict):
        total_captured = data["stats"].get("total_captured", 0)
        total_with_outcomes = data["stats"].get("total_with_outcomes", 0)
        pending = self._pending_outcome(data)
        pending_count = len(pending)

        if total_captured == 0:
            await self.capability_worker.speak(
                "No decisions captured yet — just talk naturally and I'll start building your journal."
            )
            return

        # Category breakdown
        all_decisions = data.get("decisions", [])
        cat_counts: dict = {}
        for d in all_decisions:
            cat = d.get("category", "other")
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

        cat_str = ", ".join(
            f"{count} {cat}" for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1])
        )

        # Oldest pending outcome
        oldest_str = ""
        if pending:
            oldest = min(pending, key=lambda x: x.get("date", ""))
            oldest_str = f" Oldest unresolved: {oldest['summary']}."

        await self.capability_worker.speak(
            f"You have {total_captured} {'decision' if total_captured == 1 else 'decisions'} total — "
            f"{cat_str}. "
            f"Outcomes recorded for {total_with_outcomes}, "
            f"{pending_count} still pending.{oldest_str}"
        )

    async def _handle_clear_all(self, data: dict):
        total = len(data.get("decisions", []))
        if total == 0:
            await self.capability_worker.speak("Your decision journal is already empty!")
            return

        confirmed = await self.capability_worker.run_confirmation_loop(
            f"Clear all {total} {'decision' if total == 1 else 'decisions'} including unresolved ones?"
        )
        if confirmed:
            data["decisions"] = []
            await self._save_journal(data)
            await self.capability_worker.speak(
                "Done — decision journal cleared. Start fresh anytime!"
            )
        else:
            await self.capability_worker.speak("No problem, keeping everything.")

    async def _handle_toggle(self, intent: str, data: dict):
        turn_on = intent == "TOGGLE_NOTIFY_ON"
        data.setdefault("settings", {})["notify_on_capture"] = turn_on
        await self._save_journal(data)
        if turn_on:
            await self.capability_worker.speak(
                "Got it — I'll let you know each time I capture a decision."
            )
        else:
            await self.capability_worker.speak(
                "Done — I'll capture decisions silently. Say 'decision journal' anytime to review them."
            )

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    async def _run(self):
        try:
            # wait_for_complete_transcription returns the full transcribed utterance —
            # this is the only reliable way to get the current message since
            # get_full_message_history() does NOT include the current turn until
            # after resume_normal_flow() is called.
            trigger_text = await self.capability_worker.wait_for_complete_transcription()
            if not trigger_text or not isinstance(trigger_text, str):
                trigger_text = ""

            intent = self._classify_intent(trigger_text)
            self.worker.editor_logging_handler.info(
                f"[DecisionJournal] Intent: {intent} | Trigger: {trigger_text[:80]}"
            )

            data = await self._load_journal()

            if intent == "LIST":
                await self._handle_list(data)
            elif intent == "OUTCOME":
                await self._handle_outcome(data, trigger_text)
            elif intent == "REFLECT":
                await self._handle_reflect(data, trigger_text)
            elif intent == "PATTERN":
                await self._handle_pattern(data)
            elif intent == "ADD":
                await self._handle_add(data, trigger_text)
            elif intent == "HISTORY":
                await self._handle_history(data)
            elif intent == "STATS":
                await self._handle_stats(data)
            elif intent == "CLEAR_ALL":
                await self._handle_clear_all(data)
            elif intent == "TOGGLE_NOTIFY_ON":
                await self._handle_toggle("TOGGLE_NOTIFY_ON", data)
            elif intent == "TOGGLE_NOTIFY_OFF":
                await self._handle_toggle("TOGGLE_NOTIFY_OFF", data)
            else:
                await self.capability_worker.speak(
                    "I can review your decisions, record outcomes, reflect on a choice, "
                    "or show your decision patterns. What would you like?"
                )

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[DecisionJournal] Skill error: {e}")
            try:
                await self.capability_worker.speak(
                    "Something went wrong. Try asking again in a moment."
                )
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self._run())
