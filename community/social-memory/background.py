import json
import re
from datetime import datetime, timedelta

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

MEMORY_FILE = "social_memory.json"
POLL_INTERVAL = 15.0
SAVE_EVERY_N_POLLS = 20
MAX_LLM_CALLS_PER_POLL = 3
MAX_SNIPPETS_PER_PERSON = 5
MAX_PEOPLE = 100
STARTUP_NOTIFY_MIN = 1
MAX_PERSONALITY_INJECTIONS = 4
NUDGE_AFTER_DAYS = 3

SKIP_PHRASES = [
    "can you", "could you", "would you", "will you",
    "tell me about", "what do you know about",
    "who is", "who are",
    "hypothetically", "if someone", "if a person",
    "let's say", "what if",
]


def _new_state() -> dict:
    return {
        "last_processed_index": 0,
        "polls_since_save": 0,
        "startup_notified": False,
        "personality_injected_count": 0,
        "nudge_fired_today": False,
        "current_day": "",
    }


def _empty_memory_data() -> dict:
    return {
        "people": [],
        "history": [],
        "settings": {
            "notify_on_capture": False,
            "follow_up_nudge_after_days": NUDGE_AFTER_DAYS,
            "last_nudge_date": "",
        },
        "stats": {
            "total_people_captured": 0,
            "total_follow_ups_captured": 0,
            "total_follow_ups_completed": 0,
        },
        "meta": {"last_processed_length": 0},
    }


def _new_person(name: str, relationship_hint: str) -> dict:
    now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return {
        "id": str(int(datetime.now().timestamp() * 1000)),
        "name": name,
        "name_normalized": name.lower().strip(),
        "relationship_hint": relationship_hint,
        "first_mentioned": now_str[:10],
        "last_mentioned": now_str,
        "mention_count": 0,
        "ambiguous_identity": False,
        "context_snippets": [],
        "follow_ups": [],
    }


def _resolve_deadline(deadline_hint: str) -> str:
    today = datetime.now()
    h = deadline_hint.lower().strip()
    if "today" in h:
        return today.strftime("%Y-%m-%d")
    if "tomorrow" in h:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    if "weekend" in h:
        days = (7 - today.weekday()) % 7 or 7
        return (today + timedelta(days=days)).strftime("%Y-%m-%d")
    day_offsets = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    for day_name, target_weekday in day_offsets.items():
        if day_name in h:
            days = (target_weekday - today.weekday()) % 7 or 7
            return (today + timedelta(days=days)).strftime("%Y-%m-%d")
    if "next week" in h:
        return (today + timedelta(days=7)).strftime("%Y-%m-%d")
    if "this week" in h:
        return (today + timedelta(days=3)).strftime("%Y-%m-%d")
    if "next month" in h:
        return (today + timedelta(days=30)).strftime("%Y-%m-%d")
    return (today + timedelta(days=7)).strftime("%Y-%m-%d")


class SocialMemoryBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # Do not change following tag of register capability
    # {{register capability}}

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    async def _load_memory(self) -> dict:
        try:
            exists = await self.capability_worker.check_if_file_exists(MEMORY_FILE, False)
            if not exists:
                return _empty_memory_data()
            raw = await self.capability_worker.read_file(MEMORY_FILE, False)
            if not raw or not raw.strip():
                return _empty_memory_data()
            return json.loads(raw)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SocialMemory] Load error: {e}")
            return _empty_memory_data()

    async def _save_memory(self, data: dict):
        try:
            exists = await self.capability_worker.check_if_file_exists(MEMORY_FILE, False)
            if exists:
                await self.capability_worker.delete_file(MEMORY_FILE, False)
            await self.capability_worker.write_file(
                MEMORY_FILE, json.dumps(data, indent=2), False
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SocialMemory] Save error: {e}")

    async def _restore_from_file(self, s: dict) -> dict:
        data = await self._load_memory()
        s["last_processed_index"] = data.get("meta", {}).get("last_processed_length", 0)
        return data

    # ------------------------------------------------------------------
    # Detection helpers
    # ------------------------------------------------------------------

    def _skip_phrase_filter(self, text: str) -> bool:
        t = text.lower()
        return any(phrase in t for phrase in SKIP_PHRASES)

    def _phase1_fast_filter(self, text: str) -> bool:
        return len(text.split()) >= 4

    def _strip_json_fences(self, raw: str) -> str:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            ).strip()
        return raw

    def _phase2_llm_extract(self, text: str) -> dict | None:
        prompt = (
            f"The user said: '{text}'\n\n"
            "Extract any real people (not the AI assistant, not the user themselves) who are mentioned.\n\n"
            "For each person found, determine:\n"
            "1. name: Their first name or nickname as spoken — preserve casing\n"
            "2. relationship_hint: What does context suggest — friend, colleague, manager, "
            "partner, family, acquaintance, or unknown\n"
            "3. context_snippet: What was said about them in max 100 chars. "
            "No 'The user...' framing.\n"
            "4. speaker_relation: DIRECT (user interacted with person) or INDIRECT "
            "(user heard about them secondhand)\n"
            "   DIRECT: 'I had lunch with Sarah', 'Jake pushed back', 'I called Marcus'\n"
            "   INDIRECT: 'She told me about Jake', 'Apparently Tom got promoted'\n"
            "5. follow_up: Only for DIRECT mentions — if the user committed to doing "
            "something toward this person.\n"
            "   Format: {\"commitment\": \"call Sarah\", \"deadline_hint\": \"after the weekend\"}\n"
            "   Set to null if no commitment, or if speaker_relation is INDIRECT.\n\n"
            "Only capture real people the user personally knows. Skip:\n"
            "- Public figures unless clearly a personal relationship\n"
            "- Impersonal service references ('emailed support', 'talked to customer service')\n"
            "- Fictional characters\n"
            "- The user themselves\n"
            "- Pronoun-only references ('him', 'her') with no associated name\n\n"
            "Return ONLY valid JSON, no markdown:\n"
            "{\"people\": [{\"name\": \"Sarah\", \"relationship_hint\": \"friend\", "
            "\"context_snippet\": \"had lunch together\", \"speaker_relation\": \"direct\", "
            "\"follow_up\": {\"commitment\": \"call Sarah about the project\", "
            "\"deadline_hint\": \"this week\"}}]}\n"
            "OR if no real people found: {\"people\": []}"
        )
        try:
            raw = self.capability_worker.text_to_text_response(prompt)
            cleaned = self._strip_json_fences(raw)
            parsed = json.loads(cleaned)
            people = parsed.get("people", [])
            if not isinstance(people, list) or not people:
                return None
            return parsed
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SocialMemory] Phase 2 parse error: {e}")
            return None

    def _is_duplicate_snippet(self, text: str, person: dict) -> bool:
        words_new = set(re.findall(r'\b[a-z]+\b', text.lower()))
        if not words_new:
            return False
        for snippet in person.get("context_snippets", []):
            words_ex = set(re.findall(r'\b[a-z]+\b', snippet.get("text", "").lower()))
            if words_ex:
                overlap = len(words_new & words_ex) / max(len(words_new), len(words_ex), 1)
                if overlap >= 0.70:
                    return True
        return False

    def _is_duplicate_followup(self, commitment: str, person: dict) -> bool:
        words_new = set(re.findall(r'\b[a-z]+\b', commitment.lower()))
        if not words_new:
            return False
        for fup in person.get("follow_ups", []):
            if fup.get("status") != "pending":
                continue
            words_ex = set(re.findall(r'\b[a-z]+\b', fup.get("commitment", "").lower()))
            if words_ex:
                overlap = len(words_new & words_ex) / max(len(words_new), len(words_ex), 1)
                if overlap >= 0.60:
                    return True
        return False

    # ------------------------------------------------------------------
    # Person management
    # ------------------------------------------------------------------

    def _merge_person(self, person_data: dict, data: dict, s: dict) -> dict:
        name = person_data.get("name", "").strip()
        if not name or len(name) < 2:
            return data

        name_normalized = name.lower().strip()
        relationship_hint = person_data.get("relationship_hint", "unknown")
        context_snippet = person_data.get("context_snippet", "").strip()[:100]
        speaker_relation = person_data.get("speaker_relation", "direct")
        follow_up_data = person_data.get("follow_up")
        now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        existing = None
        for p in data.get("people", []):
            if p.get("name_normalized", "") == name_normalized:
                existing = p
                break
        if existing is None:
            for p in data.get("people", []):
                stored = p.get("name_normalized", "")
                if name_normalized in stored or stored in name_normalized:
                    existing = p
                    break

        if existing is None:
            if len(data.get("people", [])) >= MAX_PEOPLE:
                oldest = min(data["people"], key=lambda p: p.get("last_mentioned", ""))
                data["people"].remove(oldest)
                data.setdefault("history", []).append(oldest)
                if len(data.get("history", [])) > 50:
                    data["history"] = data["history"][-50:]

            existing = _new_person(name, relationship_hint)
            data["people"].append(existing)
            data["stats"]["total_people_captured"] = (
                data["stats"].get("total_people_captured", 0) + 1
            )

            if s["personality_injected_count"] < MAX_PERSONALITY_INJECTIONS and context_snippet:
                try:
                    self.capability_worker.update_personality_agent_prompt(
                        f"[Social context]: {name} — {relationship_hint}. {context_snippet}"
                    )
                    s["personality_injected_count"] += 1
                except Exception:
                    pass
        else:
            existing_rel = existing.get("relationship_hint", "unknown")
            if existing_rel in ("unknown", "") and relationship_hint not in ("unknown", ""):
                existing["relationship_hint"] = relationship_hint
                if s["personality_injected_count"] < MAX_PERSONALITY_INJECTIONS and context_snippet:
                    try:
                        self.capability_worker.update_personality_agent_prompt(
                            f"[Social context]: {name} — {relationship_hint}. {context_snippet}"
                        )
                        s["personality_injected_count"] += 1
                    except Exception:
                        pass
            elif (
                existing_rel not in ("unknown", "")
                and relationship_hint not in ("unknown", "")
                and existing_rel != relationship_hint
                and not existing.get("ambiguous_identity", False)
            ):
                conflicting = [
                    {"colleague", "family"}, {"friend", "family"}, {"manager", "family"},
                    {"colleague", "partner"}, {"friend", "manager"},
                ]
                if any({existing_rel, relationship_hint} == pair for pair in conflicting):
                    existing["ambiguous_identity"] = True

        existing["last_mentioned"] = now_str
        existing["mention_count"] = existing.get("mention_count", 0) + 1

        if context_snippet and not self._is_duplicate_snippet(context_snippet, existing):
            existing.setdefault("context_snippets", []).append({
                "text": context_snippet,
                "captured_at": now_str,
                "speaker_relation": speaker_relation,
            })
            if len(existing["context_snippets"]) > MAX_SNIPPETS_PER_PERSON:
                existing["context_snippets"] = existing["context_snippets"][-MAX_SNIPPETS_PER_PERSON:]

        if follow_up_data and speaker_relation == "direct":
            commitment = follow_up_data.get("commitment", "").strip()[:200]
            deadline_hint = follow_up_data.get("deadline_hint", "").strip()
            if commitment and not self._is_duplicate_followup(commitment, existing):
                existing.setdefault("follow_ups", []).append({
                    "id": f"fu_{int(datetime.now().timestamp() * 1000)}",
                    "commitment": commitment,
                    "deadline_hint": deadline_hint or "no deadline",
                    "deadline_date": _resolve_deadline(deadline_hint) if deadline_hint else _resolve_deadline(""),
                    "captured_at": now_str,
                    "status": "pending",
                    "completed_at": None,
                    "nudge_count": 0,
                    "last_nudged": None,
                })
                data["stats"]["total_follow_ups_captured"] = (
                    data["stats"].get("total_follow_ups_captured", 0) + 1
                )

        return data

    # ------------------------------------------------------------------
    # Follow-up nudge
    # ------------------------------------------------------------------

    async def _check_followup_nudges(self, s: dict):
        if s["nudge_fired_today"]:
            return

        today = datetime.now().date()
        today_str = today.strftime("%Y-%m-%d")
        data = await self._load_memory()
        nudge_after = data["settings"].get("follow_up_nudge_after_days", NUDGE_AFTER_DAYS)

        most_overdue_fup = None
        most_overdue_days = 0

        for person in data.get("people", []):
            for fup in person.get("follow_ups", []):
                if fup.get("status") != "pending":
                    continue
                if fup.get("last_nudged") == today_str:
                    continue
                try:
                    deadline_str = fup.get("deadline_date", "")
                    if not deadline_str:
                        continue
                    deadline = datetime.strptime(deadline_str, "%Y-%m-%d").date()
                    days_overdue = (today - deadline).days
                    if days_overdue >= nudge_after and days_overdue > most_overdue_days:
                        most_overdue_days = days_overdue
                        most_overdue_fup = fup
                except Exception:
                    continue

        if not most_overdue_fup:
            return

        commitment = most_overdue_fup["commitment"]
        deadline_hint = most_overdue_fup.get("deadline_hint", "")

        if deadline_hint and deadline_hint not in ("no deadline", ""):
            msg = (
                f"By the way — you said you'd {commitment} {deadline_hint}. "
                f"That was {most_overdue_days} "
                f"{'day' if most_overdue_days == 1 else 'days'} ago. "
                "Still on your list?"
            )
        else:
            msg = (
                f"Heads up — you mentioned you'd {commitment}. "
                f"That was {most_overdue_days} "
                f"{'day' if most_overdue_days == 1 else 'days'} ago. "
                "Still planning to?"
            )

        # Set flags FIRST — prevents double-fire if speak() raises
        most_overdue_fup["nudge_count"] = most_overdue_fup.get("nudge_count", 0) + 1
        most_overdue_fup["last_nudged"] = today_str
        await self._save_memory(data)
        s["nudge_fired_today"] = True

        try:
            await self.capability_worker.send_interrupt_signal()
            await self.capability_worker.speak(msg)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SocialMemory] Nudge speak error: {e}")

    # ------------------------------------------------------------------
    # Main daemon loop
    # ------------------------------------------------------------------

    async def watch_loop(self):
        s = _new_state()
        self.worker.editor_logging_handler.info("[SocialMemory] daemon started")
        cached_data = await self._restore_from_file(s)
        # Release immediately — without this, hotword-triggered daemon (background_daemon_mode=False)
        # would block all conversation input permanently since watch_loop never returns.
        self.capability_worker.resume_normal_flow()

        try:
            pending_fups = [
                f
                for p in cached_data.get("people", [])
                for f in p.get("follow_ups", [])
                if f.get("status") == "pending"
            ]
            if len(pending_fups) >= STARTUP_NOTIFY_MIN and not s["startup_notified"]:
                count = len(pending_fups)
                await self.capability_worker.send_interrupt_signal()
                await self.capability_worker.speak(
                    f"Just so you know — you have {count} pending "
                    f"{'follow-up' if count == 1 else 'follow-ups'} with people from before. "
                    "Say 'social memory' anytime to review them."
                )
                s["startup_notified"] = True
        except Exception:
            pass

        while True:
            try:
                history = self.capability_worker.get_full_message_history()
                history = history or []
                current_length = len(history)

                if s["last_processed_index"] == 0 and current_length > 10:
                    s["last_processed_index"] = current_length - 10

                if s["last_processed_index"] > current_length:
                    s["last_processed_index"] = max(0, current_length - 3)

                new_msgs = history[s["last_processed_index"]:]
                s["last_processed_index"] = current_length

                llm_calls_this_poll = 0
                for msg in new_msgs:
                    if msg.get("role") != "user":
                        continue
                    text = msg.get("content", "")
                    if not isinstance(text, str):
                        continue
                    text = text.strip()

                    # Fallback for "forget about [name]" — platform sometimes routes
                    # short conversational phrases to the main agent before does_match()
                    # is called. Detect from history and redirect user to the foreground skill.
                    tl = text.lower()
                    if any(p in tl for p in (
                        "forget about", "remove from social memory", "delete from social memory",
                    )):
                        await self.capability_worker.send_interrupt_signal()
                        await self.capability_worker.speak(
                            "To remove someone from your social memory, say 'social memory' and I'll take care of it."
                        )
                        continue

                    if self._skip_phrase_filter(text):
                        continue
                    if not self._phase1_fast_filter(text):
                        continue
                    if llm_calls_this_poll >= MAX_LLM_CALLS_PER_POLL:
                        break

                    result = self._phase2_llm_extract(text)
                    llm_calls_this_poll += 1
                    if result is None:
                        continue

                    data = await self._load_memory()
                    for person_data in result.get("people", []):
                        data = self._merge_person(person_data, data, s)

                    data.setdefault("meta", {})["last_processed_length"] = s["last_processed_index"]
                    await self._save_memory(data)
                    s["polls_since_save"] = 0

                    for person_data in result.get("people", []):
                        self.worker.editor_logging_handler.info(
                            f"[SocialMemory] Captured: {person_data.get('name', '?')}"
                        )

                today = datetime.now().strftime("%Y-%m-%d")
                if today != s["current_day"]:
                    s["current_day"] = today
                    s["nudge_fired_today"] = False

                await self._check_followup_nudges(s)

            except Exception as e:
                self.worker.editor_logging_handler.error(f"[SocialMemory] Loop error: {e}")

            s["polls_since_save"] += 1
            if s["polls_since_save"] >= SAVE_EVERY_N_POLLS:
                try:
                    fresh = await self._load_memory()
                    fresh.setdefault("meta", {})["last_processed_length"] = s["last_processed_index"]
                    await self._save_memory(fresh)
                    s["polls_since_save"] = 0
                except Exception:
                    pass

            await self.worker.session_tasks.sleep(POLL_INTERVAL)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.background_daemon_mode = background_daemon_mode
        self.worker.session_tasks.create(self.watch_loop())
