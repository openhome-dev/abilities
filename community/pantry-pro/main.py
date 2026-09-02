import json
import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# pantrypro — voice-guided pantry assistant
# persist inventory, suggest meals from stock, flag expiry, build shopping lists

STORAGE_FILE = "pantrypro_inventory.json"
MEALDB = "https://www.themealdb.com/api/json/v1/1"
API_TIMEOUT = 10

CANCEL_PHRASES = ("never mind", "cancel", "forget it", "skip")

YES_WORDS = ("yes", "yeah", "yep", "sure", "ok", "okay", "please", "do it", "yup")

FULL_LIST_PHRASES = (
    "whole list", "full list", "entire list", "complete list",
    "all of them", "all of it", "all items", "everything",
    "the rest", "what's left", "whats left", "read them all",
    "list them all", "every item", "don't truncate", "dont truncate",
    "instead of", "no more", "not four more", "not 4 more",
)

INTENT_PROMPT = """Classify this pantry command. Today is {today}.
Return ONLY JSON in this exact shape:
{{"intent":"<intent>","items":[{{"name":"","qty":1,"unit":"","location":"","expires":""}}],"location_filter":"all","full_list":false}}

intents:
- add — putting food into the pantry, fridge, or freezer
- used — finished / threw out / used the last of something (restock later)
- remove — stop tracking an item without restocking
- list — hear what's in stock
- expiring — what's going bad soon across the pantry (no specific item)
- item_date — ask when a specific item expires / what date is on it
  (e.g. "when does the ground beef expire", "what's the date on the milk")
- recipes — meal ideas from current stock
- shop_add — put items on the shopping list
- shop_read — hear the shopping list
- shop_clear — empty the shopping list
- shop_build — generate a grocery list from gaps / a planned meal
- update — change quantity or expiry
- tips — waste-saving tips
- exit — done / stop
- unknown — not a pantry command

rules:
- extract item names as short lowercase grocery words (milk, not "the milk we bought")
- location is pantry, fridge, freezer, or empty
- expires is YYYY-MM-DD if a date can be inferred, else empty
- qty is a number (default 1). unit is optional (cans, gallons, leftovers)
- location_filter is pantry, fridge, freezer, or all
- full_list is true when the user wants the complete inventory read aloud
  (whole list, full list, all items, everything, the rest, stop saying N more)
- for item_date, put the named item in items
- for list/expiring/recipes/exit/unknown, items may be empty
- split multiples: "milk and eggs" → two items
- "when does X expire" / "expiry date for X" / "tell me the date that X expires" → item_date, not expiring

user said: "{input}"
"""

RECIPE_FALLBACK_PROMPT = """You are a concise home cook. Given this inventory, suggest 3 simple meals.
prioritize items that expire soon. each meal should mostly use what's on hand.
respect diet and household size from the user profile when present
(for example vegetarian, vegan, gluten-free, or cooking for a family).
return ONLY JSON: {{"meals":[{{"name":"","uses":["item"]}}]}}
inventory: {inventory}
expiring soon: {expiring}
user profile: {profile}
"""

INGREDIENT_MAP = {
    "pasta": "spaghetti",
    "spaghetti": "spaghetti",
    "tomato sauce": "tomato",
    "pasta sauce": "tomato",
    "canned beans": "kidney beans",
    "beans": "kidney beans",
    "black beans": "black beans",
    "chickpeas": "chickpeas",
    "garbanzo": "chickpeas",
    "milk": "milk",
    "eggs": "egg",
    "egg": "egg",
    "chicken": "chicken",
    "rice": "rice",
    "onion": "onion",
    "garlic": "garlic",
    "butter": "butter",
    "cheese": "cheese",
    "beef": "beef",
    "ground beef": "beef",
    "tomato": "tomato",
    "tomatoes": "tomato",
    "bread": "bread",
    "potato": "potato",
    "potatoes": "potato",
    "spinach": "spinach",
    "lettuce": "lettuce",
    "yogurt": "yogurt",
    "tuna": "tuna",
    "salmon": "salmon",
    "flour": "flour",
    "sugar": "sugar",
    "oats": "oats",
    "peanut butter": "peanut butter",
}


def _empty_data() -> dict:
    return {"items": [], "shopping": []}


def _item_id() -> str:
    return f"itm_{uuid.uuid4().hex[:8]}"


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def _singularize(name: str) -> str:
    # light singularization for eggs/egg, tomatoes/tomato, boxes/box
    n = _norm(name)
    if len(n) > 4 and n.endswith("ies"):
        return n[:-3] + "y"
    if len(n) > 4 and n.endswith(("oes", "ses", "xes", "ches", "shes")):
        return n[:-2]
    if len(n) > 2 and n.endswith("s") and not n.endswith("ss"):
        return n[:-1]
    return n


def _names_match_strict(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    return _singularize(na) == _singularize(nb)


def _parse_json(raw: str) -> dict:
    clean = raw.replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(clean)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _join_and(parts: list) -> str:
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def _wants_full_list(text: str) -> bool:
    lower = (text or "").lower()
    if any(p in lower for p in FULL_LIST_PHRASES):
        return True
    # "give me all of them" / "read all eight"
    if "all" in lower.split() and any(
        w in lower for w in ("list", "item", "items", "them", "stock", "pantry", "fridge")
    ):
        return True
    return False


def _format_days(days: int) -> str:
    if days < 0:
        n = abs(days)
        return "yesterday" if n == 1 else f"{n} days ago"
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"in {days} days"


class PantryProCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    data: dict = None
    pending: dict = None
    load_ok: bool = False

    # do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.data = _empty_data()
        self.pending = None
        self.load_ok = False
        self.worker.session_tasks.create(self.run())

    def _today(self):
        try:
            tz = ZoneInfo(self.capability_worker.get_timezone())
            return datetime.now(tz).date()
        except Exception:
            return datetime.now().date()

    def _log(self, msg: str):
        self.worker.editor_logging_handler.info(f"[PantryPro] {msg}")

    def _err(self, msg: str):
        self.worker.editor_logging_handler.error(f"[PantryPro] {msg}")

    # storage

    async def _load(self) -> bool:
        # true = safe to save later. missing file is ok; a failed read is not.
        try:
            exists = await self.capability_worker.check_if_file_exists(STORAGE_FILE, False)
            if not exists:
                self.data = _empty_data()
                self.load_ok = True
                return True

            raw = await self.capability_worker.read_file(STORAGE_FILE, False)
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("inventory is not a json object")
            parsed.setdefault("items", [])
            parsed.setdefault("shopping", [])
            self.data = parsed
            self.load_ok = True
            return True
        except Exception as e:
            self._err(f"load failed: {e}")
            self.data = _empty_data()
            self.load_ok = False
            return False

    async def _save(self) -> bool:
        if not self.load_ok:
            self._err("save refused: inventory was not loaded cleanly")
            return False
        try:
            await self.capability_worker.delete_file(STORAGE_FILE, False)
            await self.capability_worker.write_file(
                STORAGE_FILE, json.dumps(self.data), False
            )
            return True
        except Exception as e:
            self._err(f"save failed: {e}")
            return False

    async def _persist(self) -> str:
        # save after a mutation; return a short spoken warning on failure
        if await self._save():
            return ""
        return " I couldn't save that right now, so it may not stick."

    async def _read_user_profile(self) -> str:
        # read-only — never write user_profile.md (platform-owned)
        try:
            if not await self.capability_worker.check_if_file_exists(
                "user_profile.md", False
            ):
                return ""
            raw = await self.capability_worker.read_file("user_profile.md", False)
            text = (raw or "").strip()
            if len(text) > 1200:
                text = text[:1200]
            return text
        except Exception as e:
            self._err(f"user_profile read skipped: {e}")
            return ""

    # inventory helpers

    def _days_until(self, expires: str) -> int:
        if not expires:
            return 9999
        try:
            exp = datetime.strptime(expires[:10], "%Y-%m-%d").date()
            return (exp - self._today()).days
        except Exception:
            return 9999

    def _find_item(self, name: str, location: str = "", *, fuzzy: bool = False):
        # merge/add: strict exact or singular/plural only.
        # lookups (used/remove/update): fuzzy allowed, longest name wins.
        n = _norm(name)
        if not n:
            return None

        candidates = []
        for item in self.data.get("items", []):
            if location and item.get("location") and item.get("location") != location:
                continue
            candidates.append(item)

        for item in candidates:
            if _norm(item.get("name", "")) == n:
                return item

        for item in candidates:
            if _names_match_strict(item.get("name", ""), n):
                return item

        if not fuzzy:
            return None

        fuzzy_hits = []
        for item in candidates:
            iname = _norm(item.get("name", ""))
            if n in iname or iname in n:
                fuzzy_hits.append(item)
        if not fuzzy_hits:
            return None
        fuzzy_hits.sort(key=lambda i: len(_norm(i.get("name", ""))), reverse=True)
        return fuzzy_hits[0]

    def _expiring(self, within: int = 5) -> list:
        due = []
        for item in self.data.get("items", []):
            days = self._days_until(item.get("expires", ""))
            if days <= within:
                due.append((item, days))
        due.sort(key=lambda pair: pair[1])
        return due

    def _headline_stock(self, limit: int = 3) -> str:
        items = self.data.get("items", [])
        if not items:
            return ""
        ranked = sorted(
            items,
            key=lambda i: self._days_until(i.get("expires", "")),
        )
        names = [i["name"] for i in ranked[:limit]]
        return _join_and(names)

    def _is_exit(self, text: str) -> bool:
        lower = (text or "").lower().strip()
        if any(
            p in lower
            for p in (
                "that's all", "thats all", "nothing else",
                "i'm good", "im good", "all done", "all good", "no thanks",
            )
        ):
            return True
        tokens = set(lower.split())
        return bool(tokens & {"stop", "exit", "quit", "done", "bye", "goodbye"}) and len(tokens) <= 2

    def _is_cancel(self, text: str) -> bool:
        lower = (text or "").lower()
        return any(p in lower for p in CANCEL_PHRASES)

    def _is_yes(self, text: str) -> bool:
        lower = (text or "").lower().strip()
        return lower in YES_WORDS or lower.startswith("yes")

    def _is_no(self, text: str) -> bool:
        lower = (text or "").lower().strip()
        return lower in ("no", "nope", "nah", "not now", "later") or lower.startswith("no ")

    def _trigger_text(self) -> str:
        history = self.capability_worker.get_full_message_history() or []
        for msg in reversed(history):
            if msg.get("role") == "user":
                return (msg.get("content") or "").strip()
        return ""

    def classify(self, user_input: str) -> dict:
        prompt = INTENT_PROMPT.format(today=self._today().isoformat(), input=user_input)
        raw = self.capability_worker.text_to_text_response(
            prompt,
            system_prompt="return only valid json. no markdown.",
        )
        result = _parse_json(raw)
        if not result:
            self._err(f"intent parse failed: {raw[:200]}")
            return {"intent": "unknown", "items": [], "location_filter": "all"}
        result.setdefault("intent", "unknown")
        result.setdefault("items", [])
        result.setdefault("location_filter", "all")
        result.setdefault("full_list", False)
        if not isinstance(result["items"], list):
            result["items"] = []
        return result

    def _looks_like_item_date(self, text: str) -> bool:
        lower = (text or "").lower()
        asks_when = any(
            p in lower
            for p in (
                "when does", "when do", "what date", "the date",
                "expiry", "expiration", "best by", "use by",
            )
        )
        mentions_expire = any(
            p in lower for p in ("expire", "expires", "expiry", "expiration", "date")
        )
        return asks_when and mentions_expire

    def _refine_result(self, result: dict, user_input: str) -> dict:
        # fix common misroutes before dispatch
        intent = (result.get("intent") or "unknown").lower()
        if intent == "list" and _wants_full_list(user_input):
            result["full_list"] = True

        if self._looks_like_item_date(user_input) and intent in (
            "expiring", "unknown", "list", "tips",
        ):
            result["intent"] = "item_date"
            if not any((s.get("name") or "").strip() for s in (result.get("items") or [])):
                # match a stocked item named in the utterance
                lower = user_input.lower()
                hits = []
                for item in self.data.get("items") or []:
                    name = _norm(item.get("name", ""))
                    if name and name in lower:
                        hits.append(name)
                if hits:
                    # longest name wins (ground beef over beef)
                    hits.sort(key=len, reverse=True)
                    result["items"] = [{"name": hits[0], "qty": 1, "unit": "", "location": "", "expires": ""}]
        return result

    # mutations

    def _upsert_item(self, spec: dict) -> str:
        name = _norm(spec.get("name", ""))
        if not name:
            return ""
        location = (spec.get("location") or "").lower().strip()
        if location not in ("pantry", "fridge", "freezer"):
            location = ""
        qty = spec.get("qty") or 1
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            qty = 1
        unit = (spec.get("unit") or "").strip().lower()
        expires = (spec.get("expires") or "").strip()
        if expires and not re.match(r"^\d{4}-\d{2}-\d{2}$", expires):
            expires = ""

        existing = self._find_item(name, location)
        if existing:
            try:
                extra = int(qty)
            except (TypeError, ValueError):
                extra = 1
            existing["qty"] = int(existing.get("qty") or 1) + max(1, extra)
            if unit:
                existing["unit"] = unit
            if location:
                existing["location"] = location
            if expires:
                existing["expires"] = expires
            return existing["name"]

        item = {
            "id": _item_id(),
            "name": name,
            "qty": max(1, qty),
            "unit": unit,
            "location": location or "pantry",
            "expires": expires,
            "added": self._today().isoformat(),
        }
        self.data.setdefault("items", []).append(item)
        return name

    def _remove_item(self, name: str, location: str = "") -> dict:
        item = self._find_item(name, location, fuzzy=True)
        if not item:
            return {}
        self.data["items"] = [
            i for i in self.data.get("items", []) if i.get("id") != item.get("id")
        ]
        return item

    def _shop_add(self, names: list) -> list:
        added = []
        shopping = self.data.setdefault("shopping", [])
        for name in names:
            n = _norm(name)
            if not n:
                continue
            if n not in shopping:
                shopping.append(n)
                added.append(n)
        return added

    # recipes

    def _mealdb_ingredient(self, name: str) -> str:
        n = _norm(name)
        if n in INGREDIENT_MAP:
            return INGREDIENT_MAP[n]
        for key, val in INGREDIENT_MAP.items():
            if key in n or n in key:
                return val
        # last token often works ("canned tomato" → tomato)
        parts = n.split()
        return parts[-1] if parts else n

    def _parse_meal_ingredients(self, meal: dict) -> list:
        out = []
        for i in range(1, 21):
            ing = _norm(meal.get(f"strIngredient{i}", ""))
            if ing:
                out.append(ing)
        return out

    def _missing_for(self, ingredients: list) -> list:
        stock = [_norm(i.get("name", "")) for i in self.data.get("items", [])]
        missing = []
        skip = {
            "salt", "pepper", "water", "oil", "olive oil", "vegetable oil",
            "sugar", "flour", "garlic", "onion",
        }
        for ing in ingredients:
            if ing in skip:
                continue
            if any(ing == s or ing in s or s in ing for s in stock):
                continue
            missing.append(ing)
        return missing[:8]

    async def _search_meals(self, ingredient: str) -> list:
        url = f"{MEALDB}/filter.php"
        try:
            r = await self.worker.session_tasks.get_async(
                url, params={"i": ingredient}, timeout=API_TIMEOUT
            )
            if r.status_code != 200:
                self._err(f"mealdb filter status {r.status_code}")
                return []
            data = r.json()
            return (data.get("meals") or [])[:6]
        except Exception as e:
            self._err(f"mealdb filter failed: {e}")
            return []

    async def _lookup_meal(self, meal_id: str) -> dict:
        url = f"{MEALDB}/lookup.php"
        try:
            r = await self.worker.session_tasks.get_async(
                url, params={"i": meal_id}, timeout=API_TIMEOUT
            )
            if r.status_code != 200:
                self._err(f"mealdb lookup status {r.status_code}")
                return {}
            data = r.json()
            meals = data.get("meals") or []
            return meals[0] if meals else {}
        except Exception as e:
            self._err(f"mealdb lookup failed: {e}")
            return {}

    async def _llm_recipes(self) -> list:
        items = [i.get("name", "") for i in self.data.get("items", [])]
        expiring = [i["name"] for i, _ in self._expiring(5)]
        profile = await self._read_user_profile()
        raw = self.capability_worker.text_to_text_response(
            RECIPE_FALLBACK_PROMPT.format(
                inventory=_join_and(items) or "empty",
                expiring=_join_and(expiring) or "none",
                profile=profile or "none",
            ),
            system_prompt="return only valid json. no markdown.",
        )
        parsed = _parse_json(raw)
        meals = parsed.get("meals") if isinstance(parsed, dict) else []
        out = []
        if isinstance(meals, list):
            for m in meals[:3]:
                if isinstance(m, dict) and m.get("name"):
                    out.append({"strMeal": m["name"], "idMeal": "", "uses": m.get("uses") or []})
        return out

    # speak helpers

    def _list_speech(self, location_filter: str = "all", *, full: bool = False) -> str:
        items = self.data.get("items", [])
        if location_filter in ("pantry", "fridge", "freezer"):
            items = [i for i in items if i.get("location") == location_filter]
        if not items:
            if location_filter == "all":
                return "Nothing tracked yet. Tell me what's in the pantry or fridge."
            return f"Nothing in the {location_filter} yet."

        by_loc = {"fridge": [], "pantry": [], "freezer": []}
        for item in items:
            loc = item.get("location") or "pantry"
            by_loc.setdefault(loc, []).append(item.get("name", "item"))

        if location_filter in by_loc:
            names = by_loc[location_filter]
            if full or len(names) <= 5:
                return f"In the {location_filter}: {_join_and(names)}."
            shown = names[:5]
            rest = len(names) - 5
            return (
                f"In the {location_filter}: {_join_and(shown)}. "
                f"Plus {rest} more — want the whole list?"
            )

        total = len(items)
        if full:
            chunks = []
            for loc in ("fridge", "pantry", "freezer"):
                names = by_loc.get(loc) or []
                if names:
                    chunks.append(f"{loc}: {_join_and(names)}")
            return f"{total} items. " + ". ".join(chunks) + "."

        chunks = []
        truncated = False
        for loc in ("fridge", "pantry", "freezer"):
            names = by_loc.get(loc) or []
            if not names:
                continue
            if len(names) > 4:
                truncated = True
                chunks.append(f"{loc} has {_join_and(names[:4])}")
            else:
                chunks.append(f"{loc} has {_join_and(names)}")
        speech = f"{total} items. " + ". ".join(chunks) + "."
        if truncated:
            speech += " Want the whole list?"
        return speech

    def _spoken_date(self, expires: str) -> str:
        try:
            exp = datetime.strptime(expires[:10], "%Y-%m-%d").date()
            return f"{exp.strftime('%B')} {exp.day}, {exp.year}"
        except Exception:
            return expires

    def _should_ask_expiry(self, name: str, location: str) -> bool:
        # ask dates for fridge/freezer and obvious perishables; skip dry goods
        loc = (location or "").lower()
        n = _norm(name)
        if loc in ("fridge", "freezer"):
            return True
        perishable = (
            "milk", "cream", "yogurt", "cheese", "butter", "egg",
            "beef", "chicken", "pork", "turkey", "fish", "salmon", "shrimp",
            "meat", "leftover", "deli", "ham", "bacon", "sausage",
            "spinach", "lettuce", "berries", "strawberry", "tofu",
        )
        shelf_stable = (
            "pasta", "spaghetti", "rice", "bean", "sauce", "flour", "sugar",
            "oil", "vinegar", "cereal", "oat", "spice", "salt", "pepper",
            "can", "canned", "broth", "stock", "honey", "peanut butter",
        )
        if any(p in n for p in perishable):
            return True
        if any(s in n for s in shelf_stable):
            return False
        return False

    def _item_expiry_speech(self, specs: list) -> str:
        parts = []
        for spec in specs:
            name = (spec.get("name") or "").strip()
            if not name:
                continue
            item = self._find_item(name, fuzzy=True)
            if not item:
                parts.append(f"I don't have {_norm(name)} tracked.")
                continue
            label = item.get("name", name)
            expires = item.get("expires") or ""
            if not expires:
                parts.append(f"No expiry date set for {label}.")
                continue
            days = self._days_until(expires)
            spoken = self._spoken_date(expires)
            if days < 0:
                parts.append(f"{label} expired on {spoken}.")
            elif days == 0:
                parts.append(f"{label} expires today — {spoken}.")
            else:
                parts.append(
                    f"{label} expires {spoken} — that's {_format_days(days)}."
                )
        return " ".join(parts) or "Which item's expiry date do you want?"

    def _expiring_speech(self) -> str:
        due = self._expiring(5)
        if not due:
            return "Nothing is close to expiring. Nice work."
        parts = []
        for item, days in due[:4]:
            name = item.get("name", "item")
            loc = item.get("location") or ""
            where = f" in the {loc}" if loc else ""
            if days < 0:
                parts.append(f"{name}{where} already went bad {_format_days(days)}")
            elif days == 0:
                parts.append(f"{name}{where} expires today")
            else:
                parts.append(f"{name}{where} expires {_format_days(days)}")
        extra = f" Plus {len(due) - 4} more." if len(due) > 4 else ""
        return _join_and(parts).capitalize() + "." + extra

    def _shop_speech(self) -> str:
        shopping = self.data.get("shopping") or []
        if not shopping:
            return "Your shopping list is empty."
        if len(shopping) == 1:
            return f"One item: {shopping[0]}."
        return f"{len(shopping)} items: {_join_and(shopping)}."

    # handlers

    async def _handle_add(self, specs: list) -> str:
        added = []
        needs_date = []
        for spec in specs:
            name = self._upsert_item(spec)
            if not name:
                continue
            added.append(name)
            item = self._find_item(name, (spec.get("location") or ""))
            if not item or item.get("expires"):
                continue
            loc = item.get("location") or (spec.get("location") or "")
            if self._should_ask_expiry(name, loc):
                needs_date.append(name)
        if not added:
            return "I didn't catch what to add. Try 'add milk to the fridge, expires Friday'."
        warn = await self._persist()
        msg = f"Added {_join_and(added)}."
        if needs_date:
            # ask one item at a time — never apply one date to the whole batch
            self.pending = {
                "type": "expiry",
                "name": needs_date[0],
                "remaining": needs_date[1:],
            }
            msg += f" When does the {needs_date[0]} expire? Say a date, or skip."
        return msg + warn

    async def _handle_used(self, specs: list) -> str:
        removed = []
        for spec in specs:
            item = self._remove_item(spec.get("name", ""), spec.get("location") or "")
            if item:
                removed.append(item.get("name"))
        if not removed:
            return "I couldn't find that in your pantry."
        warn = await self._persist()
        self.pending = {"type": "shop_used", "names": removed}
        return (
            f"Removed {_join_and(removed)}. "
            f"Add {_join_and(removed)} to the shopping list?"
            + warn
        )

    async def _handle_remove(self, specs: list) -> str:
        removed = []
        missing = []
        for spec in specs:
            item = self._remove_item(spec.get("name", ""), spec.get("location") or "")
            if item:
                removed.append(item.get("name"))
            else:
                missing.append(_norm(spec.get("name", "")))
        warn = await self._persist() if removed else ""
        parts = []
        if removed:
            parts.append(f"Stopped tracking {_join_and(removed)}.")
        if missing:
            parts.append(f"Couldn't find {_join_and([m for m in missing if m])}.")
        return (" ".join(parts) or "I didn't catch what to remove.") + warn

    async def _handle_update(self, specs: list) -> str:
        updated = []
        for spec in specs:
            item = self._find_item(
                spec.get("name", ""), spec.get("location") or "", fuzzy=True
            )
            if not item:
                continue
            if spec.get("qty"):
                try:
                    item["qty"] = max(1, int(spec["qty"]))
                except (TypeError, ValueError):
                    pass
            if spec.get("unit"):
                item["unit"] = spec["unit"]
            if spec.get("location") in ("pantry", "fridge", "freezer"):
                item["location"] = spec["location"]
            if spec.get("expires"):
                item["expires"] = spec["expires"]
            updated.append(item["name"])
        if not updated:
            return "I couldn't find that item to update."
        warn = await self._persist()
        return f"Updated {_join_and(updated)}." + warn

    async def _handle_recipes(self) -> str:
        items = self.data.get("items") or []
        if not items:
            return "Add a few ingredients first, then I can suggest meals."

        await self.capability_worker.speak("One sec, matching what you've got to some meals.")

        due = self._expiring(5)
        search_from = [i for i, _ in due] + items
        meals = []
        used_ing = ""
        for src in search_from[:4]:
            ing = self._mealdb_ingredient(src.get("name", ""))
            if not ing:
                continue
            found = await self._search_meals(ing)
            if found:
                meals = found
                used_ing = ing
                break

        if not meals:
            meals = await self._llm_recipes()

        if not meals:
            stock = self._headline_stock()
            return f"I couldn't find a match. You have {stock}. Want to add more items?"

        show = meals[:3]
        self.pending = {"type": "recipe_pick", "meals": show}
        names = [m.get("strMeal", "a meal") for m in show]
        lead = ""
        if due:
            lead = f"Using {due[0][0].get('name')} before it goes. "
        elif used_ing:
            lead = f"Based on {used_ing}. "
        numbered = ". ".join(f"{i + 1}, {n}" for i, n in enumerate(names))
        return f"{lead}I can do {numbered}. Pick a number, or say skip."

    async def _handle_shop_add(self, specs: list) -> str:
        names = [_norm(s.get("name", "")) for s in specs]
        added = self._shop_add(names)
        skipped = [n for n in names if n and n not in added]
        warn = await self._persist() if added else ""
        parts = []
        if added:
            parts.append(f"Put {_join_and(added)} on the shopping list.")
        if skipped:
            parts.append(f"{_join_and(skipped)} already listed.")
        return (" ".join(parts) or "What should I add to the shopping list?") + warn

    async def _handle_shop_build(self, specs: list) -> str:
        # if they named ingredients, add those; else restock expired items onto the list
        if specs and any(s.get("name") for s in specs):
            return await self._handle_shop_add(specs)
        expired = [i.get("name") for i, d in self._expiring(0) if d < 0]
        added = self._shop_add(expired)
        shopping = self.data.get("shopping") or []
        warn = await self._persist() if added else ""
        if added:
            return f"Added expired items: {_join_and(added)}. {_shop_tail(shopping)}" + warn
        if shopping:
            return self._shop_speech()
        return "List is empty. Name items to buy, or pick a recipe and I'll add what's missing."

    async def _handle_tips(self) -> str:
        due = self._expiring(5)
        stock = [i.get("name") for i in self.data.get("items", [])]
        if not stock:
            return "Once you log a few items, I can give use-it-up tips."
        prompt = (
            "Give one short spoken tip (2 sentences max) to reduce food waste. "
            f"Stock: {_join_and(stock)}. "
            f"Expiring: {_join_and([i['name'] for i, _ in due]) or 'none'}."
        )
        tip = self.capability_worker.text_to_text_response(
            prompt,
            system_prompt="you are pantrypro. be warm and brief. no markdown.",
        )
        return (tip or "Cook the oldest items first, and freeze leftovers the same day.").strip()

    async def _dispatch(self, result: dict) -> str:
        intent = (result.get("intent") or "unknown").lower()
        specs = result.get("items") or []
        loc = (result.get("location_filter") or "all").lower()

        if intent == "add":
            return await self._handle_add(specs)
        if intent == "used":
            return await self._handle_used(specs)
        if intent == "remove":
            return await self._handle_remove(specs)
        if intent == "list":
            full = bool(result.get("full_list"))
            speech = self._list_speech(loc, full=full)
            if not full and "want the whole list" in speech.lower():
                self.pending = {"type": "list_full", "location_filter": loc}
            return speech
        if intent == "item_date":
            return self._item_expiry_speech(specs)
        if intent == "expiring":
            # "when does the milk expire" sometimes lands here with an item name
            if any((s.get("name") or "").strip() for s in specs):
                return self._item_expiry_speech(specs)
            return self._expiring_speech()
        if intent == "recipes":
            return await self._handle_recipes()
        if intent == "shop_add":
            return await self._handle_shop_add(specs)
        if intent == "shop_read":
            return self._shop_speech()
        if intent == "shop_clear":
            if not self.data.get("shopping"):
                return "The shopping list is already empty."
            confirmed = await self.capability_worker.run_confirmation_loop(
                f"Clear all {len(self.data['shopping'])} shopping items?"
            )
            if confirmed:
                self.data["shopping"] = []
                warn = await self._persist()
                return "Shopping list cleared." + warn
            return "Okay, keeping the list."
        if intent == "shop_build":
            return await self._handle_shop_build(specs)
        if intent == "update":
            return await self._handle_update(specs)
        if intent == "tips":
            return await self._handle_tips()
        if intent == "exit":
            return "__exit__"
        return (
            "I can add food, check what's expiring, suggest meals, or build a shopping list. "
            "What do you need?"
        )

    async def _handle_pending(self, user_input: str) -> str:
        pending = self.pending
        if not pending:
            return ""
        if self._is_cancel(user_input):
            self.pending = None
            return "Okay, skipped."

        ptype = pending.get("type")

        if ptype == "list_full":
            loc = pending.get("location_filter") or "all"
            if self._is_yes(user_input) or _wants_full_list(user_input):
                self.pending = None
                return self._list_speech(loc, full=True)
            if self._is_no(user_input):
                self.pending = None
                return "Okay."
            self.pending = None
            return ""

        if ptype == "expiry":
            name = pending.get("name") or ""
            remaining = list(pending.get("remaining") or [])

            if self._is_yes(user_input) or "skip" in user_input.lower():
                if remaining:
                    self.pending = {
                        "type": "expiry",
                        "name": remaining[0],
                        "remaining": remaining[1:],
                    }
                    return (
                        f"Okay, no date for {name}. "
                        f"When does the {remaining[0]} expire? Say a date, or skip."
                    )
                self.pending = None
                return "Got it, no date. Anything else?"

            raw = self.capability_worker.text_to_text_response(
                f"Today is {self._today().isoformat()}. Extract an expiry date as YYYY-MM-DD "
                f"from: '{user_input}'. "
                "If only a month and year are given, use the first day of that month. "
                "Return ONLY the date or UNKNOWN.",
                system_prompt="return only a date or UNKNOWN.",
            )
            date = (raw or "").strip()[:10]
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
                return "I didn't catch the date. Try 'next Friday' or say skip."

            item = self._find_item(name, fuzzy=True)
            if item:
                item["expires"] = date
            warn = await self._persist()
            spoken = self._spoken_date(date)
            if remaining:
                self.pending = {
                    "type": "expiry",
                    "name": remaining[0],
                    "remaining": remaining[1:],
                }
                return (
                    f"Set {name} to expire {spoken}. "
                    f"When does the {remaining[0]} expire? Say a date, or skip."
                    + warn
                )
            self.pending = None
            return f"Set {name} to expire {spoken}. Anything else?" + warn

        if ptype == "shop_used":
            names = pending.get("names") or []
            if self._is_yes(user_input):
                self.pending = None
                added = self._shop_add(names)
                warn = await self._persist()
                return f"Added {_join_and(added or names)} to the shopping list." + warn
            if self._is_no(user_input):
                self.pending = None
                return "Okay, leaving the shopping list as is."
            self.pending = None
            return ""

        if ptype == "recipes_offer":
            if self._is_yes(user_input) or "recipe" in user_input.lower():
                self.pending = None
                return await self._handle_recipes()
            if self._is_no(user_input):
                self.pending = None
                return "Okay. Add items, check expiry, or say done."
            self.pending = None
            return ""

        if ptype == "recipe_pick":
            meals = pending.get("meals") or []
            lower = user_input.lower().strip()
            pick = None
            if lower in ("1", "one", "first"):
                pick = meals[0] if meals else None
            elif lower in ("2", "two", "second") and len(meals) > 1:
                pick = meals[1]
            elif lower in ("3", "three", "third") and len(meals) > 2:
                pick = meals[2]
            else:
                for m in meals:
                    if _norm(m.get("strMeal", "")) in _norm(user_input) or _norm(user_input) in _norm(m.get("strMeal", "")):
                        pick = m
                        break
            if not pick:
                return "Say 1, 2, or 3, or skip."

            meal_id = pick.get("idMeal") or ""
            title = pick.get("strMeal", "that meal")
            missing = []
            if meal_id:
                detail = await self._lookup_meal(meal_id)
                ings = self._parse_meal_ingredients(detail) if detail else []
                missing = self._missing_for(ings)
            elif pick.get("uses"):
                missing = self._missing_for([_norm(u) for u in pick["uses"]])

            self.pending = None
            if missing:
                self.pending = {"type": "shop_missing", "names": missing, "meal": title}
                return (
                    f"{title}. You're missing {_join_and(missing[:5])}. "
                    "Add those to the shopping list?"
                )
            return f"{title}. You already have what you need. Want another idea?"

        if ptype == "shop_missing":
            names = pending.get("names") or []
            if self._is_yes(user_input):
                self.pending = None
                added = self._shop_add(names)
                warn = await self._persist()
                return f"Added {_join_and(added or names)} to the shopping list." + warn
            if self._is_no(user_input):
                self.pending = None
                return "Okay, I won't add them."
            self.pending = None
            return ""

        self.pending = None
        return ""

    def _signoff(self) -> str:
        n = len(self.data.get("items") or [])
        shop = len(self.data.get("shopping") or [])
        if n and shop:
            return f"Saved. {n} items in stock, {shop} on the shopping list."
        if n:
            return f"Saved. {n} items in stock. See you next time."
        return "Okay. Come back when you have groceries to log."

    async def _greet(self, trigger: str) -> str:
        items = self.data.get("items") or []
        if not items:
            return (
                "PantryPro here. Tell me what's in the pantry or fridge, "
                "like pasta, tomato sauce, and canned beans."
            )
        due = self._expiring(3)
        stock = self._headline_stock()
        if due:
            names = _join_and([i.get("name") for i, _ in due[:3]])
            self.pending = {"type": "recipes_offer"}
            return f"Welcome back. {names} should be used soon. Want recipe ideas?"
        self.pending = {"type": "recipes_offer"}
        return f"You have {stock}. Want recipe ideas?"

    def _is_generic_trigger(self, text: str) -> bool:
        t = _norm(text)
        generic = {
            "pantry", "pantry pro", "pantrypro", "pantry assistant",
            "open pantry", "food inventory",
        }
        return t in generic or not t

    async def run(self):
        try:
            if not await self._load():
                await self.capability_worker.speak(
                    "I couldn't load your pantry safely, so I won't change anything "
                    "this session. Try again in a moment."
                )
                return

            trigger = self._trigger_text()
            self._log(f"started. trigger={trigger!r} items={len(self.data.get('items') or [])}")

            handled_up_front = False
            if trigger and not self._is_generic_trigger(trigger) and not self._is_exit(trigger):
                result = self._refine_result(self.classify(trigger), trigger)
                intent = (result.get("intent") or "unknown").lower()
                if intent not in ("unknown", "exit", ""):
                    reply = await self._dispatch(result)
                    if reply == "__exit__":
                        await self.capability_worker.speak(self._signoff())
                        return
                    await self.capability_worker.speak(reply)
                    handled_up_front = True
                    if not self.pending:
                        await self.capability_worker.speak("Anything else for the pantry?")

            if not handled_up_front:
                await self.capability_worker.speak(await self._greet(trigger))

            idle_count = 0
            while True:
                try:
                    user_input = await self.capability_worker.user_response()

                    if not user_input:
                        idle_count += 1
                        if idle_count >= 2:
                            await self.capability_worker.speak(
                                "Still here if you need the pantry. Otherwise I'll sign off."
                            )
                            follow = await self.capability_worker.user_response()
                            if not follow or self._is_exit(follow):
                                await self.capability_worker.speak(self._signoff())
                                break
                            user_input = follow
                            idle_count = 0
                        else:
                            continue

                    idle_count = 0

                    if self.pending:
                        pending_reply = await self._handle_pending(user_input)
                        if pending_reply:
                            await self.capability_worker.speak(pending_reply)
                            continue

                    if self._is_exit(user_input):
                        await self.capability_worker.speak(self._signoff())
                        break

                    result = self._refine_result(self.classify(user_input), user_input)
                    self._log(
                        f"intent={result.get('intent')} items={result.get('items')} "
                        f"full_list={result.get('full_list')}"
                    )
                    reply = await self._dispatch(result)
                    if reply == "__exit__":
                        await self.capability_worker.speak(self._signoff())
                        break
                    await self.capability_worker.speak(reply)

                except Exception as e:
                    self._err(f"turn error: {e}")
                    await self.capability_worker.speak(
                        "Something glitched. Try that again?"
                    )
                    continue

        except Exception as e:
            self._err(f"run error: {e}")
            try:
                await self.capability_worker.speak("PantryPro hit a snag. Back to the agent.")
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()


def _shop_tail(shopping: list) -> str:
    if not shopping:
        return "Shopping list is still empty."
    return f"List now has {_join_and(shopping)}."
