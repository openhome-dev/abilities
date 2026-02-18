import asyncio
import json
import os

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# REDCAST HERITAGE STOCK CHECKER
# A personal watchlist for clothing items on redcastheritage.com.
# Add items you're eyeing, check if your size is still in stock, and get
# spoken updates — all by voice. Uses the Shopify JSON API (no scraping).
# =============================================================================

BASE_URL = "https://redcastheritage.com"
CATALOG_URL = f"{BASE_URL}/collections/all/products.json?limit=250"
STORAGE_FILE = "redcast_watchlist.json"

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave",
    "nothing else", "all good", "nope", "no thanks",
    "i'm good", "that's all", "all done", "finished",
}

FILLER_LINES = [
    "One sec, checking that for you.",
    "Hang on, pulling that up.",
    "Let me check the site real quick.",
]

INTENT_SYSTEM_PROMPT = (
    "You are a clothing stock checker intent classifier. "
    "Given user input, determine the intent. Return ONLY valid JSON, no other text."
)

INTENT_PROMPT = """Classify this stock checker command. Return ONLY JSON in this exact format:
{{"intent": "<intent>", "item": "<item_description>", "size": "<size_or_empty>"}}

Possible intents:
- "add" — user wants to add/watch an item (e.g. "watch the Samurai jeans in 31", "add the chore coat", "keep an eye on the IH flannel in large")
- "check" — user wants to check stock for a specific item (e.g. "are the Samurai jeans in stock?", "check the chore coat", "is the Iron Heart flannel in medium in stock?", "do they have the 710 jeans in 32?")
- "check_all" — user wants to check all watchlist items (e.g. "check everything", "how's my whole list looking?", "check all my items")
- "sizes" — user wants to see all available sizes for the last checked item (e.g. "what sizes are left?", "show me all sizes", "what's available?")
- "list" — user wants to hear the watchlist (e.g. "what's on my list?", "read my watchlist", "what am I watching?")
- "remove" — user wants to remove an item (e.g. "remove the Samurai jeans", "take off the chore coat", "delete that one")
- "clear" — user wants to clear the entire watchlist (e.g. "clear my list", "remove everything", "start fresh")
- "exit" — user wants to leave (e.g. "done", "stop", "bye", "that's all")
- "unknown" — not a stock checker command

Rules:
- For "add", "check", and "remove", extract the item description into "item" (lowercase, brand + model if mentioned).
- For "add" and "check", extract the size into "size" if mentioned (e.g. "31", "medium", "L"). Leave empty string if not mentioned.
- For other intents, set "item" and "size" to empty strings.

User said: "{input}"
"""

MATCH_SYSTEM_PROMPT = (
    "You are a product matcher. Given a user's description of a clothing item "
    "and a list of products from a store, find the best match. "
    "Return ONLY valid JSON, no other text."
)

MATCH_PROMPT = """Find the best matching product for this description.

IMPORTANT: The user is speaking, so model numbers may be transcribed incorrectly:
- "634" might sound like "six thirty four" or "six three four"
- "IH" might sound like "I H" or "eye aitch"
- Hyphens and spaces are often missing or added randomly
- Be VERY forgiving with model numbers and codes
- Focus on brand + general description (e.g., "jeans", "chore coat", "flannel")

Return ONLY JSON: {{"handle": "<product_handle>", "title": "<product_title>", "confidence": "<high|medium|low>"}}

If no product is a reasonable match, return: {{"handle": "", "title": "", "confidence": "none"}}

User is looking for: "{description}"

Available products:
{product_list}
"""

WATCHLIST_MATCH_PROMPT = """Match the user's request to one of their watchlist items.
Check both the official product name AND what the user originally called it when they added it.

Return ONLY JSON: {{"key": "<watchlist_key>", "confidence": "<high|medium|low>"}}

If no item matches, return: {{"key": "", "confidence": "none"}}

User said: "{input}"

Watchlist items:
{watchlist_items}
"""


class RedcastStockCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    watchlist: dict = None
    last_checked_handle: str = None
    filler_index: int = 0

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
        self.watchlist = {}
        self.last_checked_handle = None
        self.filler_index = 0
        self.worker.session_tasks.create(self.run())

    # ── Helpers ──────────────────────────────────────────────────────────

    def log(self, msg):
        self.worker.editor_logging_handler.info(f"[Redcast] {msg}")

    def log_err(self, msg):
        self.worker.editor_logging_handler.error(f"[Redcast] {msg}")

    async def speak_filler(self):
        line = FILLER_LINES[self.filler_index % len(FILLER_LINES)]
        self.filler_index += 1
        await self.capability_worker.speak(line)

    def parse_llm_json(self, raw: str) -> dict:
        clean = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)

    # ── Persistence ──────────────────────────────────────────────────────

    async def load_watchlist(self):
        try:
            if await self.capability_worker.check_if_file_exists(STORAGE_FILE, False):
                raw = await self.capability_worker.read_file(STORAGE_FILE, False)
                self.watchlist = json.loads(raw)
                self.log(f"Loaded {len(self.watchlist)} items")
            else:
                self.watchlist = {}
        except Exception as e:
            self.log_err(f"Load failed: {e}")
            self.watchlist = {}

    async def save_watchlist(self):
        try:
            if await self.capability_worker.check_if_file_exists(STORAGE_FILE, False):
                await self.capability_worker.delete_file(STORAGE_FILE, False)
            await self.capability_worker.write_file(
                STORAGE_FILE, json.dumps(self.watchlist), False
            )
            self.log(f"Saved {len(self.watchlist)} items")
        except Exception as e:
            self.log_err(f"Save failed: {e}")

    # ── LLM Classification ───────────────────────────────────────────────

    def classify_intent(self, user_input: str) -> dict:
        prompt = INTENT_PROMPT.format(input=user_input)
        raw = self.capability_worker.text_to_text_response(
            prompt, system_prompt=INTENT_SYSTEM_PROMPT
        )
        try:
            result = self.parse_llm_json(raw)
            if "intent" not in result:
                result["intent"] = "unknown"
            return result
        except Exception as e:
            self.log_err(f"Intent parse failed: {e} | Raw: {raw}")
            return {"intent": "unknown", "item": "", "size": ""}

    def match_product(self, description: str, products: list) -> dict:
        product_list = "\n".join(
            f'- "{p["title"]}" (handle: {p["handle"]}, vendor: {p["vendor"]})'
            for p in products
        )
        prompt = MATCH_PROMPT.format(
            description=description, product_list=product_list
        )
        raw = self.capability_worker.text_to_text_response(
            prompt, system_prompt=MATCH_SYSTEM_PROMPT
        )
        try:
            return self.parse_llm_json(raw)
        except Exception as e:
            self.log_err(f"Product match failed: {e}")
            return {"handle": "", "title": "", "confidence": "none"}

    def match_watchlist_item(self, user_input: str) -> str:
        if not self.watchlist:
            return ""
        items_str = "\n".join(
            f'- key: "{k}", official: "{v["label"]}", user called it: "{v.get("user_label", "")}", size: {v.get("size", "any")}'
            for k, v in self.watchlist.items()
        )
        prompt = WATCHLIST_MATCH_PROMPT.format(
            input=user_input, watchlist_items=items_str
        )
        raw = self.capability_worker.text_to_text_response(
            prompt, system_prompt=INTENT_SYSTEM_PROMPT
        )
        try:
            result = self.parse_llm_json(raw)
            if result.get("confidence") != "none":
                return result.get("key", "")
        except Exception as e:
            self.log_err(f"Watchlist match failed: {e}")
        return ""

    # ── Shopify API ──────────────────────────────────────────────────────

    def fetch_product(self, handle: str) -> dict | None:
        try:
            url = f"{BASE_URL}/products/{handle}.js"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            self.log_err(f"HTTP {resp.status_code} for {url}")
            return None
        except Exception as e:
            self.log_err(f"Fetch product error: {e}")
            return None

    def fetch_catalog(self) -> list:
        try:
            resp = requests.get(CATALOG_URL, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                return [
                    {
                        "title": p["title"],
                        "handle": p["handle"],
                        "vendor": p.get("vendor", ""),
                    }
                    for p in data.get("products", [])
                ]
            self.log_err(f"Catalog HTTP {resp.status_code}")
            return []
        except Exception as e:
            self.log_err(f"Catalog fetch error: {e}")
            return []

    def get_stock_info(self, product_data: dict, target_size: str = "") -> dict:
        variants = product_data.get("variants", [])
        all_sizes = []
        in_stock = []
        out_of_stock = []
        target_available = None

        for v in variants:
            size = v.get("option1") or v.get("title", "")
            available = v.get("available", False)
            all_sizes.append(size)
            if available:
                in_stock.append(size)
            else:
                out_of_stock.append(size)
            if target_size and size.lower() == target_size.lower():
                target_available = available

        return {
            "all_sizes": all_sizes,
            "in_stock": in_stock,
            "out_of_stock": out_of_stock,
            "target_available": target_available,
        }

    # ── Intent Handlers ──────────────────────────────────────────────────

    async def handle_add(self, item_desc: str, size: str):
        if not item_desc:
            item_desc = await self.capability_worker.run_io_loop(
                "What item do you want to watch?"
            )
            if not item_desc:
                await self.capability_worker.speak("I didn't catch that.")
                return

        await self.speak_filler()
        catalog = await asyncio.to_thread(self.fetch_catalog)
        if not catalog:
            await self.capability_worker.speak(
                "I couldn't reach the Redcast site. Try again in a bit."
            )
            return

        match = self.match_product(item_desc, catalog)
        if not match.get("handle"):
            await self.capability_worker.speak(
                "I couldn't find a matching product on Redcast. "
                "Try describing it differently."
            )
            return

        title = match["title"]
        handle = match["handle"]
        confidence = match.get("confidence", "high")

        # Always confirm, but phrase it based on confidence
        if confidence == "high":
            confirmed = await self.capability_worker.run_confirmation_loop(
                f"Found {title}. That the one?"
            )
        else:
            # Medium or low confidence - be more explicit
            confirmed = await self.capability_worker.run_confirmation_loop(
                f"I found {title}. Is that what you meant?"
            )

        if not confirmed:
            await self.capability_worker.speak("Okay, try describing it differently.")
            return

        if not size:
            size = await self.capability_worker.run_io_loop(
                "What size should I watch for? Or say any for all sizes."
            )
            if not size:
                size = "any"

        size_clean = size.strip().lower()
        if size_clean == "any":
            key = handle
        else:
            key = f"{handle}-{size_clean}"

        # Store both official title and what the user called it
        self.watchlist[key] = {
            "label": title,
            "user_label": item_desc,  # What they originally said
            "handle": handle,
            "size": size_clean,
            "url": f"{BASE_URL}/products/{handle}",
        }
        await self.save_watchlist()

        if size_clean == "any":
            await self.capability_worker.speak(
                f"Added {title} to your watchlist. I'll check all sizes."
            )
        else:
            await self.capability_worker.speak(
                f"Added {title} in size {size_clean} to your watchlist."
            )

    async def handle_check(self, item_desc: str, size: str):
        if not item_desc:
            item_desc = await self.capability_worker.run_io_loop(
                "What item do you want to check?"
            )
            if not item_desc:
                await self.capability_worker.speak("I didn't catch that.")
                return

        # Step 1: Try matching against the watchlist first (fast path)
        key = ""
        if self.watchlist:
            if len(self.watchlist) == 1:
                # With one item, check if the description plausibly matches
                key = self.match_watchlist_item(item_desc)
            else:
                key = self.match_watchlist_item(item_desc)

        if key and key in self.watchlist:
            # Found on watchlist — use the saved handle directly
            entry = self.watchlist[key]
            await self.speak_filler()
            product = await asyncio.to_thread(self.fetch_product, entry["handle"])
            if not product:
                await self.capability_worker.speak(
                    "I couldn't reach the Redcast site right now. Try again in a bit."
                )
                return

            self.last_checked_handle = entry["handle"]
            target_size = size if size else entry.get("size", "")
            stock = self.get_stock_info(product, target_size)
            label = entry["label"]

            await self._speak_stock_result(label, target_size, stock)
            return

        # Step 2: Not on watchlist — search the catalog (slower path)
        await self.speak_filler()
        catalog = await asyncio.to_thread(self.fetch_catalog)
        if not catalog:
            await self.capability_worker.speak(
                "I couldn't reach the Redcast site. Try again in a bit."
            )
            return

        match = self.match_product(item_desc, catalog)
        if not match.get("handle"):
            await self.capability_worker.speak(
                "I couldn't find a matching product on Redcast. "
                "Try describing it differently."
            )
            return

        handle = match["handle"]
        title = match["title"]

        product = await asyncio.to_thread(self.fetch_product, handle)
        if not product:
            await self.capability_worker.speak(
                "Found the product but couldn't load stock data. Try again in a bit."
            )
            return

        self.last_checked_handle = handle
        stock = self.get_stock_info(product, size)
        await self._speak_stock_result(title, size, stock)

    async def _speak_stock_result(self, label: str, target_size: str, stock: dict):
        if target_size and target_size != "any" and stock["target_available"] is not None:
            if stock["target_available"]:
                await self.capability_worker.speak(
                    f"Size {target_size} of {label} is in stock."
                )
            else:
                if stock["in_stock"]:
                    nearby = ", ".join(stock["in_stock"][:4])
                    await self.capability_worker.speak(
                        f"Size {target_size} is sold out. "
                        f"Available sizes: {nearby}. Want the full list?"
                    )
                else:
                    await self.capability_worker.speak(
                        f"Size {target_size} is sold out and so is everything else."
                    )
        else:
            if stock["in_stock"]:
                count = len(stock["in_stock"])
                await self.capability_worker.speak(
                    f"{label} has {count} sizes in stock. Want me to list them?"
                )
            else:
                await self.capability_worker.speak(
                    f"{label} is completely sold out."
                )

    async def handle_check_all(self):
        if not self.watchlist:
            await self.capability_worker.speak(
                "Your watchlist is empty. Say add to watch an item."
            )
            return

        await self.speak_filler()
        results = []

        for key, entry in self.watchlist.items():
            product = await asyncio.to_thread(self.fetch_product, entry["handle"])
            if not product:
                results.append(f"{entry['label']}: couldn't check.")
                continue

            stock = self.get_stock_info(product, entry.get("size", ""))
            target_size = entry.get("size", "")
            label = entry["label"]

            if target_size and target_size != "any" and stock["target_available"] is not None:
                status = "in stock" if stock["target_available"] else "sold out"
                results.append(f"{label} size {target_size}: {status}.")
            else:
                count = len(stock["in_stock"])
                results.append(f"{label}: {count} sizes available.")

        # Speak in chunks of 2-3 to keep it digestible
        for i in range(0, len(results), 2):
            chunk = " ".join(results[i:i + 2])
            await self.capability_worker.speak(chunk)

    async def handle_sizes(self):
        if not self.last_checked_handle:
            await self.capability_worker.speak(
                "Check an item first, then ask about sizes."
            )
            return

        await self.speak_filler()
        product = await asyncio.to_thread(
            self.fetch_product, self.last_checked_handle
        )
        if not product:
            await self.capability_worker.speak(
                "Couldn't reach the site right now."
            )
            return

        stock = self.get_stock_info(product)
        title = product.get("title", "that item")

        if stock["in_stock"]:
            sizes_str = ", ".join(stock["in_stock"])
            await self.capability_worker.speak(
                f"Available sizes for {title}: {sizes_str}."
            )
        else:
            await self.capability_worker.speak(
                f"{title} is completely sold out."
            )

        if stock["out_of_stock"]:
            out_str = ", ".join(stock["out_of_stock"])
            await self.capability_worker.speak(
                f"Sold out: {out_str}."
            )

    async def handle_list(self):
        if not self.watchlist:
            await self.capability_worker.speak(
                "Your watchlist is empty. Say add to start watching items."
            )
            return

        count = len(self.watchlist)
        await self.capability_worker.speak(
            f"You have {count} item{'s' if count != 1 else ''} on your watchlist."
        )

        for entry in self.watchlist.values():
            size = entry.get("size", "any")
            if size and size != "any":
                await self.capability_worker.speak(
                    f"{entry['label']}, size {size}."
                )
            else:
                await self.capability_worker.speak(f"{entry['label']}, all sizes.")

    async def handle_remove(self, item_desc: str):
        if not self.watchlist:
            await self.capability_worker.speak("Your watchlist is already empty.")
            return

        if len(self.watchlist) == 1:
            key = list(self.watchlist.keys())[0]
        else:
            key = self.match_watchlist_item(item_desc) if item_desc else ""
            if not key or key not in self.watchlist:
                await self.capability_worker.speak(
                    "I'm not sure which item you mean. Say list to hear your watchlist."
                )
                return

        label = self.watchlist[key]["label"]
        confirmed = await self.capability_worker.run_confirmation_loop(
            f"Remove {label} from your watchlist?"
        )
        if confirmed:
            del self.watchlist[key]
            await self.save_watchlist()
            await self.capability_worker.speak(f"Removed {label}.")
        else:
            await self.capability_worker.speak("Okay, keeping it.")

    async def handle_clear(self):
        if not self.watchlist:
            await self.capability_worker.speak("Your watchlist is already empty.")
            return

        confirmed = await self.capability_worker.run_confirmation_loop(
            f"Clear all {len(self.watchlist)} items from your watchlist?"
        )
        if confirmed:
            self.watchlist.clear()
            await self.save_watchlist()
            await self.capability_worker.speak("Watchlist cleared.")
        else:
            await self.capability_worker.speak("Okay, keeping your watchlist.")

    # ── Main Loop ────────────────────────────────────────────────────────

    async def run(self):
        await self.load_watchlist()

        if self.watchlist:
            count = len(self.watchlist)
            await self.capability_worker.speak(
                f"Welcome back. You have {count} item{'s' if count != 1 else ''} "
                "on your watchlist. Check stock, add items, or say done."
            )
        else:
            await self.capability_worker.speak(
                "Redcast stock checker open. "
                "You can add items to watch or check stock. Say done when finished."
            )

        idle_count = 0

        try:
            while True:
                try:
                    user_input = await self.capability_worker.user_response()

                    if not user_input:
                        idle_count += 1
                        if idle_count >= 2:
                            await self.capability_worker.speak(
                                "Still here if you need anything. "
                                "Otherwise I'll close up."
                            )
                            follow_up = await self.capability_worker.user_response()
                            if not follow_up or any(
                                w in (follow_up or "").lower() for w in EXIT_WORDS
                            ):
                                await self._speak_goodbye()
                                break
                            else:
                                user_input = follow_up
                                idle_count = 0
                        else:
                            continue

                    idle_count = 0

                    lower_input = user_input.lower().strip()
                    if any(w in lower_input for w in EXIT_WORDS):
                        await self._speak_goodbye()
                        break

                    result = self.classify_intent(user_input)
                    intent = result.get("intent", "unknown")
                    item = result.get("item", "")
                    size = result.get("size", "")

                    self.log(f"Intent: {intent}, Item: {item}, Size: {size}")

                    if intent == "add":
                        await self.handle_add(item, size)
                    elif intent == "check":
                        await self.handle_check(item, size)
                    elif intent == "check_all":
                        await self.handle_check_all()
                    elif intent == "sizes":
                        await self.handle_sizes()
                    elif intent == "list":
                        await self.handle_list()
                    elif intent == "remove":
                        await self.handle_remove(item)
                    elif intent == "clear":
                        await self.handle_clear()
                    elif intent == "exit":
                        await self._speak_goodbye()
                        break
                    else:
                        await self.capability_worker.speak(
                            "I can add items, check stock, list your watchlist, "
                            "or remove items. What would you like?"
                        )

                except Exception as e:
                    self.log_err(f"Loop error: {e}")
                    await self.capability_worker.speak(
                        "Something went wrong. Let's try that again."
                    )
                    continue

        finally:
            self.capability_worker.resume_normal_flow()

    async def _speak_goodbye(self):
        count = len(self.watchlist)
        if count > 0:
            await self.capability_worker.speak(
                f"Watchlist saved with {count} item{'s' if count != 1 else ''}. "
                "See you next time."
            )
        else:
            await self.capability_worker.speak("See you next time.")
