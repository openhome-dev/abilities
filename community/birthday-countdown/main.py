import json
import re
from datetime import datetime

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# BIRTHDAY & EVENT COUNTDOWN
# Tracks birthdays, anniversaries, and other recurring events. Persists data
# across sessions. Calculates countdowns, lists upcoming events, and uses the
# LLM to generate gift ideas based on stored notes.
# =============================================================================

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave",
}

EVENTS_FILE = "birthday_events.json"

ADD_KEYWORDS = {"add", "new", "save", "remember", "create", "set"}
CHECK_KEYWORDS = {"check", "list", "upcoming", "next", "when", "how many days"}
REMOVE_KEYWORDS = {"remove", "delete", "forget"}
GIFT_KEYWORDS = {"gift", "present", "idea", "buy", "get for"}

CLASSIFY_PROMPT = (
    "Classify the user's intent for an event countdown app.\n"
    "Return ONLY one of: add, check, remove, gift, exit, unknown\n"
    "Rules:\n"
    "- 'add', 'save', 'remember', 'new birthday' -> add\n"
    "- 'when', 'list', 'upcoming', 'check', 'how many days' -> check\n"
    "- 'remove', 'delete', 'forget' -> remove\n"
    "- 'gift', 'present', 'buy', 'what to get' -> gift\n"
    "- 'stop', 'done', 'bye', 'exit' -> exit\n"
    "Input: {text}"
)

EXTRACT_EVENT_PROMPT = (
    "Extract event details from the user's input. Return ONLY valid JSON "
    "with no markdown fences.\n"
    'Format: {{"name": "<person/event name>", "date": "<MM-DD>", '
    '"type": "<birthday|anniversary|event>", "notes": "<any extra info>"}}\n'
    "If no date given, set date to null. If no notes, set notes to empty string.\n"
    "Examples:\n"
    '"Sarah birthday March 15 she likes hiking" -> '
    '{{"name": "Sarah", "date": "03-15", "type": "birthday", "notes": "likes hiking"}}\n'
    '"Our anniversary is June 1st" -> '
    '{{"name": "Our anniversary", "date": "06-01", "type": "anniversary", "notes": ""}}\n'
)

GIFT_IDEA_PROMPT = (
    "You are a thoughtful gift advisor. The user wants gift ideas for {name}. "
    "Here are notes about them: {notes}. The occasion is a {event_type}. "
    "Suggest 3-4 gift ideas in a conversational tone suitable for voice. "
    "Keep each suggestion to one sentence."
)


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _days_until(date_str: str) -> int:
    today = datetime.now()
    try:
        month, day = date_str.split("-")
        event_this_year = today.replace(month=int(month), day=int(day),
                                        hour=0, minute=0, second=0, microsecond=0)
        if event_this_year.date() < today.date():
            event_this_year = event_this_year.replace(year=today.year + 1)
        return (event_this_year.date() - today.date()).days
    except (ValueError, TypeError):
        return 999


class BirthdayCountdownCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    events: list = None

    # Do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.events = []
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            self.worker.editor_logging_handler.info(
                "[BirthdayCountdown] Ability started"
            )

            self.events = await self._load_events()

            if not self.events:
                await self.capability_worker.speak(
                    "Welcome to Birthday and Event Countdown! "
                    "You don't have any events saved yet. "
                    "Want to add one? Just tell me the name, date, and any notes."
                )
            else:
                upcoming = self._get_upcoming(3)
                if upcoming:
                    summary = ", ".join(
                        f"{e['name']} in {_days_until(e['date'])} days"
                        for e in upcoming
                    )
                    await self.capability_worker.speak(
                        f"Welcome back! Your upcoming events: {summary}. "
                        "You can add, check, remove events, or ask for gift ideas."
                    )
                else:
                    await self.capability_worker.speak(
                        "Welcome back to Event Countdown! "
                        "What would you like to do?"
                    )

            idle_count = 0

            for _ in range(20):
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    idle_count += 1
                    if idle_count >= 2:
                        await self.capability_worker.speak(
                            "Closing Event Countdown. See you next time!"
                        )
                        break
                    await self.capability_worker.speak(
                        "I'm still here. What would you like to do?"
                    )
                    continue

                idle_count = 0

                if any(w in user_input.lower() for w in EXIT_WORDS):
                    await self.capability_worker.speak(
                        "Goodbye! I'll keep track of your events."
                    )
                    break

                intent = self._classify_intent(user_input)

                if intent == "add":
                    await self._handle_add(user_input)
                elif intent == "check":
                    await self._handle_check()
                elif intent == "remove":
                    await self._handle_remove(user_input)
                elif intent == "gift":
                    await self._handle_gift(user_input)
                elif intent == "exit":
                    await self.capability_worker.speak(
                        "Goodbye! I'll keep track of your events."
                    )
                    break
                else:
                    await self.capability_worker.speak(
                        "I can add events, check upcoming ones, remove events, "
                        "or suggest gift ideas. What would you like?"
                    )

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[BirthdayCountdown] Unexpected error: {e}"
            )
            await self.capability_worker.speak(
                "Something went wrong. Closing Event Countdown."
            )
        finally:
            self.worker.editor_logging_handler.info(
                "[BirthdayCountdown] Ability ended"
            )
            self.capability_worker.resume_normal_flow()

    def _classify_intent(self, text: str) -> str:
        lower = text.lower()

        if any(w in lower for w in EXIT_WORDS):
            return "exit"
        if any(w in lower for w in GIFT_KEYWORDS):
            return "gift"
        if any(w in lower for w in REMOVE_KEYWORDS):
            return "remove"
        if any(w in lower for w in CHECK_KEYWORDS):
            return "check"
        if any(w in lower for w in ADD_KEYWORDS):
            return "add"

        try:
            result = self.capability_worker.text_to_text_response(
                CLASSIFY_PROMPT.format(text=text)
            )
            intent = result.strip().lower().rstrip(".")
            if intent in ("add", "check", "remove", "gift", "exit"):
                return intent
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[BirthdayCountdown] Classification error: {e}"
            )

        return "unknown"

    async def _handle_add(self, user_input: str):
        try:
            raw = self.capability_worker.text_to_text_response(
                f"User said: {user_input}",
                system_prompt=EXTRACT_EVENT_PROMPT,
            )
            event = json.loads(_strip_json_fences(raw))
        except (json.JSONDecodeError, Exception) as e:
            self.worker.editor_logging_handler.error(
                f"[BirthdayCountdown] Event extraction error: {e}"
            )
            event = {"name": None, "date": None, "type": "event", "notes": ""}

        if not event.get("name"):
            name_input = await self.capability_worker.run_io_loop(
                "What's the name of the person or event?"
            )
            if not name_input or any(w in name_input.lower() for w in EXIT_WORDS):
                return
            event["name"] = name_input.strip()

        if not event.get("date"):
            date_input = await self.capability_worker.run_io_loop(
                f"When is {event['name']}'s event? Give me the month and day."
            )
            if not date_input or any(w in date_input.lower() for w in EXIT_WORDS):
                return
            parsed_date = self._parse_date(date_input)
            if not parsed_date:
                await self.capability_worker.speak(
                    "I couldn't understand that date. Try something like March 15."
                )
                return
            event["date"] = parsed_date

        if not event.get("type"):
            event["type"] = "event"
        if not event.get("notes"):
            event["notes"] = ""

        self.events.append(event)
        await self._save_events()

        days = _days_until(event["date"])
        await self.capability_worker.speak(
            f"Saved! {event['name']}'s {event['type']} is in {days} days."
        )

    async def _handle_check(self):
        if not self.events:
            await self.capability_worker.speak(
                "You don't have any events saved. Want to add one?"
            )
            return

        upcoming = self._get_upcoming(5)
        if not upcoming:
            await self.capability_worker.speak(
                "No upcoming events found."
            )
            return

        parts = []
        for e in upcoming:
            days = _days_until(e["date"])
            if days == 0:
                parts.append(f"{e['name']}'s {e['type']} is today!")
            elif days == 1:
                parts.append(f"{e['name']}'s {e['type']} is tomorrow!")
            else:
                parts.append(f"{e['name']}'s {e['type']} is in {days} days")

        await self.capability_worker.speak(
            f"Here are your upcoming events: {'. '.join(parts)}."
        )

    async def _handle_remove(self, user_input: str):
        if not self.events:
            await self.capability_worker.speak("You don't have any events to remove.")
            return

        name_to_remove = self._extract_name(user_input)
        if not name_to_remove:
            names = ", ".join(e["name"] for e in self.events)
            name_input = await self.capability_worker.run_io_loop(
                f"Which event should I remove? You have: {names}"
            )
            if not name_input or any(w in name_input.lower() for w in EXIT_WORDS):
                return
            name_to_remove = name_input.strip()

        match = None
        for e in self.events:
            if e["name"].lower() == name_to_remove.lower():
                match = e
                break

        if not match:
            for e in self.events:
                if name_to_remove.lower() in e["name"].lower():
                    match = e
                    break

        if not match:
            await self.capability_worker.speak(
                f"I couldn't find an event for {name_to_remove}."
            )
            return

        confirmed = await self.capability_worker.run_confirmation_loop(
            f"Remove {match['name']}'s {match['type']}? Say yes to confirm."
        )

        if confirmed:
            self.events.remove(match)
            await self._save_events()
            await self.capability_worker.speak(
                f"Removed {match['name']}'s {match['type']}."
            )
        else:
            await self.capability_worker.speak("Okay, keeping it.")

    async def _handle_gift(self, user_input: str):
        name = self._extract_name(user_input)
        if not name:
            if len(self.events) == 1:
                name = self.events[0]["name"]
            else:
                names = ", ".join(e["name"] for e in self.events)
                name_input = await self.capability_worker.run_io_loop(
                    f"Who do you want gift ideas for? You have: {names}"
                )
                if not name_input or any(
                    w in name_input.lower() for w in EXIT_WORDS
                ):
                    return
                name = name_input.strip()

        match = None
        for e in self.events:
            if name.lower() in e["name"].lower():
                match = e
                break

        notes = match.get("notes", "") if match else ""
        event_type = match.get("type", "event") if match else "event"

        try:
            response = self.capability_worker.text_to_text_response(
                f"Suggest gift ideas for {name}.",
                system_prompt=GIFT_IDEA_PROMPT.format(
                    name=name, notes=notes or "no specific notes",
                    event_type=event_type,
                ),
            )
            await self.capability_worker.speak(response)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[BirthdayCountdown] Gift ideas error: {e}"
            )
            await self.capability_worker.speak(
                "I had trouble coming up with ideas. Try again?"
            )

    def _get_upcoming(self, count: int) -> list:
        sorted_events = sorted(self.events, key=lambda e: _days_until(e.get("date", "12-31")))
        return sorted_events[:count]

    def _extract_name(self, text: str) -> str:
        for e in self.events:
            if e["name"].lower() in text.lower():
                return e["name"]
        return ""

    def _parse_date(self, text: str) -> str:
        try:
            result = self.capability_worker.text_to_text_response(
                f"Extract the month and day from this text and return in MM-DD format. "
                f"Return ONLY the date string like 03-15 or 12-25. Input: {text}"
            )
            cleaned = result.strip()
            if re.match(r"^\d{2}-\d{2}$", cleaned):
                return cleaned
        except Exception:
            pass
        return None

    async def _load_events(self) -> list:
        exists = await self.capability_worker.check_if_file_exists(
            EVENTS_FILE, False
        )
        if exists:
            try:
                raw = await self.capability_worker.read_file(EVENTS_FILE, False)
                data = json.loads(raw)
                if isinstance(data, list):
                    return data
            except (json.JSONDecodeError, Exception) as e:
                self.worker.editor_logging_handler.error(
                    f"[BirthdayCountdown] Corrupt file, resetting: {e}"
                )
                await self.capability_worker.delete_file(EVENTS_FILE, False)
        return []

    async def _save_events(self):
        if await self.capability_worker.check_if_file_exists(EVENTS_FILE, False):
            await self.capability_worker.delete_file(EVENTS_FILE, False)
        await self.capability_worker.write_file(
            EVENTS_FILE, json.dumps(self.events), False
        )
