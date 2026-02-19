import json
import os
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker
import requests

import re
from typing import Dict, List, Optional

API_BASE = "https://www.themealdb.com/api/json/v1/1"

# STEP_ONE = "Which specific location are you interested in knowing the weather for?"
# STEP_TWO = "Are you sure"

# prompt constants
REPEAT_PROMPT = "I'm sorry, I didn't get that. Please repeat that."

MENU_PROMPT = (
    "🍳 Mealmate here! Tell me how to help:\n"
    "- Say a dish name (e.g., 'chicken curry')\n"
    "- Say 'pantry' to use your ingredients\n"
    "- Say 'category' or 'area' to browse\n"
    "- Say 'random' to surprise you\n"
)

# normalize strings by stripping whitespace and collapsing spaces


def _norm(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

# split a long instructions text into small steps


def _steps_from_instructions(instr: Optional[str]) -> List[str]:
    if not instr:
        return []
    raw = [s.strip() for s in re.split(r"\n+|(?<=\.)\s+", instr) if s.strip()]
    return [s for s in raw if len(s) > 2]

# extract ingredient + measure pairs from a meal object


def _parse_ingredients(meal: Dict) -> List[str]:
    items = []
    for i in range(1, 21):
        ing = _norm(meal.get(f"strIngredient{i}", ""))
        mea = _norm(meal.get(f"strMeasure{i}", ""))
        if ing:
            items.append(f"{mea} {ing}".strip())
    return items


class MealmateAbilityCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    current_meal: Optional[Dict] = None
    current_steps: List[str] = []
    step_idx: int = 0

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

    # ask user something & wait for reply
    async def _ask(self, prompt: str) -> str:
        msg = prompt
        while True:
            ans = await self.capability_worker.run_io_loop(msg)
            if ans and str(ans).strip():
                return str(ans).strip()
            msg = REPEAT_PROMPT

    # speak smt back to user
    async def _say(self, text: str):
        await self.capability_worker.speak(text)

    # theMealDB (API) related parts
    # GET used for API
    def _get(self, path: str, params: Dict = None) -> Dict:
        url = f"{API_BASE}/{path}"
        r = requests.get(url, params=params or {}, timeout=10)
        r.raise_for_status()
        return r.json()

    # search recipes by dish name
    def search_by_name(self, q: str) -> List[Dict]:
        data = self._get("search.php", {"s": q})
        return data.get("meals") or []

    # search recipes by ingredients, API only supports 1 at a time so we ask once manually
    def filter_by_ingredient_multi(self, ingredients_csv: str) -> List[Dict]:
        # intersect results for multiple ingredients client-side
        ingredients = [i.strip() for i in ingredients_csv.split(",") if i.strip()]
        if not ingredients:
            return []
        first = self._get("filter.php", {"i": ingredients[0]}).get("meals") or []
        by_id = {m["idMeal"]: m for m in first}
        for ing in ingredients[1:]:
            nxt = self._get("filter.php", {"i": ing}).get("meals") or []
            ids = {m["idMeal"] for m in nxt}
            by_id = {k: v for k, v in by_id.items() if k in ids}
            if not by_id:
                break
        return list(by_id.values())

    # filter recipes by category
    def filter_by_category(self, category: str) -> List[Dict]:
        data = self._get("filter.php", {"c": category})
        return data.get("meals") or []

    # filter recipes by area or cuisine
    def filter_by_area(self, area: str) -> List[Dict]:
        data = self._get("filter.php", {"a": area})
        return data.get("meals") or []

    # lookup a meal by its ID
    def lookup_by_id(self, meal_id: str) -> Optional[Dict]:
        data = self._get("lookup.php", {"i": meal_id})
        meals = data.get("meals") or []
        return meals[0] if meals else None

    # get a random meal
    def random_meal(self) -> Optional[Dict]:
        data = self._get("random.php")
        meals = data.get("meals") or []
        return meals[0] if meals else None

    # extraction for text to text
    def _extract_intent(self, user_text: str) -> Dict[str, str]:
        """
        Uses the built-in text_to_text_response to classify user message into:
        mode ∈ {PANTRY, CATEGORY, AREA, RANDOM, NAME, ASK}
        For NAME mode, also return 'query' (dish text).
        """
        prompt = f"""Classify the user message into one of these modes and (if needed) extract a value.

Modes:
- PANTRY: user wants recipes using their ingredients (keywords: pantry, ingredients, leftovers)
- CATEGORY: user wants to browse by category (Dessert, Seafood, etc.)
- AREA: user wants a cuisine/area (Italian, Mexican, etc.)
- RANDOM: user wants a random meal (random, surprise)
- NAME: user typed a specific dish/keyword to search by name
- ASK: unclear; need to ask user what they want

Return JSON ONLY like:
{{"mode":"PANTRY"}}
or
{{"mode":"CATEGORY"}}
or
{{"mode":"AREA"}}
or
{{"mode":"RANDOM"}}
or
{{"mode":"NAME","query":"<dish name>"}}
or
{{"mode":"ASK"}}

User: {user_text}
"""
        raw = self.capability_worker.text_to_text_response(
            prompt, self.worker.agent_memory.full_message_history
        )
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "mode" in data:
                return data
        except Exception:
            pass
        return {"mode": "ASK"}

        async def _present_brief_list_and_pick(self, meals_brief: List[Dict]) -> Optional[str]:
            # meals_brief items have idMeal, strMeal (and thumb); present top 10
            show = meals_brief[:10]
            lines = [f"{i+1}) {m['strMeal']}" for i, m in enumerate(show)]
            await self._say("Here are some options:\n" + "\n".join(lines))
            pick = await self._ask("Pick a number (or 'cancel'):")
            if pick.lower().startswith("c"):
                return None
            if not pick.isdigit() or not (1 <= int(pick) <= len(show)):
                await self._say("Invalid choice.")
                return None
            return show[int(pick) - 1]["idMeal"]

    # display details for a selected meal
    async def _load_and_show_meal(self, meal_id: str):
        meal = self.lookup_by_id(meal_id)
        if not meal:
            await self._say("Couldn't load that meal. Try another.")
            return
        self.current_meal = meal
        title = meal.get("strMeal", "Unknown meal")
        area = meal.get("strArea") or "Unknown"
        category = meal.get("strCategory") or "Uncategorized"
        # yt = meal.get("strYoutube")
        # src = meal.get("strSource")

        ings = _parse_ingredients(meal)
        await self._say(
            f"**{title}**\n"
            f"Category: {category} • Area: {area}\n"
            f"Ingredients:\n- " + "\n- ".join(ings)
        )
        # if yt:
        #     await self._say(f"YouTube: {yt}")
        # if src:
        #     await self._say(f"Source: {src}")

        # Offer next actions
        while True:
            nxt = (await self._ask("Type 'cook' for guided steps, 'list' for shopping list, 'another' for new search, or 'done' to exit.")).strip().lower()
            if nxt == "cook":
                await self._guided_cook()
            elif nxt == "list":
                await self._shopping_list()
            elif nxt == "another":
                return
            elif nxt == "done":
                return
            else:
                await self._say("Options: cook / list / another / done")

    # shows shopping list for current meal
    async def _shopping_list(self):
        if not self.current_meal:
            await self._say("No meal loaded.")
            return
        ings = _parse_ingredients(self.current_meal)
        await self._say("🛒 Shopping list:\n- " + "\n- ".join(ings))

    # guides user through cooking steps
    async def _guided_cook(self):
        if not self.current_meal:
            await self._say("No meal loaded.")
            return
        self.current_steps = _steps_from_instructions(self.current_meal.get("strInstructions"))
        if not self.current_steps:
            await self._say("This recipe has no detailed steps—check the source link above.")
            return
        self.step_idx = 0
        await self._say("👩‍🍳 Entering cook mode. Commands: next / back / repeat / exit")
        await self._say(f"Step 1: {self.current_steps[0]}")
        while True:
            cmd = (await self._ask("> ")).strip().lower()
            if cmd in {"next", "n"}:
                if self.step_idx < len(self.current_steps) - 1:
                    self.step_idx += 1
                    await self._say(f"Step {self.step_idx+1}: {self.current_steps[self.step_idx]}")
                else:
                    await self._say("🎉 All done. Bon appétit!")
                    return
            elif cmd in {"back", "b"}:
                if self.step_idx > 0:
                    self.step_idx -= 1
                    await self._say(f"Step {self.step_idx+1}: {self.current_steps[self.step_idx]}")
                else:
                    await self._say("Already at the first step.")
            elif cmd in {"repeat", "r"}:
                await self._say(f"Step {self.step_idx+1}: {self.current_steps[self.step_idx]}")
            elif cmd in {"exit", "quit"}:
                await self._say("Exiting cook mode.")
                return
            else:
                await self._say("Commands: next / back / repeat / exit")

    async def first_setup(self):
        # msg = self.worker.final_user_input

        msg = await self.capability_worker.wait_for_complete_transcription()

        # figure out intent from user's first phrase
        intent = self._extract_intent(msg)
        mode = intent.get("mode", "ASK")
        query = intent.get("query")

        try:
            if mode == "PANTRY":
                have = await self._ask("List ingredients you have (comma-separated), e.g., 'chicken, onion, rice':")
                results = self.filter_by_ingredient_multi(have)
                if not results:
                    await self._say("No matches with those ingredients. Try fewer/more common items.")
                else:
                    meal_id = await self._present_brief_list_and_pick(results)
                    if meal_id:
                        await self._load_and_show_meal(meal_id)

            elif mode == "CATEGORY":
                await self._say("Popular categories: Beef, Chicken, Dessert, Pasta, Seafood, Vegetarian.")
                cat = await self._ask("Which category?")
                results = self.filter_by_category(cat)
                if not results:
                    await self._say("No meals found for that category.")
                else:
                    meal_id = await self._present_brief_list_and_pick(results)
                    if meal_id:
                        await self._load_and_show_meal(meal_id)

            elif mode == "AREA":
                await self._say("Popular areas: American, British, Chinese, French, Greek, Indian, Italian, Japanese, Mexican, Moroccan, Spanish, Thai, Turkish.")
                area = await self._ask("Which area/cuisine?")
                results = self.filter_by_area(area)
                if not results:
                    await self._say("No meals found for that area.")
                else:
                    meal_id = await self._present_brief_list_and_pick(results)
                    if meal_id:
                        await self._load_and_show_meal(meal_id)

            elif mode == "RANDOM":
                meal = self.random_meal()
                if not meal:
                    await self._say("No random meal available right now.")
                else:
                    await self._load_and_show_meal(meal["idMeal"])

            elif mode == "NAME":
                if not query or len(query) < 2:
                    query = await self._ask("Dish name or keyword (e.g., 'tikka', 'pasta'):")
                matches = self.search_by_name(query)
                if not matches:
                    await self._say("No results for that dish name. Try another keyword.")
                else:
                    # search.php returns full meals already; present top 5
                    show = matches[:5]
                    lines = [f"{i+1}) {m['strMeal']}" for i, m in enumerate(show)]
                    await self._say("I found:\n" + "\n".join(lines))
                    pick = await self._ask("Pick a number (or 'cancel'):")
                    if not pick.lower().startswith("c") and pick.isdigit() and 1 <= int(pick) <= len(show):
                        await self._load_and_show_meal(show[int(pick) - 1]["idMeal"])

            else:  # ASK
                await self._say(MENU_PROMPT)
                # Fall back to a quick follow-up ask → re-extract once
                follow = await self._ask("How should I help?")
                intent = self._extract_intent(follow)
                # Minimal recursion to handle once
                if intent.get("mode") and intent.get("mode") != "ASK":
                    # Simulate restarting with the clarified intent
                    # (We reuse first_setup core branches without re-waiting transcription)
                    mode = intent["mode"]
                    query = intent.get("query")
                    # Quick branch reuse:
                    if mode == "RANDOM":
                        meal = self.random_meal()
                        if meal:
                            await self._load_and_show_meal(meal["idMeal"])
                        else:
                            await self._say("No random meal right now.")
                    elif mode == "PANTRY":
                        have = await self._ask("List ingredients (comma-separated):")
                        results = self.filter_by_ingredient_multi(have)
                        if results:
                            meal_id = await self._present_brief_list_and_pick(results)
                            if meal_id:
                                await self._load_and_show_meal(meal_id)
                        else:
                            await self._say("No matches with those ingredients.")
                    elif mode == "CATEGORY":
                        cat = await self._ask("Which category?")
                        results = self.filter_by_category(cat)
                        if results:
                            meal_id = await self._present_brief_list_and_pick(results)
                            if meal_id:
                                await self._load_and_show_meal(meal_id)
                        else:
                            await self._say("No meals found for that category.")
                    elif mode == "AREA":
                        area = await self._ask("Which area/cuisine?")
                        results = self.filter_by_area(area)
                        if results:
                            meal_id = await self._present_brief_list_and_pick(results)
                            if meal_id:
                                await self._load_and_show_meal(meal_id)
                        else:
                            await self._say("No meals found for that area.")
                    elif mode == "NAME":
                        if not query or len(query) < 2:
                            query = await self._ask("Dish name or keyword:")
                        matches = self.search_by_name(query)
                        if matches:
                            show = matches[:5]
                            lines = [f"{i+1}) {m['strMeal']}" for i, m in enumerate(show)]
                            await self._say("I found:\n" + "\n".join(lines))
                            pick = await self._ask("Pick a number (or 'cancel'):")
                            if not pick.lower().startswith("c") and pick.isdigit() and 1 <= int(pick) <= len(show):
                                await self._load_and_show_meal(show[int(pick) - 1]["idMeal"])
                        else:
                            await self._say("No results for that dish name.")
                    else:
                        await self._say("Okay! Ping me again when you're ready.")
                else:
                    await self._say("Okay! Ping me again when you're ready.")

        except requests.RequestException:
            await self._say("Looks like TheMealDB is unavailable right now. Please try again later.")
        except Exception:
            await self._say("Something went wrong. Please try again.")

        await self.worker.session_tasks.sleep(1)
        self.capability_worker.resume_normal_flow()

    def call(
        self,
        worker: AgentWorker,
    ):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.first_setup())
