import json
import os
import re
import requests
import asyncio
import time
from typing import Optional, ClassVar, Dict, List

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

API_KEY = "18267ea57046473b9f03795627694281"
BASE_URL = "https://api.spoonacular.com"
SESSION_FILE = "smart_sous_chef_session.json"


class Chefassistantv1Capability(MatchingCapability):

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    active_timers: ClassVar[Dict[str, Dict]] = {}

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
        self.capability_worker = CapabilityWorker(worker)
        self.worker.session_tasks.create(self.first_function())

    async def first_function(self):
        try:
            session = await self.load_session()

            if session:
                resume = await self.capability_worker.run_confirmation_loop(
                    f"You were cooking {session['recipe_name']} at step {session['current_step'] + 1}. Resume?"
                )
                if resume:
                    await self.run_workflow(session)
                    return
                else:
                    await self.clear_session()

            await self.capability_worker.speak(
                "Smart Sous Chef ready. What would you like to cook?"
            )

            while True:
                user_input = await self.capability_worker.user_response()
                if not user_input:
                    continue

                user_input_lower = user_input.lower()

                if self.is_exit(user_input_lower):
                    await self.capability_worker.speak("Session ended. Goodbye!")
                    break

                recipe_query = self.clean_recipe_input(user_input_lower)

                if not recipe_query:
                    await self.capability_worker.speak("Please tell me the recipe name.")
                    continue

                recipe_data = await self.fetch_recipe(recipe_query)

                if not recipe_data:
                    await self.capability_worker.speak(f"Sorry, couldn't find a good match for '{recipe_query}'. Try another?")
                    continue

                await self.save_session(recipe_data)
                await self.run_workflow(recipe_data)
                break

        except Exception as e:
            print("System Error:", str(e))
            await self.capability_worker.speak("Oops, something went wrong. Let's try again.")
        finally:
            self.capability_worker.resume_normal_flow()

    async def run_workflow(self, session: dict):
        steps = session["steps"]
        current_step = session["current_step"]
        ingredients = session.get("ingredients", [])  # list of dicts {name, amount, unit}

        await self.capability_worker.speak(
            f"Step {current_step + 1} of {len(steps)}: {steps[current_step]}"
        )

        while True:
            user_input = await self.capability_worker.user_response()
            if not user_input:
                continue

            user_input_lower = user_input.lower().strip()

            if self.is_exit(user_input_lower):
                await self.clear_session()
                await self.capability_worker.speak("Session ended. Goodbye!")
                break

            if "next" in user_input_lower:
                if current_step < len(steps) - 1:
                    current_step += 1
                    session["current_step"] = current_step
                    await self.save_session(session)
                    await self.capability_worker.speak(
                        f"Step {current_step + 1} of {len(steps)}: {steps[current_step]}"
                    )
                else:
                    await self.capability_worker.speak("Recipe complete! Enjoy your meal.")
                    await self.clear_session()
                    break
                continue

            if "repeat" in user_input_lower or "what step" in user_input_lower:
                await self.capability_worker.speak(
                    f"Step {current_step + 1} of {len(steps)}: {steps[current_step]}"
                )
                continue

            if any(word in user_input_lower for word in ["ingredients", "what are the ingredients"]):
                if not ingredients:
                    await self.capability_worker.speak("No ingredient details available for this recipe.")
                else:
                    ing_list = ", ".join([f"{i['amount']} {i['unit']} {i['name']}" for i in ingredients if i['amount'] and i['unit']])
                    await self.capability_worker.speak(f"You'll need: {ing_list or 'details not available'}.")
                continue

            if "how much" in user_input_lower:
                # Simple parse: "how much garlic?" → search name
                match = re.search(r"how much ([\w\s]+)\??", user_input_lower)
                if match:
                    ing_name = match.group(1).strip()
                    found = next((i for i in ingredients if ing_name in i['name'].lower()), None)
                    if found:
                        await self.capability_worker.speak(f"{found['amount']} {found['unit']} of {found['name']}.")
                    else:
                        await self.capability_worker.speak(f"I don't have details for {ing_name} in this recipe.")
                continue

            if "timer" in user_input_lower or "set timer" in user_input_lower:
                minutes = self.extract_minutes(user_input_lower)
                if minutes:
                    await self.start_timer(minutes)
                else:
                    await self.capability_worker.speak("For how many minutes?")
                continue

            # Basic recipe by ingredients trigger
            if "what can i cook with" in user_input_lower or "what can i make with" in user_input_lower:
                # Extract after "with "
                parts = re.split(r"(?:with|using)\s+", user_input_lower, maxsplit=1)
                if len(parts) > 1:
                    ings = parts[1].replace(" and ", ",").replace(" ", ",")
                    await self.capability_worker.speak("Searching recipes with those ingredients... One moment.")
                    # TODO: Implement find_by_ingredients async call here (see note below)
                    await self.capability_worker.speak("Feature coming soon! For now, try naming a recipe directly.")
                continue

            await self.capability_worker.speak(
                "Say next, repeat, what step, ingredients, how much [item], timer X minutes, or stop."
            )

    async def fetch_recipe(self, query: str) -> Optional[dict]:
        try:
            # Step 1: Search
            search_response = requests.get(
                f"{BASE_URL}/recipes/complexSearch",
                params={
                    "query": query,
                    "number": 3,
                    "addRecipeInformation": True,
                    "instructionsRequired": True,
                    "fillIngredients": True,
                    "apiKey": API_KEY,
                },
                timeout=10,
            )

            if search_response.status_code != 200:
                print(f"Search error: {search_response.status_code} {search_response.text}")
                return None

            results = search_response.json().get("results", [])
            if not results:
                return None

            recipe_id = results[0]["id"]
            title = results[0]["title"]

            # Step 2: Full info
            info_response = requests.get(
                f"{BASE_URL}/recipes/{recipe_id}/information",
                params={"apiKey": API_KEY, "includeNutrition": False},
                timeout=10,
            )

            if info_response.status_code != 200:
                print(f"Info error: {info_response.status_code} {info_response.text}")
                return None

            data = info_response.json()

            # Steps from analyzedInstructions (preferred)
            analyzed = data.get("analyzedInstructions", [])
            steps = []
            if analyzed and analyzed[0].get("steps"):
                steps = [s["step"].strip() for s in analyzed[0]["steps"] if s["step"].strip()]
            else:
                instructions = data.get("instructions", "")
                instructions = re.sub(r'<[^>]+>', '', instructions)
                steps = [s.strip() for s in re.split(r'\.\s+|\n+', instructions) if s.strip()]

            if not steps:
                return None

            # Ingredients list
            extended_ings = data.get("extendedIngredients", [])
            ingredients = [
                {
                    "name": ing["name"].lower(),
                    "amount": ing.get("amount"),
                    "unit": ing.get("unit", ""),
                }
                for ing in extended_ings
            ]

            return {
                "recipe_name": title,
                "steps": steps,
                "ingredients": ingredients,
                "current_step": 0,
            }

        except Exception as e:
            print("Fetch error:", str(e))
            return None

    # Timer functions (unchanged, but parsing improved in run_workflow)
    async def start_timer(self, minutes: int):
        name = f"Timer {len(self.active_timers) + 1}"
        end_time = time.time() + (minutes * 60)
        task = self.worker.session_tasks.create(self.run_timer(name, end_time))
        self.active_timers[name] = {"task": task}
        await self.capability_worker.speak(f"Started {name} for {minutes} minutes. I'll let you know when it's done.")

    async def run_timer(self, name: str, end_time: float):
        await asyncio.sleep(max(0, end_time - time.time()))
        if name in self.active_timers:
            await self.capability_worker.speak(f"🔔 {name} is up!")
            del self.active_timers[name]

    def extract_minutes(self, text: str) -> Optional[int]:
        # More flexible: look for number near "minute", "min", "timer"
        match = re.search(r"(\d+)\s*(minute|minutes|min|mins)?", text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        # Also handle "two minutes" → word numbers (simple for now)
        word_to_num = {"one":1, "two":2, "three":3, "four":4, "five":5}
        for word, num in word_to_num.items():
            if word in text:
                return num
        return None

    # Session helpers (unchanged)
    async def load_session(self) -> Optional[dict]:
        if await self.capability_worker.check_if_file_exists(SESSION_FILE, False):
            try:
                raw = await self.capability_worker.read_file(SESSION_FILE, False)
                return json.loads(raw)
            except:
                await self.capability_worker.delete_file(SESSION_FILE, False)
        return None

    async def save_session(self, data: dict):
        await self.capability_worker.write_file(SESSION_FILE, json.dumps(data), False)

    async def clear_session(self):
        if await self.capability_worker.check_if_file_exists(SESSION_FILE, False):
            await self.capability_worker.delete_file(SESSION_FILE, False)

    def clean_recipe_input(self, text: str) -> str:
        phrases = [
            "start cooking", "let's cook", "i want to cook", "i would like to cook",
            "please cook", "cook", "hey", "hi", "hello", "what can i cook",
            "i'd like to cook", "make", "prepare", "the recipe for"
        ]
        for phrase in phrases:
            text = re.sub(rf"\b{re.escape(phrase)}\b", "", text, count=1, flags=re.I)
        text = re.sub(r"[^\w\s-]", "", text)
        return text.strip()

    def is_exit(self, text: str) -> bool:
        return any(word in text for word in ["stop", "exit", "quit", "done", "cancel", "end"])
