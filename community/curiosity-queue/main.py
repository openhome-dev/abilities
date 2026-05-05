import json
import random
import re
from datetime import datetime
from typing import Optional

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# CURIOSITY QUEUE — Interactive Skill
# Triggered by hotwords like "what am I curious about?" or "curiosity queue".
# Reads from curiosity_queue.json (written by background.py) and lets the user
# list pending curiosities, get spoken LLM-generated answers, add items
# manually, clear answered items, and toggle real-time notifications.
# =============================================================================

QUEUE_FILE = "curiosity_queue.json"
EXPLORE_ALL_CAP = 5  # BUG-10: max items per explore-all batch

HOTWORDS = {
    "what am i curious about",
    "my curiosity queue",
    "curiosity queue",
    "what have i been wondering",
    "what am i wondering about",
    "show my curiosities",
    "my curiosity list",
    "curiosity list",
    "explain one of my curiosities",
    "answer my curiosities",
    "explore my curiosities",
    "add to my curiosity queue",
    "add to curiosity queue",
    "random curiosity",
    "explain my curiosity",
    "what questions do i have",
    "notify me when you capture",
    "stop notifying me",
    "things i wonder about",
}

# BUG-2: Whole-word regex exit detection — prevents false exits on "no, explain..."
_EXIT_PATTERN = re.compile(
    r'\b(stop|exit|quit|done|cancel|bye|goodbye|never\s*mind|no\s*thanks|'
    r"that'?s\s*all|nothing|nah)\b",
    re.IGNORECASE,
)

ANSWER_SYSTEM_PROMPT = (
    "You're answering a genuine curiosity in 3-4 conversational sentences. "
    "Be fascinating, clear, and accessible. Avoid jargon unless you briefly explain it. "
    "End with one thought-provoking follow-up observation. "
    "No bullet points — this will be spoken aloud."
)

ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
}


# BUG-9: Single shared empty-data factory — used in all three _load_queue paths
def _empty_queue_data() -> dict:
    return {
        "queue": [],
        "history": [],
        "settings": {"instant_explain": False, "last_brief_date": ""},
        "stats": {"total_captured": 0, "total_answered": 0},
        "meta": {"last_processed_length": 0},
    }


class CuriosityQueueCapability(MatchingCapability):
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
        """BUG-2: Whole-word exit check — 'no' only triggers on standalone 'no', not in phrases."""
        if not text or not text.strip():
            return True
        stripped = text.strip().rstrip(".,!?").strip().lower()
        if stripped == "no":
            return True
        return bool(_EXIT_PATTERN.search(text))

    def _strip_json_fences(self, raw: str) -> str:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            ).strip()
        return raw

    def _pending(self, data: dict) -> list:
        return [i for i in data.get("queue", []) if not i.get("answered", False)]

    def _answered_in_queue(self, data: dict) -> list:
        return [i for i in data.get("queue", []) if i.get("answered", False)]

    def _classify_intent(self, text: str) -> str:
        t = text.lower()

        # Destructive ops — check before generic keywords
        if any(kw in t for kw in ("clear", "delete", "wipe", "remove")) and "all" in t:
            return "CLEAR_ALL"
        if any(kw in t for kw in ("clear", "remove", "delete")) and any(
            kw in t for kw in ("answered", "done", "completed")
        ):
            return "CLEAR_ANSWERED"

        # Toggle notifications
        if any(kw in t for kw in ("stop notif", "silent mode", "no notif", "disable notif")):
            return "TOGGLE_INSTANT_OFF"
        if any(kw in t for kw in ("notify me", "let me know when", "instant explain", "real-time", "real time")):
            return "TOGGLE_INSTANT_ON"

        # History
        if any(kw in t for kw in ("history", "what did i learn", "past curiosi", "already answered")):
            return "HISTORY"

        # Manual add
        if any(kw in t for kw in ("add to", "add a", "save to", "save a", "remember", "note down")):
            return "ADD"

        # Explore all
        if "all" in t and any(kw in t for kw in ("explain", "tell me", "answer", "go through")):
            return "EXPLORE_ALL"

        # Explore one
        if any(kw in t for kw in ("explain", "tell me about", "answer", "explore", "dive into", "random")):
            return "EXPLORE"

        # Default: list
        return "LIST"

    def _build_topic_list(self, items: list) -> str:
        """Build a spoken flat numbered list of topics, capped at 10."""
        capped = items[:10]
        parts = [f"{i + 1}. {item['topic']}" for i, item in enumerate(capped)]
        result = ". ".join(parts)
        if len(items) > 10:
            result += f". And {len(items) - 10} more."
        return result

    def _build_grouped_topic_list(self, items: list) -> str:
        """UX-3: Group topics by category (how/why/what/other) for clarity."""
        capped = items[:10]

        groups: dict = {}
        for item in capped:
            cat = item.get("category", "other")
            if cat not in groups:
                groups[cat] = []
            groups[cat].append(item)

        # Fall back to flat list when all items share a single category
        if len(groups) == 1:
            return self._build_topic_list(items)

        parts = []
        idx = 1
        for cat in ["how", "why", "what", "other"]:
            if cat not in groups:
                continue
            group_items = groups[cat]
            n = len(group_items)
            if cat == "other":
                heading = f"{n} {'other' if n == 1 else 'others'}"
            else:
                heading = f"{n} '{cat}' {'question' if n == 1 else 'questions'}"
            nums = [f"{idx + j}. {item['topic']}" for j, item in enumerate(group_items)]
            parts.append(f"{heading}: {'. '.join(nums)}")
            idx += n

        result = ". ".join(parts)
        if len(items) > 10:
            result += f". And {len(items) - 10} more."
        return result

    def _infer_category(self, topic: str) -> str:
        """UX-6: Lightweight keyword-based category inference for manually-added topics."""
        t = topic.lower().strip()
        if re.search(r'\bhow\b', t):
            return "how"
        if re.search(r'\bwhy\b', t):
            return "why"
        if re.search(r'\bwhat\b', t):
            return "what"
        return "other"

    def _select_item(self, pending: list, hint: str) -> Optional[dict]:
        """
        Pick a pending curiosity from hint text.
        Priority: explicit number > ordinal word > 'random' > keyword match > first item.
        """
        if not pending:
            return None

        t = hint.lower()

        # Explicit digit: "explain the 2nd one" / "number 3"
        num_match = re.search(r'\b(\d+)\b', hint)
        if num_match:
            idx = int(num_match.group(1)) - 1
            if 0 <= idx < len(pending):
                return pending[idx]

        # Ordinal words: "the first one", "second curiosity"
        for word, idx in ORDINALS.items():
            if word in t:
                real_idx = idx - 1
                if 0 <= real_idx < len(pending):
                    return pending[real_idx]

        # Random
        if "random" in t or "surprise" in t:
            return random.choice(pending)

        # Keyword overlap between hint and topic
        hint_words = set(re.findall(r'\b[a-z]+\b', t))
        best_item = None
        best_overlap = 0
        for item in pending:
            topic_words = set(re.findall(r'\b[a-z]+\b', item["topic"].lower()))
            overlap = len(hint_words & topic_words)
            if overlap > best_overlap:
                best_overlap = overlap
                best_item = item
        if best_item and best_overlap > 0:
            return best_item

        # Default: first unanswered
        return pending[0]

    def _generate_answer(self, topic: str) -> str:
        """Generate a 3-4 sentence spoken answer for a curiosity topic."""
        try:
            return self.capability_worker.text_to_text_response(
                f"The user is curious about: {topic}",
                system_prompt=ANSWER_SYSTEM_PROMPT,
            )
        except Exception:
            return (
                f"That's a fascinating topic — {topic}. "
                "I wasn't able to generate a full answer right now, but it's definitely worth exploring!"
            )

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    async def _load_queue(self) -> dict:
        try:
            exists = await self.capability_worker.check_if_file_exists(QUEUE_FILE, False)
            if not exists:
                return _empty_queue_data()  # BUG-9
            raw = await self.capability_worker.read_file(QUEUE_FILE, False)
            if not raw or not raw.strip():
                return _empty_queue_data()  # BUG-9
            return json.loads(raw)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[CuriosityQueue] Load error: {e}")
            return _empty_queue_data()  # BUG-9

    async def _save_queue(self, data: dict):
        try:
            exists = await self.capability_worker.check_if_file_exists(QUEUE_FILE, False)
            if exists:
                await self.capability_worker.delete_file(QUEUE_FILE, False)
            await self.capability_worker.write_file(
                QUEUE_FILE, json.dumps(data, indent=2), False
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[CuriosityQueue] Save error: {e}")

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------

    async def _handle_list(self, data: dict):
        pending = self._pending(data)

        if not pending:
            if self._answered_in_queue(data) or data.get("history"):
                await self.capability_worker.speak(
                    "Your curiosity queue is all caught up — nothing left to explore! "
                    "Say 'history' to hear what you've already learned, or just keep talking and I'll capture new ones."
                )
            else:
                await self.capability_worker.speak(
                    "Your curiosity queue is empty! Just talk naturally — whenever you wonder about "
                    "something, I'll quietly add it to your queue."
                )
            return

        count = len(pending)
        # UX-3: Grouped list by category
        topic_list = self._build_grouped_topic_list(pending)
        await self.capability_worker.speak(
            f"You have {count} {'curiosity' if count == 1 else 'curiosities'} waiting. {topic_list}."
        )

        await self.capability_worker.speak(
            "Want me to explain one? Say a number, say 'random', or say stop."
        )

        reply = await self.capability_worker.user_response()
        if self._is_exit(reply):
            return

        await self._handle_explore(data, reply)

    async def _handle_explore(self, data: dict, hint: str = "", depth: int = 0):
        # UX-8: Reload fresh data at each explore to catch background daemon additions
        data = await self._load_queue()

        # Recursion depth cap
        if depth >= 3:
            await self.capability_worker.speak(
                "You've been on quite a curiosity journey! Come back anytime to keep exploring."
            )
            return

        pending = self._pending(data)
        if not pending:
            await self.capability_worker.speak(
                "Your curiosity queue is empty — nothing left to explore!"
            )
            return

        selected = self._select_item(pending, hint)
        if selected is None:
            await self.capability_worker.speak(
                "I couldn't find that one — let me explain the first item instead."
            )
            selected = pending[0]

        topic = selected["topic"]
        self.worker.editor_logging_handler.info(f"[CuriosityQueue] Explaining: {topic}")

        # Generate answer (sync LLM call)
        answer = self._generate_answer(topic)

        # BUG-7: Use found flag to detect race with background daemon; BUG-8: record answered_at
        found = False
        for item in data["queue"]:
            if item["id"] == selected["id"]:
                item["answered"] = True
                item["answer"] = answer
                item["answered_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                found = True
                break
        if not found:
            self.worker.editor_logging_handler.error(
                f"[CuriosityQueue] Item not found in queue after answer: {selected['id']}"
            )

        data["stats"]["total_answered"] = data["stats"].get("total_answered", 0) + 1
        await self._save_queue(data)

        await self.capability_worker.speak(answer)

        # Check remaining after marking answered
        remaining = self._pending(data)
        if not remaining:
            # UX-4: Warm closure when queue is fully explored
            await self.capability_worker.speak(
                "That's your last curiosity — all caught up! Keep wondering and I'll keep capturing."
            )
        else:
            remaining_count = len(remaining)
            await self.capability_worker.speak(
                f"You have {remaining_count} more {'curiosity' if remaining_count == 1 else 'curiosities'}. "
                "Want me to explain another? Say a number, 'random', or stop."
            )
            reply = await self.capability_worker.user_response()
            if not self._is_exit(reply):
                await self._handle_explore(data, reply, depth + 1)

    async def _handle_explore_all(self, data: dict):
        pending = self._pending(data)
        if not pending:
            await self.capability_worker.speak("Your curiosity queue is empty — nothing to explore!")
            return

        total_pending = len(pending)
        # BUG-10: Cap at EXPLORE_ALL_CAP (5) per invocation to avoid multi-minute blocking
        batch = pending[:EXPLORE_ALL_CAP]

        if total_pending <= EXPLORE_ALL_CAP:
            await self.capability_worker.speak(
                f"I'll give you a quick overview of all {total_pending} "
                f"{'curiosity' if total_pending == 1 else 'curiosities'}."
            )
        else:
            await self.capability_worker.speak(
                f"You have {total_pending} curiosities — I'll walk through the first {EXPLORE_ALL_CAP}."
            )

        for item in batch:
            topic = item["topic"]
            try:
                brief = self.capability_worker.text_to_text_response(
                    f"Give exactly one fascinating sentence about: {topic}. No bullet points. Spoken aloud.",
                    system_prompt="You are a curiosity guide. One sentence only, spoken aloud. Be fascinating.",
                )
            except Exception:
                brief = "A fascinating topic worth exploring further."

            await self.capability_worker.speak(f"{topic}: {brief}")

            item["answered"] = True
            item["answer"] = brief
            item["answered_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        batch_count = len(batch)
        data["stats"]["total_answered"] = data["stats"].get("total_answered", 0) + batch_count
        await self._save_queue(data)

        # BUG-10: Offer next batch if more remain
        if total_pending > EXPLORE_ALL_CAP:
            still_remaining = total_pending - EXPLORE_ALL_CAP
            await self.capability_worker.speak(
                f"That's {EXPLORE_ALL_CAP}. You have {still_remaining} more. "
                "Want me to continue with the next batch?"
            )
            reply = await self.capability_worker.user_response()
            if not self._is_exit(reply):
                fresh = await self._load_queue()
                await self._handle_explore_all(fresh)
        else:
            await self.capability_worker.speak(
                "All done! Your curiosity queue is now empty. Keep wondering — I'll keep capturing."
            )

    async def _handle_add(self, data: dict, trigger_text: str):
        # Try to extract topic from trigger text
        topic = ""
        t = trigger_text.lower()
        add_markers = [
            "add to my curiosity queue", "add to curiosity queue",
            "add to the queue", "save to curiosity", "add a curiosity",
            "add", "save", "remember", "note down",
        ]
        for marker in add_markers:
            if marker in t:
                idx = t.index(marker) + len(marker)
                after = trigger_text[idx:].strip().lstrip(",:- ").strip()
                if len(after.split()) >= 2:
                    topic = after[:200]
                    break

        if not topic:
            reply = await self.capability_worker.run_io_loop(
                "What would you like to add to your curiosity queue?"
            )
            if self._is_exit(reply) or not reply:
                return
            topic = reply.strip()[:200]

        if not topic:
            await self.capability_worker.speak("I didn't catch a topic. No worries!")
            return

        # BUG-6: Dedup check — same 60% word-overlap threshold as the background daemon
        topic_words = set(re.findall(r'\b[a-z]+\b', topic.lower()))
        for existing in data.get("queue", []):
            if existing.get("answered"):
                continue
            existing_words = set(re.findall(r'\b[a-z]+\b', existing.get("topic", "").lower()))
            if existing_words:
                overlap = len(topic_words & existing_words) / max(len(topic_words), len(existing_words), 1)
                if overlap >= 0.60:
                    await self.capability_worker.speak(
                        "That's already in your queue! Say 'curiosity queue' to explore it."
                    )
                    return

        # UX-6: Infer category from topic text
        category = self._infer_category(topic)

        entry = {
            "id": str(int(datetime.now().timestamp() * 1000)),
            "topic": topic,
            "raw": trigger_text[:500],
            "captured_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "answered": False,
            "answer": None,
            "answered_at": None,
            "category": category,
        }
        data.setdefault("queue", []).append(entry)
        data["stats"]["total_captured"] = data["stats"].get("total_captured", 0) + 1

        # Overflow: max 50 items — archive oldest answered item, or oldest if all unanswered
        if len(data["queue"]) > 50:
            answered = [i for i in data["queue"] if i.get("answered")]
            oldest = min(
                answered if answered else data["queue"],
                key=lambda x: x.get("captured_at", "")
            )
            data["queue"].remove(oldest)
            data.setdefault("history", []).append(oldest)

        # History cap
        if len(data.get("history", [])) > 100:
            data["history"] = data["history"][-100:]

        await self._save_queue(data)

        pending_count = len(self._pending(data))
        await self.capability_worker.speak(
            f"Added! You now have {pending_count} {'curiosity' if pending_count == 1 else 'curiosities'} to explore."
        )

    async def _handle_clear_answered(self, data: dict):
        answered = self._answered_in_queue(data)
        if not answered:
            await self.capability_worker.speak("No answered curiosities to clear — queue is already tidy!")
            return

        count = len(answered)
        confirmed = await self.capability_worker.run_confirmation_loop(
            f"Clear {count} answered {'curiosity' if count == 1 else 'curiosities'} from your queue?"
        )
        if confirmed:
            data["queue"] = [i for i in data["queue"] if not i.get("answered", False)]
            await self._save_queue(data)
            await self.capability_worker.speak(
                f"Cleared {count} answered {'curiosity' if count == 1 else 'curiosities'}. Your queue is tidy now."
            )
        else:
            await self.capability_worker.speak("No problem — keeping everything.")

    async def _handle_clear_all(self, data: dict):
        total = len(data.get("queue", []))
        if total == 0:
            await self.capability_worker.speak("Your curiosity queue is already empty!")
            return

        confirmed = await self.capability_worker.run_confirmation_loop(
            f"Clear all {total} items including unanswered ones?"
        )
        if confirmed:
            data["queue"] = []
            await self._save_queue(data)
            await self.capability_worker.speak(
                "Done — curiosity queue cleared. Start fresh anytime!"
            )
        else:
            await self.capability_worker.speak("No problem, keeping everything.")

    async def _handle_toggle(self, intent: str, data: dict):
        turn_on = intent == "TOGGLE_INSTANT_ON"
        data.setdefault("settings", {})["instant_explain"] = turn_on
        await self._save_queue(data)
        if turn_on:
            await self.capability_worker.speak(
                "Got it — I'll give you a heads-up each time I add something to your curiosity queue."
            )
        else:
            await self.capability_worker.speak(
                "Done — I'll capture curiosities silently from now on. Ask anytime to review your queue."
            )

    async def _handle_history(self, data: dict):
        answered_queue = self._answered_in_queue(data)
        history_items = data.get("history", [])

        all_answered = answered_queue + history_items
        # BUG-8: Sort by answered_at (when it was actually explored), fallback to captured_at
        all_answered_sorted = sorted(
            all_answered,
            key=lambda x: x.get("answered_at") or x.get("captured_at", ""),
            reverse=True,
        )
        recent = all_answered_sorted[:5]

        if not recent:
            await self.capability_worker.speak(
                "No answered curiosities yet — start exploring to build up your history!"
            )
            return

        topic_list = ". ".join(
            f"{i + 1}. {item['topic']}" for i, item in enumerate(recent)
        )
        await self.capability_worker.speak(
            f"Here are your {len(recent)} most recently explored curiosities. {topic_list}."
        )

        # UX-5: Append lifetime stats
        total_captured = data["stats"].get("total_captured", 0)
        total_answered = data["stats"].get("total_answered", 0)
        if total_captured > 0:
            await self.capability_worker.speak(
                f"You've explored {total_answered} of {total_captured} "
                f"{'curiosity' if total_captured == 1 else 'curiosities'} total."
            )

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    async def _run(self):
        try:
            await self.capability_worker.wait_for_complete_transcription()

            # Get trigger utterance from history
            trigger_text = ""
            try:
                history = self.capability_worker.get_full_message_history()
                history = history or []
                user_msgs = [m for m in history if m.get("role") == "user"]
                if user_msgs:
                    trigger_text = user_msgs[-1].get("content", "") or ""
                    if not isinstance(trigger_text, str):
                        trigger_text = ""
            except Exception:
                trigger_text = ""

            intent = self._classify_intent(trigger_text)
            self.worker.editor_logging_handler.info(
                f"[CuriosityQueue] Intent: {intent} | Trigger: {trigger_text[:80]}"
            )

            data = await self._load_queue()

            if intent == "LIST":
                await self._handle_list(data)
            elif intent == "EXPLORE":
                await self._handle_explore(data, trigger_text)
            elif intent == "EXPLORE_ALL":
                await self._handle_explore_all(data)
            elif intent == "ADD":
                await self._handle_add(data, trigger_text)
            elif intent == "CLEAR_ANSWERED":
                await self._handle_clear_answered(data)
            elif intent == "CLEAR_ALL":
                await self._handle_clear_all(data)
            elif intent in ("TOGGLE_INSTANT_ON", "TOGGLE_INSTANT_OFF"):
                await self._handle_toggle(intent, data)
            elif intent == "HISTORY":
                await self._handle_history(data)
            else:
                await self.capability_worker.speak(
                    "I can list your curiosities, explain them, add new ones, or clear answered ones. What would you like?"
                )

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[CuriosityQueue] Skill error: {e}")
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
