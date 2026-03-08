import json
import os
import re
from typing import ClassVar, Dict, List, Optional

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

API_KEY = "your api key here"
BASE_URL = "https://api.spoonacular.com"


class TestingPrAbilitiesCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    active_timers: ClassVar[Dict[str, bool]] = {}

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")) as file:
            data = json.load(file)

        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(worker)
        self.worker.session_tasks.create(self.first_function())

    async def first_function(self):
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
                "Say next, repeat, timer, or stop."
            )

    async def fetch_recipe(self, query: str) -> Optional[dict]:
        try:
            # Search for recipe
            response = requests.get(
                f"{BASE_URL}/recipes/complexSearch",
                params={"query": query, "number": 1, "apiKey": API_KEY},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not results:
                return None

            recipe_id = results[0]["id"]

            # Fetch full recipe info
            info_response = requests.get(
                f"{BASE_URL}/recipes/{recipe_id}/information",
                params={"apiKey": API_KEY},
                timeout=10,
            )
            info_response.raise_for_status()
            info = info_response.json()

            analyzed = info.get("analyzedInstructions", [])
            if not analyzed or not analyzed[0].get("steps"):
                return None

            steps = [
                s["step"]
                for s in analyzed[0]["steps"]
                if s["step"]
            ]

            return {"steps": steps}

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
        await self.worker.session_tasks.sleep(minutes * 60)
        if name in self.active_timers:
            await self.capability_worker.speak(
                f"{name} finished."
            )
            del self.active_timers[name]

    def extract_minutes(self, text: str) -> Optional[int]:
        match = re.search(r"(\d+)\s*(minute|min)", text)
        if match:
            return int(match.group(1))
        return None

    def is_exit(self, text: str) -> bool:
        return any(
            word in text
            for word in ["stop", "exit", "quit", "done"]
        )
