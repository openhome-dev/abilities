import json
import re
import uuid
from datetime import datetime

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# PLANT CARE REMINDER
# Tracks plants, watering schedules, and fertilizing. Persists data across
# sessions. Uses LLM for species-specific care tips and automatic watering
# interval suggestions. Mirrors the pet-care-assistant pattern.
# =============================================================================

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave",
    "that's all", "no thanks", "i'm done", "i'm good",
}

PLANT_DATA_FILE = "plant_care_data.json"

ADD_KEYWORDS = {"add", "new", "got", "bought", "planted"}
WATER_KEYWORDS = {"water", "watered", "irrigate"}
CHECK_KEYWORDS = {"check", "status", "need", "overdue", "what plants", "list"}
TIPS_KEYWORDS = {"tips", "care", "how do i", "advice", "help with"}
REMOVE_KEYWORDS = {"remove", "delete", "get rid"}

CLASSIFY_PROMPT = (
    "Classify this plant care request. Return ONLY one of: "
    "add, water, check, tips, remove, exit, unknown\n"
    "Rules:\n"
    "- 'add', 'new plant', 'got a plant', 'bought' -> add\n"
    "- 'watered', 'water', 'just watered' -> water\n"
    "- 'check', 'status', 'need watering', 'overdue', 'list' -> check\n"
    "- 'tips', 'care for', 'how do I', 'advice' -> tips\n"
    "- 'remove', 'delete', 'died', 'get rid of' -> remove\n"
    "- 'stop', 'done', 'bye' -> exit\n"
    "Input: {text}"
)

EXTRACT_PLANT_PROMPT = (
    "Extract plant details from the user's input. Return ONLY valid JSON "
    "with no markdown fences.\n"
    'Format: {{"name": "<common name>", "species": "<species if mentioned>", '
    '"location": "<where in home>"}}\n'
    "If not mentioned, set to empty string.\n"
    "Examples:\n"
    '"I got a new monstera for the living room" -> '
    '{{"name": "Monstera", "species": "Monstera deliciosa", "location": "living room"}}\n'
    '"Added a succulent to my desk" -> '
    '{{"name": "Succulent", "species": "", "location": "desk"}}\n'
)

WATER_INTERVAL_PROMPT = (
    "For a {species} plant, what is the recommended watering interval in days? "
    "Return ONLY a single number. Common intervals: succulents 10-14, "
    "tropical plants 7-10, herbs 2-3, cacti 14-21, ferns 3-5. "
    "If unsure, return 7."
)

CARE_TIPS_PROMPT = (
    "You are a plant care expert. Give concise, practical care tips for a "
    "{species} plant. Cover watering, light, humidity, and any common issues. "
    "Keep it to 3-4 sentences for voice output."
)


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


class PlantCareReminderCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    #{{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.plant_data = {"plants": []}
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            self.worker.editor_logging_handler.info(
                "[PlantCare] Ability started"
            )

            self.plant_data = await self._load_data()
            plants = self.plant_data.get("plants", [])

            if not plants:
                await self.capability_worker.speak(
                    "Welcome to Plant Care! You don't have any plants tracked yet. "
                    "Tell me about a plant to get started, like "
                    "'I got a new monstera for the living room'."
                )
            else:
                overdue = self._get_overdue_plants()
                if overdue:
                    names = ", ".join(p["name"] for p in overdue)
                    await self.capability_worker.speak(
                        f"Welcome back! These plants need watering: {names}. "
                        "You can also add plants, check status, or get care tips."
                    )
                else:
                    await self.capability_worker.speak(
                        f"Welcome back! All {len(plants)} plants are on schedule. "
                        "What would you like to do?"
                    )

            idle_count = 0

            for _ in range(20):
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    idle_count += 1
                    if idle_count >= 2:
                        await self.capability_worker.speak(
                            "Closing Plant Care. Your plants will thank you!"
                        )
                        break
                    await self.capability_worker.speak(
                        "I'm here. What would you like to do with your plants?"
                    )
                    continue

                idle_count = 0

                if any(w in user_input.lower() for w in EXIT_WORDS):
                    await self.capability_worker.speak(
                        "Happy gardening! See you next time."
                    )
                    break

                intent = self._classify_intent(user_input)

                if intent == "add":
                    await self._handle_add(user_input)
                elif intent == "water":
                    await self._handle_water(user_input)
                elif intent == "check":
                    await self._handle_check()
                elif intent == "tips":
                    await self._handle_tips(user_input)
                elif intent == "remove":
                    await self._handle_remove(user_input)
                elif intent == "exit":
                    await self.capability_worker.speak(
                        "Happy gardening! See you next time."
                    )
                    break
                else:
                    await self.capability_worker.speak(
                        "I can add plants, log watering, check status, "
                        "give care tips, or remove plants. What would you like?"
                    )

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PlantCare] Unexpected error: {e}"
            )
            await self.capability_worker.speak(
                "Something went wrong. Closing Plant Care."
            )
        finally:
            self.worker.editor_logging_handler.info(
                "[PlantCare] Ability ended"
            )
            self.capability_worker.resume_normal_flow()

    def _classify_intent(self, text: str) -> str:
        lower = text.lower()

        if any(w in lower for w in EXIT_WORDS):
            return "exit"
        if any(w in lower for w in REMOVE_KEYWORDS):
            return "remove"
        if any(w in lower for w in TIPS_KEYWORDS):
            return "tips"
        if any(w in lower for w in WATER_KEYWORDS):
            return "water"
        if any(w in lower for w in CHECK_KEYWORDS):
            return "check"
        if any(w in lower for w in ADD_KEYWORDS):
            return "add"

        try:
            result = self.capability_worker.text_to_text_response(
                CLASSIFY_PROMPT.format(text=text)
            )
            intent = result.strip().lower().rstrip(".")
            if intent in ("add", "water", "check", "tips", "remove", "exit"):
                return intent
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PlantCare] Classification error: {e}"
            )

        return "unknown"

    async def _handle_add(self, user_input: str):
        try:
            raw = self.capability_worker.text_to_text_response(
                f"User said: {user_input}",
                system_prompt=EXTRACT_PLANT_PROMPT,
            )
            details = json.loads(_strip_json_fences(raw))
        except (json.JSONDecodeError, Exception) as e:
            self.worker.editor_logging_handler.error(
                f"[PlantCare] Plant extraction error: {e}"
            )
            details = {}

        name = details.get("name", "")
        species = details.get("species", "")
        location = details.get("location", "")

        if not name:
            name_input = await self.capability_worker.run_io_loop(
                "What's the plant called?"
            )
            if not name_input or any(
                w in name_input.lower() for w in EXIT_WORDS
            ):
                return
            name = name_input.strip()

        if not species:
            species = name

        water_interval = self._get_water_interval(species)

        plant = {
            "id": str(uuid.uuid4()),
            "name": name,
            "species": species,
            "location": location,
            "last_watered": datetime.now().strftime("%Y-%m-%d"),
            "water_interval_days": water_interval,
            "last_fertilized": "",
            "notes": "",
        }

        self.plant_data.setdefault("plants", []).append(plant)
        await self._save_data()

        await self.capability_worker.speak(
            f"Added {name}! I'll remind you to water it every "
            f"{water_interval} days. "
            f"{'It is in the ' + location + '.' if location else ''}"
        )

    async def _handle_water(self, user_input: str):
        plants = self.plant_data.get("plants", [])
        if not plants:
            await self.capability_worker.speak(
                "You don't have any plants tracked yet. Add one first!"
            )
            return

        plant = self._find_plant_in_text(user_input)

        if not plant and len(plants) == 1:
            plant = plants[0]
        elif not plant:
            names = ", ".join(p["name"] for p in plants)
            name_input = await self.capability_worker.run_io_loop(
                f"Which plant did you water? You have: {names}"
            )
            if not name_input or any(
                w in name_input.lower() for w in EXIT_WORDS
            ):
                return
            plant = self._find_plant_in_text(name_input)

        if not plant:
            await self.capability_worker.speak(
                "I couldn't find that plant. Check your plant list."
            )
            return

        plant["last_watered"] = datetime.now().strftime("%Y-%m-%d")
        await self._save_data()

        await self.capability_worker.speak(
            f"Got it! Marked {plant['name']} as watered today. "
            f"Next watering in about {plant['water_interval_days']} days."
        )

    async def _handle_check(self):
        plants = self.plant_data.get("plants", [])
        if not plants:
            await self.capability_worker.speak(
                "You don't have any plants tracked yet."
            )
            return

        overdue = self._get_overdue_plants()
        ok_plants = [p for p in plants if p not in overdue]

        parts = []
        if overdue:
            names = ", ".join(p["name"] for p in overdue)
            parts.append(f"Need watering now: {names}")
        if ok_plants:
            for p in ok_plants:
                days_left = self._days_until_water(p)
                parts.append(f"{p['name']}: water in {days_left} days")

        await self.capability_worker.speak(". ".join(parts) + ".")

    async def _handle_tips(self, user_input: str):
        plant = self._find_plant_in_text(user_input)
        plants = self.plant_data.get("plants", [])

        if not plant and len(plants) == 1:
            plant = plants[0]
        elif not plant:
            species = self._extract_species_from_text(user_input)
            if species:
                try:
                    response = self.capability_worker.text_to_text_response(
                        f"Give care tips for {species}.",
                        system_prompt=CARE_TIPS_PROMPT.format(species=species),
                    )
                    await self.capability_worker.speak(response)
                    return
                except Exception as e:
                    self.worker.editor_logging_handler.error(
                        f"[PlantCare] Tips error: {e}"
                    )
                    await self.capability_worker.speak(
                        "I had trouble getting care tips."
                    )
                    return

        if not plant:
            name_input = await self.capability_worker.run_io_loop(
                "Which plant do you want care tips for?"
            )
            if not name_input or any(
                w in name_input.lower() for w in EXIT_WORDS
            ):
                return
            plant = self._find_plant_in_text(name_input)

        species = plant["species"] if plant else user_input.strip()

        try:
            response = self.capability_worker.text_to_text_response(
                f"Give care tips for {species}.",
                system_prompt=CARE_TIPS_PROMPT.format(species=species),
            )
            await self.capability_worker.speak(response)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PlantCare] Tips error: {e}"
            )
            await self.capability_worker.speak(
                "I had trouble getting care tips. Try again?"
            )

    async def _handle_remove(self, user_input: str):
        plants = self.plant_data.get("plants", [])
        if not plants:
            await self.capability_worker.speak("You don't have any plants to remove.")
            return

        plant = self._find_plant_in_text(user_input)
        if not plant:
            names = ", ".join(p["name"] for p in plants)
            name_input = await self.capability_worker.run_io_loop(
                f"Which plant should I remove? You have: {names}"
            )
            if not name_input or any(
                w in name_input.lower() for w in EXIT_WORDS
            ):
                return
            plant = self._find_plant_in_text(name_input)

        if not plant:
            await self.capability_worker.speak("I couldn't find that plant.")
            return

        confirmed = await self.capability_worker.run_confirmation_loop(
            f"Remove {plant['name']} from your plant list? Say yes to confirm."
        )

        if confirmed:
            self.plant_data["plants"] = [
                p for p in plants if p["id"] != plant["id"]
            ]
            await self._save_data()
            await self.capability_worker.speak(f"Removed {plant['name']}.")
        else:
            await self.capability_worker.speak(f"Okay, keeping {plant['name']}.")

    def _find_plant_in_text(self, text: str) -> dict:
        lower = text.lower()
        for p in self.plant_data.get("plants", []):
            if p["name"].lower() in lower:
                return p
        for p in self.plant_data.get("plants", []):
            if p["species"].lower() in lower:
                return p
        return None

    def _extract_species_from_text(self, text: str) -> str:
        try:
            result = self.capability_worker.text_to_text_response(
                f"Extract the plant name or species from this text. "
                f"Return ONLY the plant name, nothing else. Input: {text}"
            )
            cleaned = result.strip().strip('"').strip("'")
            if cleaned and len(cleaned) < 100:
                return cleaned
        except Exception:
            pass
        return ""

    def _get_water_interval(self, species: str) -> int:
        try:
            result = self.capability_worker.text_to_text_response(
                WATER_INTERVAL_PROMPT.format(species=species)
            )
            val = int(re.search(r"\d+", result.strip()).group())
            if 1 <= val <= 60:
                return val
        except (ValueError, AttributeError, Exception):
            pass
        return 7

    def _get_overdue_plants(self) -> list:
        overdue = []
        datetime.now()
        for p in self.plant_data.get("plants", []):
            if self._days_until_water(p) <= 0:
                overdue.append(p)
        return overdue

    def _days_until_water(self, plant: dict) -> int:
        try:
            last = datetime.strptime(plant["last_watered"], "%Y-%m-%d")
            interval = plant.get("water_interval_days", 7)
            next_water = last.toordinal() + interval
            today = datetime.now().toordinal()
            return next_water - today
        except (ValueError, KeyError):
            return 0

    async def _load_data(self) -> dict:
        exists = await self.capability_worker.check_if_file_exists(
            PLANT_DATA_FILE, False
        )
        if exists:
            try:
                raw = await self.capability_worker.read_file(
                    PLANT_DATA_FILE, False
                )
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, Exception) as e:
                self.worker.editor_logging_handler.error(
                    f"[PlantCare] Corrupt file, resetting: {e}"
                )
                await self.capability_worker.delete_file(PLANT_DATA_FILE, False)
        return {"plants": []}

    async def _save_data(self):
        if await self.capability_worker.check_if_file_exists(
            PLANT_DATA_FILE, False
        ):
            await self.capability_worker.delete_file(PLANT_DATA_FILE, False)
        await self.capability_worker.write_file(
            PLANT_DATA_FILE, json.dumps(self.plant_data), False
        )
