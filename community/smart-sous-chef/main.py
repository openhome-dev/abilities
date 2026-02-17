import json
import re
import urllib.parse
import urllib.request
from typing import ClassVar, Dict, List, Optional

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


<<<<<<< HEAD
API_KEY = "Your API Key here"
=======
API_KEY = "YOUR_API_KEY"
>>>>>>> 1f8be2b (Replace main.py with fully validation-safe version)
BASE_URL = "https://api.spoonacular.com"


class Chefassistantv1Capability(MatchingCapability):

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    active_timers: ClassVar[Dict[str, bool]] = {}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(worker)
        self.worker.session_tasks.create(self.first_function())

    async def first_function(self):
<<<<<<< HEAD
        try:
            await self.capability_worker.speak(
                "Smart Sous Chef ready. What would you like to cook?"
            )

            while True:
                user_input = await self.capability_worker.user_response()
                if not user_input:
                    continue

                text = user_input.lower().strip()

                if self.is_exit(text):
                    await self.capability_worker.speak("Session ended.")
                    break

                recipe = await self.fetch_recipe(text)

                if not recipe:
                    await self.capability_worker.speak(
                        "Recipe not found. Try another."
                    )
                    continue

                await self.run_workflow(recipe)
                break

        finally:
            self.capability_worker.resume_normal_flow()

    async def run_workflow(self, session: dict):
        steps: List[str] = session["steps"]
        ingredients = session.get("ingredients", [])
        current_step = 0

        await self.capability_worker.speak(
            f"Step 1 of {len(steps)}. {steps[0]}"
=======
        await self.capability_worker.speak(
            "Smart Sous Chef ready. What would you like to cook?"
>>>>>>> 1f8be2b (Replace main.py with fully validation-safe version)
        )

        while True:
            user_input = await self.capability_worker.user_response()
            if not user_input:
                continue

            text = user_input.lower().strip()

            if self.is_exit(text):
<<<<<<< HEAD
                await self.capability_worker.speak("Cooking ended.")
                break

            if "next" in text:
                current_step += 1
                if current_step < len(steps):
                    await self.capability_worker.speak(
                        f"Step {current_step + 1} of {len(steps)}. "
                        f"{steps[current_step]}"
                    )
                else:
                    await self.capability_worker.speak(
                        "Recipe complete. Enjoy!"
                    )
                    break
                continue

            if "repeat" in text:
                await self.capability_worker.speak(
                    f"Step {current_step + 1}. "
                    f"{steps[current_step]}"
                )
                continue

            if "ingredients" in text:
                if not ingredients:
                    await self.capability_worker.speak(
                        "Ingredient details unavailable."
                    )
                else:
                    short_list = ", ".join(
                        i["name"] for i in ingredients[:5]
                    )
                    await self.capability_worker.speak(
                        f"You'll need: {short_list}."
                    )
                continue

            if "how much" in text:
                match = re.search(r"how much ([\w\s]+)", text)
                if match:
                    name = match.group(1).strip()
                    found = next(
                        (
                            i for i in ingredients
                            if name in i["name"]
                        ),
                        None,
                    )
                    if found:
                        await self.capability_worker.speak(
                            f"{found['amount']} "
                            f"{found['unit']} "
                            f"{found['name']}."
                        )
                    else:
                        await self.capability_worker.speak(
                            "Not found in this recipe."
                        )
=======
                await self.capability_worker.speak("Session ended.")
                break

            recipe = await self.fetch_recipe(text)

            if not recipe:
                await self.capability_worker.speak(
                    "Recipe not found. Try another."
                )
                continue

            await self.run_workflow(recipe)
            break

        self.capability_worker.resume_normal_flow()

    async def run_workflow(self, session: dict):
        steps: List[str] = session["steps"]
        current_step = 0

        await self.capability_worker.speak(
            f"Step 1 of {len(steps)}. {steps[0]}"
        )

        while True:
            user_input = await self.capability_worker.user_response()
            if not user_input:
                continue

            text = user_input.lower().strip()

            if self.is_exit(text):
                await self.capability_worker.speak("Cooking ended.")
                break

            if "next" in text:
                current_step += 1
                if current_step < len(steps):
                    await self.capability_worker.speak(
                        f"Step {current_step + 1}. "
                        f"{steps[current_step]}"
                    )
                else:
                    await self.capability_worker.speak(
                        "Recipe complete."
                    )
                    break
                continue

            if "repeat" in text:
                await self.capability_worker.speak(
                    f"Step {current_step + 1}. "
                    f"{steps[current_step]}"
                )
>>>>>>> 1f8be2b (Replace main.py with fully validation-safe version)
                continue

            if "timer" in text:
                minutes = self.extract_minutes(text)
                if minutes:
                    await self.start_timer(minutes)
                else:
                    await self.capability_worker.speak(
                        "How many minutes?"
                    )
                continue

            await self.capability_worker.speak(
<<<<<<< HEAD
                "Say next, repeat, ingredients, timer, or stop."
=======
                "Say next, repeat, timer, or stop."
>>>>>>> 1f8be2b (Replace main.py with fully validation-safe version)
            )

    async def fetch_recipe(self, query: str) -> Optional[dict]:
        try:
            params = urllib.parse.urlencode(
<<<<<<< HEAD
                {
                    "query": query,
                    "number": 1,
                    "apiKey": API_KEY,
                }
=======
                {"query": query, "number": 1, "apiKey": API_KEY}
>>>>>>> 1f8be2b (Replace main.py with fully validation-safe version)
            )
            url = f"{BASE_URL}/recipes/complexSearch?{params}"

            with urllib.request.urlopen(url, timeout=10) as response:
                data = json.loads(response.read().decode())

            results = data.get("results", [])
            if not results:
                return None

            recipe_id = results[0]["id"]

            info_url = (
                f"{BASE_URL}/recipes/{recipe_id}/information"
                f"?apiKey={API_KEY}"
            )

            with urllib.request.urlopen(info_url, timeout=10) as response:
                info = json.loads(response.read().decode())
<<<<<<< HEAD

            analyzed = info.get("analyzedInstructions", [])
            steps = []

            if analyzed and analyzed[0].get("steps"):
                steps = [
                    s["step"]
                    for s in analyzed[0]["steps"]
                    if s["step"]
                ]

            if not steps:
                return None

            ingredients = [
                {
                    "name": ing["name"].lower(),
                    "amount": ing.get("amount", ""),
                    "unit": ing.get("unit", ""),
                }
                for ing in info.get(
                    "extendedIngredients", []
                )
            ]

            return {
                "steps": steps,
                "ingredients": ingredients,
            }
=======

            analyzed = info.get("analyzedInstructions", [])
            if not analyzed or not analyzed[0].get("steps"):
                return None

            steps = [
                s["step"]
                for s in analyzed[0]["steps"]
                if s["step"]
            ]

            return {"steps": steps}
>>>>>>> 1f8be2b (Replace main.py with fully validation-safe version)

        except Exception:
            return None

    async def start_timer(self, minutes: int):
        name = f"Timer {len(self.active_timers) + 1}"
        self.active_timers[name] = True
        self.worker.session_tasks.create(
            self.run_timer(name, minutes)
        )
        await self.capability_worker.speak(
            f"{name} set for {minutes} minutes."
        )

    async def run_timer(self, name: str, minutes: int):
<<<<<<< HEAD
        await self.worker.session_tasks.sleep(
            minutes * 60
        )
=======
        await self.worker.session_tasks.sleep(minutes * 60)
>>>>>>> 1f8be2b (Replace main.py with fully validation-safe version)
        if name in self.active_timers:
            await self.capability_worker.speak(
                f"{name} finished."
            )
            del self.active_timers[name]

    def extract_minutes(self, text: str) -> Optional[int]:
<<<<<<< HEAD
        match = re.search(
            r"(\d+)\s*(minute|min)",
            text,
        )
=======
        match = re.search(r"(\d+)\s*(minute|min)", text)
>>>>>>> 1f8be2b (Replace main.py with fully validation-safe version)
        if match:
            return int(match.group(1))
        return None

    def is_exit(self, text: str) -> bool:
        return any(
            word in text
            for word in ["stop", "exit", "quit", "done"]
        )
