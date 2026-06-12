import json
import re
from datetime import datetime

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# ON THIS DAY IN HISTORY
# Tells the user notable historical events for a calendar date using
# Wikipedia's free "On this day" feed (no API key). Defaults to today and
# accepts any spoken date ("June eleventh", "Christmas", "March third").
# =============================================================================

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave",
}

ONTHISDAY_URL = (
    "https://en.wikipedia.org/api/rest_v1/feed/onthisday/selected"
)

# Wikimedia asks every client to send a descriptive User-Agent.
HEADERS = {
    "User-Agent": (
        "OpenHome-OnThisDay-Ability/1.0 "
        "(https://github.com/openhome-dev/abilities)"
    ),
    "Accept": "application/json",
}

MONTHS = [
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
]

DATE_PROMPT = (
    "Extract the month and day from the user's text and return ONLY a date "
    "in MM-DD format (zero-padded, no year), nothing else. If they mean "
    "today or are unclear, return the single word: today.\n"
    "Examples:\n"
    "'what happened today' -> today\n"
    "'June 11th' -> 06-11\n"
    "'tell me about Christmas' -> 12-25\n"
    "'March 3' -> 03-03\n"
    "Input: {text}"
)

SUMMARIZE_PROMPT = (
    "You are a warm, concise history narrator for a voice assistant. Given a "
    "list of events that happened on a calendar date, pick the 3 or 4 most "
    "notable and varied (don't cluster on one topic). For each, say the year "
    "and what happened in one short spoken sentence. Open with the date, keep "
    "the whole reply under about six sentences, and end with a light hook "
    "inviting another date. Plain spoken English, no lists or markdown."
)


class OnThisDayCapability(MatchingCapability):
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
                "[OnThisDay] Ability started"
            )
            await self.capability_worker.speak(
                "I can tell you what happened on this day in history. "
                "Say a date like June eleventh, or just say today."
            )

            while True:
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    await self.capability_worker.speak(
                        "I didn't catch that. Which date should I look up?"
                    )
                    continue

                words = set(re.findall(r"[a-z]+", user_input.lower()))
                if words & EXIT_WORDS:
                    await self.capability_worker.speak("Goodbye!")
                    break

                month, day, label = self._resolve_date(user_input)
                await self.capability_worker.speak(
                    f"Looking up what happened on {label}."
                )

                events = self._fetch_events(month, day)

                if not events:
                    await self.capability_worker.speak(
                        f"I couldn't pull up history for {label} right now. "
                        "Try another date, or say done to exit."
                    )
                    continue

                summary = self._summarize(events, label)
                await self.capability_worker.speak(summary)
                await self.capability_worker.speak(
                    "Want another date, or say done to exit?"
                )

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[OnThisDay] Unexpected error: {e}"
            )
            await self.capability_worker.speak(
                "Something went wrong. Closing the history guide."
            )
        finally:
            self.worker.editor_logging_handler.info(
                "[OnThisDay] Ability ended"
            )
            self.capability_worker.resume_normal_flow()

    def _resolve_date(self, user_input: str):
        """Return (month, day, spoken_label), defaulting to today on doubt."""
        now = datetime.now()
        tokens = set(re.findall(r"[a-z]+", user_input.lower()))
        if "today" in tokens or "tonight" in tokens:
            return now.month, now.day, "this day"
        try:
            result = self.capability_worker.text_to_text_response(
                DATE_PROMPT.format(text=user_input)
            ).strip().lower()
            if "today" not in result:
                # Take the last two numbers so a stray year prefix
                # ("2026-06-11") or trailing punctuation still parses.
                nums = re.findall(r"\d+", result)
                if len(nums) >= 2:
                    month, day = int(nums[-2]), int(nums[-1])
                    if 1 <= month <= 12 and 1 <= day <= 31:
                        return month, day, f"{MONTHS[month - 1]} {day}"
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[OnThisDay] Date parse error: {e}"
            )
        return now.month, now.day, "this day"

    def _fetch_events(self, month: int, day: int):
        try:
            resp = requests.get(
                f"{ONTHISDAY_URL}/{month:02d}/{day:02d}",
                headers=HEADERS,
                timeout=6,
            )
            if resp.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"[OnThisDay] Wikipedia API returned {resp.status_code}"
                )
                return None
            selected = resp.json().get("selected", [])
            cleaned = []
            for event in selected:
                text = (event.get("text") or "").strip()
                year = event.get("year")
                if text and year is not None:
                    cleaned.append({"year": year, "text": text})
            return cleaned or None
        except requests.exceptions.Timeout:
            self.worker.editor_logging_handler.error(
                "[OnThisDay] Wikipedia API timeout"
            )
            return None
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[OnThisDay] Wikipedia API error: {e}"
            )
            return None

    def _summarize(self, events: list, label: str) -> str:
        payload = json.dumps(
            {"date": label, "events": events[:12]}, ensure_ascii=False
        )
        try:
            return self.capability_worker.text_to_text_response(
                payload, system_prompt=SUMMARIZE_PROMPT
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[OnThisDay] Summary error: {e}"
            )
            event = events[0]
            return f"On {label} in {event['year']}, {event['text']}"
