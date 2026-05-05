import json
import re
from datetime import datetime, timedelta

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

MEMORY_FILE = "social_memory.json"
MAX_SNIPPETS_PER_PERSON = 5

HOTWORDS = {
    "social memory", "my social memory",
    "tell me about", "what do i know about", "what have i said about",
    "remind me about",
    "who have i mentioned", "people i've mentioned", "who have i talked about",
    "my people", "people i know",
    "any follow-ups", "any follow ups", "pending follow-ups", "pending follow ups",
    "who do i owe", "who should i reach out to",
    "what did i say i'd do", "commitments i made",
    "add a note about", "note about someone", "add someone",
    "forget about", "remove person", "delete person", "stop tracking",
    "clear my social memory", "clear all people", "wipe my social memory",
    "memory stats",
}

_EXIT_PATTERN = re.compile(
    r'\b(stop|exit|quit|done|cancel|bye|goodbye|never\s*mind|no\s*thanks|'
    r"that'?s\s*all|nothing|nah)\b",
    re.IGNORECASE,
)


def _empty_memory_data() -> dict:
    return {
        "people": [],
        "history": [],
        "settings": {
            "notify_on_capture": False,
            "follow_up_nudge_after_days": 3,
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
    return (today + timedelta(days=7)).strftime("%Y-%m-%d")


class SocialMemoryCapability(MatchingCapability):
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
        if not text or not text.strip():
            return True
        stripped = text.strip().rstrip(".,!?").strip().lower()
        if stripped == "no":
            return True
        return bool(_EXIT_PATTERN.search(text))

    def _classify_intent(self, text: str) -> str:
        t = text.lower()
        if "memory stats" in t or "social stats" in t or "how many people" in t:
            return "STATS"
        if any(kw in t for kw in ("clear", "wipe")) and any(
            kw in t for kw in ("all", "social memory", "people")
        ):
            return "CLEAR"
        if any(kw in t for kw in ("forget about", "remove person", "delete person", "stop tracking")):
            return "FORGET"
        if any(kw in t for kw in (
            "follow-up", "follow up", "owe", "commitments",
            "said i'd", "said i would", "reach out", "pending",
        )):
            return "FOLLOWUPS"
        if any(kw in t for kw in ("add a note", "note about", "add someone", "save a note")):
            return "ADD"
        if any(kw in t for kw in (
            "tell me about", "what do i know about", "what have i said about",
            "remind me about", "what's the deal",
        )):
            return "WHO"
        return "LIST"

    def _find_person(self, name_query: str, data: dict) -> dict | None:
        nq = name_query.lower().strip()
        for p in data.get("people", []):
            if p.get("name_normalized", "") == nq:
                return p
        for p in data.get("people", []):
            stored = p.get("name_normalized", "")
            if nq in stored or stored in nq:
                return p
        return None

    def _extract_name_from_query(self, text: str) -> str:
        prompt = (
            f"The user said: '{text}'\n\n"
            "What is the name of the person they are referring to?\n"
            "Return ONLY the name as a plain string. No JSON, no explanation.\n"
            "Examples:\n"
            "  'tell me about Sarah' → Sarah\n"
            "  'what do I know about Jake from work' → Jake\n"
            "  'remind me about Marcus' → Marcus\n"
            "  'forget about my colleague Alex' → Alex\n"
            "  'add a note about Tom' → Tom\n"
            "If no name is found, return empty string."
        )
        try:
            result = self.capability_worker.text_to_text_response(prompt).strip()
            return result if result and len(result) < 50 else ""
        except Exception:
            return ""

    def _relative_date(self, date_str: str) -> str:
        try:
            dt = datetime.fromisoformat(date_str)
            days = (datetime.now() - dt).days
            if days == 0:
                return "today"
            if days == 1:
                return "yesterday"
            if days < 7:
                return f"{days} days ago"
            if days < 14:
                return "last week"
            if days < 30:
                return f"{days // 7} weeks ago"
            return dt.strftime("%B %d")
        except Exception:
            return "recently"

    def _days_since(self, date_str: str) -> int:
        try:
            return (datetime.now() - datetime.fromisoformat(date_str)).days
        except Exception:
            return 0

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

    # ------------------------------------------------------------------
    # Sub-handlers
    # ------------------------------------------------------------------

    async def _speak_all_snippets(self, person: dict):
        snippets = person.get("context_snippets", [])
        if not snippets:
            await self.capability_worker.speak(
                f"I don't have any detailed context on {person['name']} yet."
            )
            return
        parts = []
        for i, snippet in enumerate(reversed(snippets)):
            relation_note = " (heard about this)" if snippet.get("speaker_relation") == "indirect" else ""
            parts.append(f"{i + 1}. {snippet['text']}{relation_note}")
        await self.capability_worker.speak(
            f"Here's everything I have on {person['name']}: {'. '.join(parts)}."
        )

    async def _handle_complete_followup_for_person(self, person: dict, data: dict):
        pending = [f for f in person.get("follow_ups", []) if f.get("status") == "pending"]
        if not pending:
            await self.capability_worker.speak(f"No pending follow-ups for {person['name']}.")
            return

        now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        if len(pending) == 1:
            fup = pending[0]
            await self.capability_worker.speak(
                f"Mark '{fup['commitment']}' as done? Say yes or no."
            )
            reply = await self.capability_worker.user_response()
            if self._is_exit(reply):
                return
            if any(kw in reply.lower() for kw in ("yes", "yeah", "yep", "sure", "yup", "correct")):
                fup["status"] = "completed"
                fup["completed_at"] = now_str
                data["stats"]["total_follow_ups_completed"] = (
                    data["stats"].get("total_follow_ups_completed", 0) + 1
                )
                await self._save_memory(data)
                await self.capability_worker.speak("Done — follow-up marked complete.")
            return

        parts = [f"{i + 1}. {f['commitment']}" for i, f in enumerate(pending)]
        await self.capability_worker.speak(
            f"You have {len(pending)} pending follow-ups with {person['name']}: "
            f"{'. '.join(parts)}. Say a number or all done."
        )
        reply = await self.capability_worker.user_response()
        if self._is_exit(reply):
            return

        r = reply.lower()
        if "all" in r and "done" in r:
            for fup in pending:
                fup["status"] = "completed"
                fup["completed_at"] = now_str
            data["stats"]["total_follow_ups_completed"] = (
                data["stats"].get("total_follow_ups_completed", 0) + len(pending)
            )
            await self._save_memory(data)
            await self.capability_worker.speak(
                f"Done — all follow-ups with {person['name']} marked complete."
            )
        else:
            num_match = re.search(r'\b(\d+)\b', reply)
            if num_match:
                idx = int(num_match.group(1)) - 1
                if 0 <= idx < len(pending):
                    pending[idx]["status"] = "completed"
                    pending[idx]["completed_at"] = now_str
                    data["stats"]["total_follow_ups_completed"] = (
                        data["stats"].get("total_follow_ups_completed", 0) + 1
                    )
                    await self._save_memory(data)
                    await self.capability_worker.speak(
                        f"Done — '{pending[idx]['commitment']}' marked complete."
                    )

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------

    async def _handle_who(self, data: dict, trigger_text: str):
        name = self._extract_name_from_query(trigger_text)
        if not name:
            await self.capability_worker.speak("Who would you like to know about?")
            reply = await self.capability_worker.user_response()
            if self._is_exit(reply):
                return
            name = reply.strip()
            if not name or len(name) < 2:
                return

        person = self._find_person(name, data)
        if person is None:
            await self.capability_worker.speak(
                f"I don't have anything on {name} yet. "
                "Want me to add a note about them now?"
            )
            reply = await self.capability_worker.user_response()
            if self._is_exit(reply):
                return
            if any(kw in reply.lower() for kw in ("yes", "yeah", "yep", "sure", "yup")):
                await self._handle_add(f"add a note about {name}")
            return

        last_mentioned_str = self._relative_date(person["last_mentioned"])
        relationship = person.get("relationship_hint", "")
        rel_clause = (
            f", who seems to be a {relationship}"
            if relationship and relationship not in ("unknown", "")
            else ""
        )

        snippets = person.get("context_snippets", [])
        snippet_text = snippets[-1]["text"] if snippets else "no details yet"

        msg = (
            f"{person['name']}{rel_clause} — last mentioned {last_mentioned_str}. "
            f"Most recently: {snippet_text}."
        )

        if person.get("ambiguous_identity"):
            msg += (
                " Note: you've mentioned them in different contexts — "
                "they might be two different people with the same name."
            )

        pending_fups = [f for f in person.get("follow_ups", []) if f.get("status") == "pending"]
        if pending_fups:
            fup = pending_fups[0]
            deadline_hint = fup.get("deadline_hint", "")
            days = self._days_since(fup["captured_at"])
            if deadline_hint and deadline_hint != "no deadline":
                msg += f" You also said you'd {fup['commitment']} — {deadline_hint}."
            else:
                msg += (
                    f" You said you'd {fup['commitment']} — "
                    f"{days} {'day' if days == 1 else 'days'} ago."
                )

        await self.capability_worker.speak(msg)

        if pending_fups:
            await self.capability_worker.speak(
                "Want all context I have on them, mark a follow-up done, or stop?"
            )
        else:
            await self.capability_worker.speak(
                "Want all context I have on them, or stop?"
            )
        reply = await self.capability_worker.user_response()
        if self._is_exit(reply):
            return

        r = reply.lower()
        if any(kw in r for kw in ("done", "completed", "finished", "follow")):
            data = await self._load_memory()
            refreshed = self._find_person(person["name"], data)
            if refreshed:
                await self._handle_complete_followup_for_person(refreshed, data)
        elif any(kw in r for kw in ("all", "more", "everything", "context", "snippets")):
            await self._speak_all_snippets(person)

    async def _handle_list(self, data: dict):
        people = data.get("people", [])
        if not people:
            await self.capability_worker.speak(
                "Your social memory is empty — just talk naturally and I'll pick up everyone you mention."
            )
            return

        sorted_people = sorted(people, key=lambda p: p.get("last_mentioned", ""), reverse=True)
        top = sorted_people[:8]
        names_list = ", ".join(p["name"] for p in top)
        suffix = f" and {len(people) - 8} more" if len(people) > 8 else ""

        today_date = datetime.now().date()
        pending_fup_count = 0
        overdue_fup_count = 0
        for p in people:
            for f in p.get("follow_ups", []):
                if f.get("status") != "pending":
                    continue
                pending_fup_count += 1
                try:
                    if datetime.strptime(f.get("deadline_date", ""), "%Y-%m-%d").date() < today_date:
                        overdue_fup_count += 1
                except Exception:
                    pass

        msg = (
            f"You've mentioned {len(people)} "
            f"{'person' if len(people) == 1 else 'people'}: {names_list}{suffix}."
        )
        if pending_fup_count:
            overdue_clause = f", {overdue_fup_count} overdue" if overdue_fup_count else ""
            msg += (
                f" You have {pending_fup_count} pending "
                f"{'follow-up' if pending_fup_count == 1 else 'follow-ups'}{overdue_clause}."
            )
        await self.capability_worker.speak(msg)

        await self.capability_worker.speak(
            "Say a name to hear their context, say follow-ups to see pending actions, or stop."
        )
        reply = await self.capability_worker.user_response()
        if self._is_exit(reply):
            return

        if any(kw in reply.lower() for kw in ("follow", "pending", "owe")):
            await self._handle_followups()
        else:
            await self._handle_who(data, reply)

    async def _handle_followups(self):
        data = await self._load_memory()
        pending = [
            (p, f)
            for p in data.get("people", [])
            for f in p.get("follow_ups", [])
            if f.get("status") == "pending"
        ]

        if not pending:
            await self.capability_worker.speak("No pending follow-ups — you're all caught up!")
            return

        today = datetime.now().date()

        def overdue_days(item):
            try:
                dl = item[1].get("deadline_date", "")
                if not dl:
                    return 0
                return (today - datetime.strptime(dl, "%Y-%m-%d").date()).days
            except Exception:
                return 0

        pending_sorted = sorted(pending, key=overdue_days, reverse=True)
        top = pending_sorted[:5]

        parts = []
        for i, (person, fup) in enumerate(top):
            days = overdue_days((person, fup))
            if days > 0:
                age_str = f"{days} {'day' if days == 1 else 'days'} overdue"
            else:
                deadline_hint = fup.get("deadline_hint", "")
                age_str = (
                    f"due {deadline_hint}"
                    if deadline_hint and deadline_hint != "no deadline"
                    else "no deadline set"
                )
            parts.append(f"{i + 1}. {fup['commitment']} with {person['name']} — {age_str}")

        await self.capability_worker.speak(
            f"You have {len(pending)} pending "
            f"{'follow-up' if len(pending) == 1 else 'follow-ups'}. "
            + ". ".join(parts) + "."
        )

        await self.capability_worker.speak(
            "Say a number to mark one done, say all done to clear them all, or stop."
        )
        reply = await self.capability_worker.user_response()
        if self._is_exit(reply):
            return

        r = reply.lower()
        now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        if "all done" in r or ("all" in r and "done" in r):
            confirmed = await self.capability_worker.run_confirmation_loop(
                f"Mark all {len(pending)} follow-ups as done?"
            )
            if confirmed:
                for person, fup in pending:
                    fup["status"] = "completed"
                    fup["completed_at"] = now_str
                data["stats"]["total_follow_ups_completed"] = (
                    data["stats"].get("total_follow_ups_completed", 0) + len(pending)
                )
                await self._save_memory(data)
                await self.capability_worker.speak("Done — all follow-ups marked complete.")
        else:
            num_match = re.search(r'\b(\d+)\b', reply)
            if num_match:
                idx = int(num_match.group(1)) - 1
                if 0 <= idx < len(top):
                    person, fup = top[idx]
                    fup["status"] = "completed"
                    fup["completed_at"] = now_str
                    data["stats"]["total_follow_ups_completed"] = (
                        data["stats"].get("total_follow_ups_completed", 0) + 1
                    )
                    await self._save_memory(data)
                    await self.capability_worker.speak(
                        f"Done — '{fup['commitment']}' marked complete."
                    )

    async def _handle_add(self, trigger_text: str):
        name = self._extract_name_from_query(trigger_text)
        if not name:
            await self.capability_worker.speak("Who would you like to add a note about?")
            reply = await self.capability_worker.user_response()
            if self._is_exit(reply):
                return
            name = reply.strip()[:60]

        await self.capability_worker.speak(f"What would you like to note about {name}?")
        note_reply = await self.capability_worker.user_response()
        if self._is_exit(note_reply):
            return

        note_text = note_reply.strip()[:200]
        data = await self._load_memory()
        now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        person = self._find_person(name, data)

        if person is None:
            person = _new_person(name, "unknown")
            data["people"].append(person)
            data["stats"]["total_people_captured"] = (
                data["stats"].get("total_people_captured", 0) + 1
            )

        person.setdefault("context_snippets", []).append({
            "text": note_text,
            "captured_at": now_str,
            "speaker_relation": "direct",
        })
        if len(person["context_snippets"]) > MAX_SNIPPETS_PER_PERSON:
            person["context_snippets"] = person["context_snippets"][-MAX_SNIPPETS_PER_PERSON:]
        person["last_mentioned"] = now_str
        person["mention_count"] = person.get("mention_count", 0) + 1

        await self.capability_worker.speak(
            f"Is there anything you need to follow up with {name} on? Say skip if not."
        )
        fup_reply = await self.capability_worker.user_response()
        if fup_reply and not self._is_exit(fup_reply) and "skip" not in fup_reply.lower():
            person.setdefault("follow_ups", []).append({
                "id": f"fu_{int(datetime.now().timestamp() * 1000)}",
                "commitment": fup_reply.strip()[:200],
                "deadline_hint": "no deadline",
                "deadline_date": _resolve_deadline(""),
                "captured_at": now_str,
                "status": "pending",
                "completed_at": None,
                "nudge_count": 0,
                "last_nudged": None,
            })
            data["stats"]["total_follow_ups_captured"] = (
                data["stats"].get("total_follow_ups_captured", 0) + 1
            )

        await self._save_memory(data)
        await self.capability_worker.speak(f"Got it — noted about {person['name']}.")

    async def _handle_forget(self, data: dict, trigger_text: str):
        name = self._extract_name_from_query(trigger_text)
        if not name:
            await self.capability_worker.speak("Who would you like me to forget?")
            reply = await self.capability_worker.user_response()
            if self._is_exit(reply):
                return
            name = reply.strip()
            if not name or len(name) < 2:
                return

        person = self._find_person(name, data)
        if person is None:
            await self.capability_worker.speak(f"I don't have anyone named {name} on file.")
            return

        confirmed = await self.capability_worker.run_confirmation_loop(
            f"Remove all context about {person['name']}?"
        )
        if confirmed:
            data["people"] = [p for p in data["people"] if p["id"] != person["id"]]
            await self._save_memory(data)
            await self.capability_worker.speak(f"Done — {person['name']} removed.")
        else:
            await self.capability_worker.speak("No problem, keeping everything.")

    async def _handle_clear(self, data: dict):
        total = len(data.get("people", []))
        if total == 0:
            await self.capability_worker.speak("Your social memory is already empty.")
            return

        confirmed = await self.capability_worker.run_confirmation_loop(
            f"Clear all {total} {'person' if total == 1 else 'people'} from your social memory?"
        )
        if confirmed:
            data["people"] = []
            data["stats"] = {
                "total_people_captured": 0,
                "total_follow_ups_captured": 0,
                "total_follow_ups_completed": 0,
            }
            await self._save_memory(data)
            await self.capability_worker.speak("Done — social memory cleared.")
        else:
            await self.capability_worker.speak("Keeping everything.")

    async def _handle_stats(self, data: dict):
        stats = data.get("stats", {})
        people_count = len(data.get("people", []))
        fups_captured = stats.get("total_follow_ups_captured", 0)
        fups_completed = stats.get("total_follow_ups_completed", 0)
        pending = sum(
            1 for p in data.get("people", [])
            for f in p.get("follow_ups", [])
            if f.get("status") == "pending"
        )

        await self.capability_worker.speak(
            f"You have {people_count} "
            f"{'person' if people_count == 1 else 'people'} in social memory. "
            f"{fups_captured} "
            f"{'follow-up' if fups_captured == 1 else 'follow-ups'} tracked total, "
            f"{fups_completed} completed, {pending} still pending."
        )

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    async def _run(self):
        try:
            trigger_text = await self.capability_worker.wait_for_complete_transcription()
            if not trigger_text or not isinstance(trigger_text, str):
                trigger_text = ""

            intent = self._classify_intent(trigger_text)
            self.worker.editor_logging_handler.info(
                f"[SocialMemory] Intent: {intent} | Trigger: {trigger_text[:80]}"
            )

            data = await self._load_memory()

            if intent == "WHO":
                await self._handle_who(data, trigger_text)
            elif intent == "LIST":
                await self._handle_list(data)
            elif intent == "FOLLOWUPS":
                await self._handle_followups()
            elif intent == "ADD":
                await self._handle_add(trigger_text)
            elif intent == "FORGET":
                await self._handle_forget(data, trigger_text)
            elif intent == "CLEAR":
                await self._handle_clear(data)
            elif intent == "STATS":
                await self._handle_stats(data)
            else:
                await self.capability_worker.speak(
                    "I can tell you about someone, list who you've mentioned, "
                    "show pending follow-ups, or add a note. What would you like?"
                )

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SocialMemory] Skill error: {e}")
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
