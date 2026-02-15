import json
import os
import re
from datetime import datetime, timedelta

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# FOOD & WATER LOG
# A voice-powered food and water intake tracker. Log meals and water by voice,
# review today's intake, and track hydration — all persisted across sessions.
# The LLM classifies natural speech into intents so you can say things like
# "I had eggs for breakfast" or "drank 2 glasses of water" naturally.
# =============================================================================

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave"}

LOG_FILE = "oh_food_water_log.json"

CLASSIFY_PROMPT = (
    "You are an intent classifier for a food and water logging assistant. "
    "Classify the user's intent and extract relevant data. "
    "Return ONLY valid JSON with no markdown fences.\n\n"
    "Possible intents:\n"
    '- {"intent": "log_food", "description": "<what they ate, short>"}\n'
    '- {"intent": "log_water", "amount": <number of glasses, default 1>}\n'
    '- {"intent": "read_today", "filter": "all|food|water"}\n'
    '- {"intent": "clear_today"}\n'
    '- {"intent": "read_summary"}\n'
    '- {"intent": "unknown"}\n\n'
    "Rules:\n"
    "- Water means specifically water or hydration.\n"
    "- Coffee, juice, tea, soda count as food, not water.\n"
    "- If the user just says a food item with no verb, treat it as log_food.\n\n"
    "Examples:\n"
    '"I had eggs and toast" -> {"intent": "log_food", "description": "eggs and toast"}\n'
    '"drank 2 glasses of water" -> {"intent": "log_water", "amount": 2}\n'
    '"a glass of water" -> {"intent": "log_water", "amount": 1}\n'
    '"coffee and a bagel" -> {"intent": "log_food", "description": "coffee and a bagel"}\n'
    '"what did I eat today" -> {"intent": "read_today", "filter": "food"}\n'
    '"how much water" -> {"intent": "read_today", "filter": "water"}\n'
    '"read my log" -> {"intent": "read_today", "filter": "all"}\n'
    '"clear today" -> {"intent": "clear_today"}\n'
    '"weekly summary" -> {"intent": "read_summary"}\n'
)


class FoodWaterLogCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    log_data: dict = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self):
        try:
            self.worker.editor_logging_handler.info("[FoodWaterLog] Ability started")

            # Load persistent data
            self.log_data = await self.load_log()

            # Greet — returning user vs first run
            today_entries = self.get_today_entries()
            food_count = sum(1 for e in today_entries if e["type"] == "food")
            water_total = sum(
                e.get("amount", 1) for e in today_entries if e["type"] == "water"
            )

            if today_entries:
                parts = []
                if food_count:
                    parts.append(f"{food_count} meal{'s' if food_count != 1 else ''}")
                if water_total:
                    parts.append(
                        f"{water_total} glass{'es' if water_total != 1 else ''} of water"
                    )
                await self.capability_worker.speak(
                    f"Welcome back! Today you've logged {' and '.join(parts)}. "
                    "What would you like to add?"
                )
            else:
                await self.capability_worker.speak(
                    "Food and water log is open. "
                    "Tell me what you ate or drank, or ask what you've had today."
                )

            idle_count = 0

            while True:
                user_input = await self.capability_worker.user_response()
                normalized = self.normalize_input(user_input or "")

                # Handle empty input with idle detection
                if not normalized:
                    idle_count += 1
                    if idle_count >= 2:
                        await self.capability_worker.speak(
                            "Still here if you need me. Otherwise I'll close the log."
                        )
                        final = await self.capability_worker.user_response()
                        final_norm = self.normalize_input(final or "")
                        if not final_norm or any(
                            w in final_norm for w in EXIT_WORDS
                        ):
                            await self.capability_worker.speak(
                                "Log closed. Stay hydrated!"
                            )
                            break
                        user_input = final
                        normalized = final_norm
                        idle_count = 0
                    else:
                        continue

                idle_count = 0

                # Check exit words BEFORE processing
                if any(word in normalized for word in EXIT_WORDS):
                    await self.capability_worker.speak("Log closed. Stay hydrated!")
                    break

                # Classify intent using LLM
                intent_data = self.classify_intent(normalized)
                intent = intent_data.get("intent", "unknown")

                # If LLM couldn't classify, try our rule-based fallback
                if intent == "unknown":
                    rb = self.fallback_classify(normalized)
                    if rb.get("intent") != "unknown":
                        intent_data = rb
                        intent = rb["intent"]

                self.worker.editor_logging_handler.info(
                    f"[FoodWaterLog] Intent: {intent} | Data: {intent_data}"
                )

                if intent == "log_food":
                    await self.handle_log_food(intent_data)
                elif intent == "log_water":
                    await self.handle_log_water(intent_data)
                elif intent == "read_today":
                    await self.handle_read_today(intent_data)
                elif intent == "clear_today":
                    await self.handle_clear_today()
                elif intent == "read_summary":
                    await self.handle_read_summary()
                else:
                    await self.capability_worker.speak(
                        "I can log food, log water, or read your entries. "
                        "What would you like?"
                    )

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[FoodWaterLog] Unexpected error: {e}"
            )
            await self.capability_worker.speak(
                "Something went wrong. Closing the log."
            )
        finally:
            self.worker.editor_logging_handler.info("[FoodWaterLog] Ability ended")
            self.capability_worker.resume_normal_flow()

    # ------------------------------------------------------------------
    # Intent classification
    # ------------------------------------------------------------------

    def classify_intent(self, user_input):
        """Use the LLM to classify user intent and extract structured data."""
        try:
            raw = self.capability_worker.text_to_text_response(
                f"User said: {user_input}",
                system_prompt=CLASSIFY_PROMPT,
            )
            clean = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(clean)
        except (json.JSONDecodeError, Exception) as e:
            self.worker.editor_logging_handler.error(
                f"[FoodWaterLog] Classification error: {e}"
            )
            return {"intent": "unknown"}

    def normalize_input(self, text: str) -> str:
        """Normalize common STT mis-hearings to improve intent recognition."""
        t = (text or "").lower()
        # Remove punctuation (keep digits and whitespace)
        t = re.sub(r"[^a-z0-9\s]", " ", t)
        # Common mis-hearings
        replacements = [
            ("food look", "food log"),
            ("read my look", "read my log"),
            ("read the look", "read the log"),
            ("read my pack", "read my log"),
            ("read the pack", "read the log"),
            ("low water", "log water"),
        ]
        for a, b in replacements:
            t = t.replace(a, b)
        # Collapse extra spaces
        t = re.sub(r"\s+", " ", t)
        return t

    def fallback_classify(self, text: str) -> dict:
        """Simple rule-based fallback when LLM classification is unknown."""
        lower = (text or "").lower()

        # Clear today's entries
        if "clear" in lower and "today" in lower:
            return {"intent": "clear_today"}

        # Read requests
        if any(p in lower for p in [
            "what did i eat", "what did i have", "read my log", "read my entries", "read back",
            "what did i drink", "show my log", "read the log", "show my food and water", "show food and water"
        ]):
            if any(p in lower for p in ["water", "drink", "hydration"]):
                return {"intent": "read_today", "filter": "water"}
            if any(p in lower for p in ["eat", "food", "meal"]):
                return {"intent": "read_today", "filter": "food"}
            return {"intent": "read_today", "filter": "all"}

        # Log water (detect amount if present)
        if "water" in lower and any(p in lower for p in ["drink", "drank", "drunk", "glass", "glasses", "log", "had"]):
            amount = 1
            m = re.search(r"(\d+)\s+glass", lower)
            if m:
                try:
                    amount = int(m.group(1))
                except Exception:
                    amount = 1
            else:
                # Spelled numbers and 'a glass'
                words = {
                    "one": 1,
                    "two": 2,
                    "three": 3,
                    "four": 4,
                    "five": 5,
                    "six": 6,
                    "seven": 7,
                    "eight": 8,
                    "nine": 9,
                    "ten": 10,
                }
                for w, n in words.items():
                    if re.search(fr"\b{w}\b\s+glass", lower):
                        amount = n
                        break
                if amount == 1 and re.search(r"\ba\s+glass\b", lower):
                    amount = 1
            return {"intent": "log_water", "amount": amount}

        # Log food
        if any(p in lower for p in ["i had", "i ate", "for breakfast", "for lunch", "for dinner"]):
            # Use the raw text as description, lightly cleaned
            desc = lower
            desc = desc.replace("i had", "").replace("i ate", "").strip()
            return {"intent": "log_food", "description": desc or "something"}

        return {"intent": "unknown"}

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def handle_log_food(self, intent_data):
        """Log a food entry and save."""
        description = intent_data.get("description", "something")
        entry = {
            "type": "food",
            "description": description,
            "timestamp": datetime.now().isoformat(),
        }
        self.log_data["entries"].append(entry)
        await self.save_log()

        food_today = sum(
            1 for e in self.get_today_entries() if e["type"] == "food"
        )
        meal_word = "meal" if food_today == 1 else "meals"
        await self.capability_worker.speak(
            f"Logged {description}. That's {food_today} {meal_word} today."
        )

    async def handle_log_water(self, intent_data):
        """Log water intake and save."""
        amount = intent_data.get("amount", 1)
        entry = {
            "type": "water",
            "amount": amount,
            "timestamp": datetime.now().isoformat(),
        }
        self.log_data["entries"].append(entry)
        await self.save_log()

        water_today = sum(
            e.get("amount", 1)
            for e in self.get_today_entries()
            if e["type"] == "water"
        )
        glass_word = "glass" if amount == 1 else "glasses"
        await self.capability_worker.speak(
            f"Logged {amount} {glass_word} of water. "
            f"Total today: {water_today} glasses."
        )

    async def handle_read_today(self, intent_data):
        """Read back today's entries filtered by type."""
        filter_type = intent_data.get("filter", "all")
        today_entries = self.get_today_entries()

        if filter_type == "food":
            entries = [e for e in today_entries if e["type"] == "food"]
            if not entries:
                await self.capability_worker.speak("No food logged today yet.")
                return
            items = ", ".join(e["description"] for e in entries)
            await self.capability_worker.speak(
                f"Today's food: {items}. {len(entries)} entries total."
            )

        elif filter_type == "water":
            water_total = sum(
                e.get("amount", 1)
                for e in today_entries
                if e["type"] == "water"
            )
            if water_total == 0:
                await self.capability_worker.speak("No water logged today yet.")
                return
            await self.capability_worker.speak(
                f"You've had {water_total} glasses of water today."
            )

        else:
            if not today_entries:
                await self.capability_worker.speak(
                    "Nothing logged today yet. Tell me what you ate or drank."
                )
                return
            food_entries = [e for e in today_entries if e["type"] == "food"]
            water_total = sum(
                e.get("amount", 1)
                for e in today_entries
                if e["type"] == "water"
            )
            parts = []
            if food_entries:
                items = ", ".join(e["description"] for e in food_entries)
                parts.append(f"Food: {items}")
            if water_total > 0:
                parts.append(f"Water: {water_total} glasses")
            await self.capability_worker.speak(
                "Today's log. " + ". ".join(parts) + "."
            )

    async def handle_clear_today(self):
        """Clear today's entries after voice confirmation."""
        confirmed = await self.capability_worker.run_confirmation_loop(
            "Clear all of today's entries? Say yes to confirm."
        )
        if confirmed:
            today_str = datetime.now().strftime("%Y-%m-%d")
            self.log_data["entries"] = [
                e
                for e in self.log_data["entries"]
                if not e["timestamp"].startswith(today_str)
            ]
            await self.save_log()
            await self.capability_worker.speak("Today's log has been cleared.")
        else:
            await self.capability_worker.speak("Okay, keeping everything.")

    async def handle_read_summary(self):
        """Read a brief 7-day summary."""
        week_ago = datetime.now() - timedelta(days=7)
        week_entries = [
            e
            for e in self.log_data["entries"]
            if datetime.fromisoformat(e["timestamp"]) >= week_ago
        ]

        if not week_entries:
            await self.capability_worker.speak("No entries in the past 7 days.")
            return

        food_count = sum(1 for e in week_entries if e["type"] == "food")
        water_total = sum(
            e.get("amount", 1) for e in week_entries if e["type"] == "water"
        )
        days_logged = len(
            set(e["timestamp"][:10] for e in week_entries)
        )

        await self.capability_worker.speak(
            f"Past 7 days: {food_count} food entries, "
            f"{water_total} glasses of water, across {days_logged} days."
        )

    # ------------------------------------------------------------------
    # Persistence helpers (delete + write for JSON)
    # ------------------------------------------------------------------

    def get_today_entries(self):
        """Filter entries to today only."""
        today_str = datetime.now().strftime("%Y-%m-%d")
        return [
            e
            for e in self.log_data.get("entries", [])
            if e.get("timestamp", "").startswith(today_str)
        ]

    async def load_log(self):
        """Load persistent log data, or return empty structure on first run."""
        if await self.capability_worker.check_if_file_exists(LOG_FILE, False):
            try:
                raw = await self.capability_worker.read_file(LOG_FILE, False)
                return json.loads(raw)
            except json.JSONDecodeError:
                self.worker.editor_logging_handler.error(
                    "[FoodWaterLog] Corrupt log file, resetting."
                )
                await self.capability_worker.delete_file(LOG_FILE, False)
        return {"entries": []}

    async def save_log(self):
        """Save log data persistently using delete + write pattern for JSON."""
        if await self.capability_worker.check_if_file_exists(LOG_FILE, False):
            await self.capability_worker.delete_file(LOG_FILE, False)
        await self.capability_worker.write_file(
            LOG_FILE, json.dumps(self.log_data), False
        )
