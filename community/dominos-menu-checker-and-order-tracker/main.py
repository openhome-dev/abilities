import json
import os

import asyncio
import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


# =============================================================================
# CONFIGURATION & CONSTANTS
# =============================================================================

COUNTRY_USA = 'us'

VOICE_ID = "pNInz6obpgDQGcFmaJgB"

EXIT_WORDS = {
    "stop", "exit", "quit", "cancel", "never mind",
    "go back", "goodbye", "bye",
}

DONE_WORDS = {
    "done", "finished", "that's all", "that's it",
    "nothing else", "no more", "I'm good",
}

TRACK_WORDS = {
    "track my order", "track order", "check my order",
    "check order", "order status", "where's my order",
    "track", "tracking",
}

SAVED_INFO_FILE = "pizza_checker_location.json"

SIZE_MAP = {
    "small": "10",
    "medium": "12",
    "large": "14",
    "xlarge": "16",
    "x-large": "16",
    "extra large": "16",
}


# =============================================================================
# LLM PROMPT TEMPLATES
# =============================================================================

PARSE_ADDRESS_PROMPT = """Extract a US location from the user's spoken input.
Return ONLY a JSON object with these fields:
- "street": string (street address including number)
- "city": string
- "region": string (2-letter US state code, e.g. "CA")
- "zip": string (5-digit ZIP code, or empty string if not provided)

User said: "{user_input}"

Return ONLY valid JSON, no other text."""

MENU_SEARCH_PROMPT = """The user wants to look up food from Domino's Pizza.
User said: "{user_input}"

Extract search parameters as a JSON object:
- "keywords": list of SINGLE-WORD name keywords to search (e.g. ["Pepperoni"], ["Coke"], ["BBQ", "Chicken", "Wings"], ["Hawaiian"]). Each keyword must be ONE word. Do NOT combine words like "Hawaiian Style" — split them into ["Hawaiian", "Style"].
- "size": one of "small", "medium", "large", "xlarge", or "" if not specified

Return ONLY valid JSON, no other text."""

MENU_SELECT_PROMPT = """The user wants: "{user_request}"

Here are matching Domino's menu items:
{items_list}

Return ONLY the item code that best matches what the user wants. Return just the code string, nothing else."""

CONFIRM_INTENT_PROMPT = """Does the user's response mean "yes" or "no"?
User said: "{user_input}"

Return ONLY a JSON object: {{"confirmed": true}} or {{"confirmed": false}}"""

PRICE_SUMMARY_PROMPT = """Summarize these Domino's menu items and their prices in a natural, spoken way (2-3 sentences max).
Items:
{items}

Keep it conversational, like you're reading it back to someone."""

PARSE_PHONE_PROMPT = """Extract a US phone number from the user's spoken input.
Return ONLY a JSON object with:
- "phone": string (10-digit US phone number, digits only, no dashes or spaces)

If no valid phone number is found, return {{"phone": ""}}

User said: "{user_input}"

Return ONLY valid JSON, no other text."""

TRACK_SUMMARY_PROMPT = """Summarize this pizza delivery tracking data in 1-2 spoken sentences.
Keep it conversational, like you're updating someone on their order status.

Tracking data: {tracking_data}"""


# =============================================================================
# CAPABILITY CLASS (must be the first class in the file for OpenHome)
# =============================================================================

class OrderPizzaCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # State
    address: object = None
    store: object = None
    store_phone: str = ""
    menu: object = None
    checked_items: list = []
    saved_location: dict = None

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

        # Reset state
        self.address = None
        self.store = None
        self.store_phone = ""
        self.menu = None
        self.checked_items = []
        self.saved_location = None

        self.worker.session_tasks.create(self.run_main_flow())

    # =========================================================================
    # HELPERS
    # =========================================================================

    async def speak(self, text: str):
        await self.capability_worker.text_to_speech(text, VOICE_ID)

    def log(self, msg: str):
        self.worker.editor_logging_handler.info(f"[PizzaChecker] {msg}")

    def log_error(self, msg: str):
        self.worker.editor_logging_handler.error(f"[PizzaChecker] {msg}")

    def is_exit(self, text: str) -> bool:
        if not text:
            return False
        lower = text.lower().strip()
        return any(w in lower for w in EXIT_WORDS)

    def is_done(self, text: str) -> bool:
        if not text:
            return False
        lower = text.lower().strip()
        return any(w in lower for w in DONE_WORDS)

    def is_track(self, text: str) -> bool:
        if not text:
            return False
        lower = text.lower().strip()
        return any(w in lower for w in TRACK_WORDS)

    def llm(self, prompt: str) -> str:
        return self.capability_worker.text_to_text_response(prompt)

    def parse_json_response(self, raw: str) -> dict:
        """Parse JSON from LLM output, stripping markdown fences."""
        clean = raw.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(clean)
        except Exception:
            self.log_error(f"Failed to parse LLM JSON: {clean[:200]}")
            return None

    def is_affirmative(self, text: str) -> bool:
        """Use LLM to determine if user said yes/no."""
        if not text:
            return False
        quick_yes = ["yes", "yeah", "yep", "yup", "sure", "correct",
                     "right", "ok", "okay", "absolutely", "definitely"]
        if text.lower().strip() in quick_yes:
            return True
        quick_no = ["no", "nah", "nope", "not really"]
        if text.lower().strip() in quick_no:
            return False
        result = self.parse_json_response(
            self.llm(CONFIRM_INTENT_PROMPT.format(user_input=text))
        )
        return result.get("confirmed", False) if result else False

    # =========================================================================
    # LOCATION PERSISTENCE
    # =========================================================================

    async def load_saved_location(self) -> dict:
        try:
            exists = await self.capability_worker.check_if_file_exists(SAVED_INFO_FILE, False)
            if not exists:
                return None
            raw = await self.capability_worker.read_file(SAVED_INFO_FILE, False)
            return json.loads(raw)
        except Exception as e:
            self.log_error(f"Failed to load saved location: {e}")
        return None

    async def save_location(self, data: dict):
        try:
            await self.capability_worker.delete_file(SAVED_INFO_FILE, False)
            await self.capability_worker.write_file(
                SAVED_INFO_FILE, json.dumps(data), False
            )
            self.log("Location saved.")
        except Exception as e:
            self.log_error(f"Failed to save location: {e}")

    # =========================================================================
    # DOMINO'S API WRAPPERS
    # =========================================================================

    async def find_nearest_store(self, street, city, region, zip_code):
        """Find the closest open Domino's store. Returns (Store, Address) or (None, None)."""
        try:
            address = Address(street, city, region, zip_code)
            store = await asyncio.to_thread(address.closest_store)
            self.log(f"Found store ID {store.id}")
            return store, address
        except Exception as e:
            err = str(e)
            if "No local stores" in err:
                self.log(f"No stores found near {street}, {city}")
            else:
                self.log_error(f"Store lookup failed: {e}")
            return None, None

    def search_variants(self, menu, keywords, size=""):
        """Search menu variants directly (bypasses broken menu.search())."""
        results = []
        size_code = SIZE_MAP.get(size, size) if size else ""

        for code, v in menu.variants.items():
            name = v.get("Name", "").lower()
            if all(kw.lower() in name for kw in keywords):
                if not size_code or v.get("SizeCode", "") == size_code:
                    results.append({
                        "code": v["Code"],
                        "name": v.get("Name", "Unknown"),
                        "price": v.get("Price", "0.00"),
                        "size": v.get("SizeCode", ""),
                    })
        return results

    async def get_item_price(self, store, customer, address, item_code):
        """Price a single item by sending it through the price endpoint."""
        try:
            order = await asyncio.to_thread(Order, store, customer, address)
            order.add_item(item_code)
            response = await asyncio.to_thread(
                order._send, order.urls.price_url(), True
            )
            if response.get('Status') == -1:
                return None
            amounts = order.data.get("Amounts", {})
            return {
                "menu_price": order.data["Products"][0].get("Price", "0.00"),
                "item_total": amounts.get("Menu", 0),
                "delivery_fee": amounts.get("Surcharge", 0),
                "tax": amounts.get("Tax", 0),
                "total": amounts.get("Customer", 0),
            }
        except Exception as e:
            self.log_error(f"Price check failed: {e}")
            return None

    # =========================================================================
    # ORDER TRACKING
    # =========================================================================

    async def check_tracking(self, phone):
        """Check order tracking status by phone number."""
        try:
            result = await asyncio.to_thread(track_by_phone, phone)
            return result
        except Exception as e:
            self.log_error(f"Tracking failed: {e}")
            return None

    async def track_order_flow(self):
        """Voice flow for tracking an order by phone number."""
        await self.speak(
            "Sure! What's the phone number associated with your order?"
        )

        for attempt in range(3):
            response = await self.capability_worker.user_response()
            if not response:
                await self.speak("I didn't catch that. What's the phone number?")
                continue
            if self.is_exit(response):
                return

            parsed = self.parse_json_response(
                self.llm(PARSE_PHONE_PROMPT.format(user_input=response))
            )
            phone = parsed.get("phone", "") if parsed else ""

            if not phone or len(phone) < 10:
                await self.speak(
                    "I couldn't get a valid phone number from that. "
                    "Please say your 10-digit phone number."
                )
                continue

            await self.speak("Checking on your order...")
            tracking = await self.check_tracking(phone)

            if tracking:
                tracking_str = json.dumps(tracking) if isinstance(tracking, (dict, list)) else str(tracking)
                summary = self.llm(
                    TRACK_SUMMARY_PROMPT.format(tracking_data=tracking_str[:500])
                )
                await self.speak(summary)
            else:
                await self.speak(
                    "I couldn't find any orders for that phone number. "
                    "Double-check the number and try again, or say 'done' to skip."
                )
                continue
            return

        await self.speak("Having trouble with the phone number. Let's move on.")

    # =========================================================================
    # MAIN FLOW
    # =========================================================================

    async def run_main_flow(self):
        try:
            # Phase 1: Greeting + location
            self.saved_location = await self.load_saved_location()

            if self.saved_location:
                addr = self.saved_location
                addr_str = f"{addr.get('street', '')}, {addr.get('city', '')}, {addr.get('region', '')}"
                await self.speak(
                    f"Domino's menu checker! Want to use your saved location at {addr_str}? "
                    "Or say a new address."
                )
                response = await self.capability_worker.user_response()
                if self.is_exit(response):
                    await self.speak("No problem, maybe next time!")
                    self.capability_worker.resume_normal_flow()
                    return

                if self.is_affirmative(response):
                    self.address = Address(
                        addr.get("street", ""),
                        addr.get("city", ""),
                        addr.get("region", ""),
                        addr.get("zip", ""),
                    )
                else:
                    self.address = None
            else:
                await self.speak(
                    "Domino's menu checker! I can look up menu items and prices "
                    "from your nearest Domino's. What's your address or location?"
                )

            # Phase 2: Address collection (if needed)
            if not self.address:
                if not await self.collect_address():
                    self.capability_worker.resume_normal_flow()
                    return

            # Phase 3: Store lookup
            await self.speak("Finding your nearest Domino's...")
            self.store, api_address = await self.find_nearest_store(
                self.address.street,
                self.address.city,
                self.address.region,
                self.address.zip,
            )
            if not self.store:
                await self.speak(
                    "I couldn't find any open Domino's stores near that address. "
                    "Would you like to try a different address?"
                )
                retry = await self.capability_worker.user_response()
                if retry and self.is_affirmative(retry):
                    self.address = None
                    if not await self.collect_address():
                        self.capability_worker.resume_normal_flow()
                        return
                    self.store, api_address = await self.find_nearest_store(
                        self.address.street,
                        self.address.city,
                        self.address.region,
                        self.address.zip,
                    )
                    if not self.store:
                        await self.speak("Still no stores found. Try again later.")
                        self.capability_worker.resume_normal_flow()
                        return
                else:
                    await self.speak("Okay, exiting menu checker.")
                    self.capability_worker.resume_normal_flow()
                    return

            if api_address:
                self.address = api_address

            # Get store details
            try:
                store_details = await asyncio.to_thread(self.store.get_details)
                store_name = store_details.get("AddressDescription", f"Store #{self.store.id}")
                self.store_phone = store_details.get("Phone", "")
            except Exception as e:
                self.log_error(f"Failed to get store details: {e}")
                store_name = f"Store #{self.store.id}"
                self.store_phone = ""
            phone_msg = f" Their phone number is {self.store_phone}." if self.store_phone else ""
            await self.speak(
                f"Your nearest Domino's is {store_name}.{phone_msg} "
                "Loading their menu now..."
            )

            # Load menu
            try:
                self.menu = await asyncio.to_thread(self.store.get_menu)
                self.log(f"Menu loaded: {len(self.menu.variants)} variants")
            except Exception as e:
                self.log_error(f"Failed to load menu: {e}")
                await self.speak(
                    "I couldn't load the menu for this store. "
                    "Try again later by saying 'check Domino's menu'."
                )
                self.capability_worker.resume_normal_flow()
                return

            # Offer to save location
            if not self.saved_location:
                await self.speak("Want me to save this location for next time?")
                save_resp = await self.capability_worker.user_response()
                if self.is_affirmative(save_resp):
                    await self.save_location({
                        "street": self.address.street,
                        "city": self.address.city,
                        "region": self.address.region,
                        "zip": self.address.zip,
                    })
                    await self.speak("Saved!")

            # Phase 4: Menu browsing loop
            await self.speak(
                "What would you like to look up? You can say things like "
                "'how much is a large pepperoni pizza' or 'show me chicken wings'. "
                "Just let me know when you're done!"
            )
            await self.browse_menu()

        except Exception as e:
            self.log_error(f"Unexpected error in menu checker: {e}")
            await self.speak(
                "Something went wrong. Sorry about that. "
                "You can try again by saying 'check Domino's menu'."
            )

        self.capability_worker.resume_normal_flow()

    # =========================================================================
    # PHASE 2: ADDRESS COLLECTION
    # =========================================================================

    async def collect_address(self) -> bool:
        """Collect and validate address. Returns True on success."""
        for attempt in range(3):
            if attempt > 0:
                await self.speak("What's your address or location?")

            response = await self.capability_worker.user_response()
            if not response:
                await self.speak("I didn't catch that. Could you say the address again?")
                continue
            if self.is_exit(response):
                await self.speak("Exiting menu checker.")
                return False

            parsed = self.parse_json_response(
                self.llm(PARSE_ADDRESS_PROMPT.format(user_input=response))
            )

            if not parsed or not parsed.get("street") or not parsed.get("city"):
                await self.speak(
                    "I didn't catch a full address. "
                    "Please include the street, city, and state."
                )
                continue

            addr_str = f"{parsed['street']}, {parsed['city']}, {parsed.get('region', '')}"
            if parsed.get("zip"):
                addr_str += f" {parsed['zip']}"

            await self.speak(f"I heard: {addr_str}. Is that correct?")
            confirm = await self.capability_worker.user_response()

            if self.is_exit(confirm):
                await self.speak("Exiting menu checker.")
                return False

            if self.is_affirmative(confirm):
                self.address = Address(
                    parsed["street"],
                    parsed["city"],
                    parsed.get("region", ""),
                    parsed.get("zip", ""),
                )
                self.log(f"Address set: {addr_str}")
                return True
            else:
                await self.speak("Let's try again.")

        await self.speak("I'm having trouble with the address. Try again later.")
        return False

    # =========================================================================
    # PHASE 4: MENU BROWSING
    # =========================================================================

    async def browse_menu(self):
        """Interactive menu browsing loop."""
        while True:
            response = await self.capability_worker.user_response()
            if not response:
                continue

            # Check for tracking request mid-browse
            if self.is_track(response):
                await self.track_order_flow()
                await self.speak(
                    "Is there anything else I can help with? "
                    "You can keep looking up menu items, or say 'done' to finish."
                )
                continue

            if self.is_exit(response) or self.is_done(response):
                if self.checked_items:
                    items_text = "\n".join(
                        f"- {item['name']}: ${item['price']}"
                        for item in self.checked_items
                    )
                    summary = self.llm(PRICE_SUMMARY_PROMPT.format(items=items_text))
                    await self.speak(f"Here's a recap of what you looked up: {summary}")

                # Give store link and phone for ordering
                order_link = f"https://www.dominos.com/en/pages/order/#!/locations/store/{self.store.id}/"
                await self.speak(
                    f"If you'd like to order, you can go to {order_link}"
                )
                if self.store_phone:
                    await self.speak(
                        f"Or call the store directly at {self.store_phone}."
                    )

                # Offer order tracking
                await self.speak(
                    "Or if you've already placed an order and want to track it, "
                    "give me the phone number associated with the order. "
                    "Otherwise, say 'no' and I'll wrap up."
                )
                track_resp = await self.capability_worker.user_response()
                if track_resp and not self.is_exit(track_resp):
                    lower = track_resp.lower().strip()
                    if lower not in ("no", "nah", "nope", "no thanks"):
                        # They gave a phone number or said yes — run tracking
                        parsed = self.parse_json_response(
                            self.llm(PARSE_PHONE_PROMPT.format(user_input=track_resp))
                        )
                        phone = parsed.get("phone", "") if parsed else ""
                        if phone and len(phone) >= 10:
                            await self.speak("Checking on your order...")
                            tracking = await self.check_tracking(phone)
                            if tracking:
                                tracking_str = json.dumps(tracking) if isinstance(tracking, (dict, list)) else str(tracking)
                                summary = self.llm(
                                    TRACK_SUMMARY_PROMPT.format(tracking_data=tracking_str[:500])
                                )
                                await self.speak(summary)
                            else:
                                await self.speak(
                                    "I couldn't find any orders for that phone number."
                                )
                        else:
                            # They said something like "yes" — ask for the number
                            await self.track_order_flow()

                        # After tracking, ask if they need more help
                        await self.speak("Do you need any more help?")
                        more_help = await self.capability_worker.user_response()
                        if more_help and self.is_affirmative(more_help):
                            await self.speak(
                                "Sure! What would you like to look up?"
                            )
                            continue

                await self.speak("Thanks for using the Domino's menu checker!")
                return

            # Parse what the user wants to look up
            search_params = self.parse_json_response(
                self.llm(MENU_SEARCH_PROMPT.format(user_input=response))
            )

            if not search_params or not search_params.get("keywords"):
                await self.speak(
                    "I didn't understand that. Try something like "
                    "'large pepperoni pizza' or 'chicken wings' or 'two liter coke'."
                )
                continue

            keywords = search_params.get("keywords", [])
            size = search_params.get("size", "")
            self.log(f"Menu search: keywords={keywords}, size={size}")

            # Search
            results = self.search_variants(self.menu, keywords, size)

            if not results and size:
                results = self.search_variants(self.menu, keywords)

            if not results and len(keywords) > 1:
                # Try each keyword individually
                for kw in keywords:
                    results = self.search_variants(self.menu, [kw], size)
                    if results:
                        break
                if not results:
                    for kw in keywords:
                        results = self.search_variants(self.menu, [kw])
                        if results:
                            break

            # Last resort: split multi-word keywords into individual words
            if not results:
                split_kws = []
                for kw in keywords:
                    split_kws.extend(kw.split())
                split_kws = [w for w in split_kws if len(w) > 2]
                if split_kws != keywords:
                    for kw in split_kws:
                        results = self.search_variants(self.menu, [kw], size)
                        if results:
                            break
                    if not results:
                        for kw in split_kws:
                            results = self.search_variants(self.menu, [kw])
                            if results:
                                break

            if not results:
                await self.speak(
                    "I couldn't find anything matching that on the menu. "
                    "Try describing it differently, like 'pepperoni' or 'wings'."
                )
                continue

            # Present results
            if len(results) == 1:
                item = results[0]
                size_label = f" (size {item['size']})" if item['size'] else ""
                await self.speak(
                    f"{item['name']}{size_label} is ${item['price']}. "
                    "Want to look up anything else?"
                )
                self.checked_items.append(item)

            elif len(results) <= 5:
                options_parts = []
                for r in results:
                    size_label = f" size {r['size']}" if r['size'] else ""
                    options_parts.append(f"{r['name']}{size_label} for ${r['price']}")
                options_text = ". ".join(options_parts)
                await self.speak(
                    f"I found {len(results)} options: {options_text}. "
                    "Want details on any of these, or look up something else?"
                )
                self.checked_items.extend(results)

            else:
                # Many results — show top matches via LLM
                items_text = "\n".join(
                    f"- {r['code']}: {r['name']} ${r['price']}"
                    for r in results[:10]
                )
                best_code = self.llm(
                    MENU_SELECT_PROMPT.format(
                        user_request=response, items_list=items_text
                    )
                ).strip()
                best = next(
                    (r for r in results if r["code"] == best_code), results[0]
                )
                await self.speak(
                    f"I found {len(results)} matches. The best match is "
                    f"{best['name']} for ${best['price']}. "
                    f"There are {len(results) - 1} other options too. "
                    "Want to hear more, or look up something else?"
                )
                self.checked_items.append(best)

                # If user wants more
                followup = await self.capability_worker.user_response()
                if not followup:
                    continue
                if self.is_exit(followup) or self.is_done(followup):
                    break
                more_lower = followup.lower().strip()
                if "more" in more_lower or "other" in more_lower or "yes" in more_lower:
                    top5 = results[:5]
                    listing = ". ".join(
                        f"{r['name']}: ${r['price']}" for r in top5
                    )
                    await self.speak(
                        f"Here are the top options: {listing}. "
                        "What else would you like to look up?"
                    )
                    self.checked_items.extend(top5)
                elif more_lower in ("no", "nah", "nope", "no thanks", "nope thanks"):
                    await self.speak("What else would you like to look up?")


# =============================================================================
# DOMINO'S API CLASSES (inlined for OpenHome single-file deployment)
# =============================================================================

class _Urls(object):
    def __init__(self, country=COUNTRY_USA):
        self.country = country
        self.urls = {
            COUNTRY_USA: {
                'find_url': 'https://order.dominos.com/power/store-locator?s={line1}&c={line2}&type={type}',
                'info_url': 'https://order.dominos.com/power/store/{store_id}/profile',
                'menu_url': 'https://order.dominos.com/power/store/{store_id}/menu?lang={lang}&structured=true',
                'place_url': 'https://order.dominos.com/power/place-order',
                'price_url': 'https://order.dominos.com/power/price-order',
                'track_root': 'https://tracker.dominos.com/tracker-presentation-service/',
                'track_path': 'v2/orders',
                'validate_url': 'https://order.dominos.com/power/validate-order',
            },
        }

    def find_url(self):
        return self.urls[self.country]['find_url']

    def info_url(self):
        return self.urls[self.country]['info_url']

    def menu_url(self):
        return self.urls[self.country]['menu_url']

    def price_url(self):
        return self.urls[self.country]['price_url']

    def validate_url(self):
        return self.urls[self.country]['validate_url']

    def track_by_phone_url(self, phone):
        root = self.urls[self.country]['track_root']
        path = self.urls[self.country]['track_path']
        return f'{root}{path}?phonenumber={phone}'

    def track_detail_url(self, track_action):
        root = self.urls[self.country]['track_root']
        return f'{root}{track_action}'


def _request_json(url, **kwargs):
    r = requests.get(url.format(**kwargs), timeout=15)
    r.raise_for_status()
    return r.json()


def track_by_phone(phone, country=COUNTRY_USA):
    """Track order by phone using Domino's v2 JSON tracker API."""
    phone = str(phone).strip()
    urls = _Urls(country)
    headers = {'Accept': 'application/json'}

    # Step 1: Look up orders by phone number
    r = requests.get(urls.track_by_phone_url(phone), headers=headers, timeout=15)
    r.raise_for_status()
    orders = r.json()

    if not orders or not isinstance(orders, list) or len(orders) == 0:
        return None

    # Step 2: Get detailed tracking from first order's Track action
    first_order = orders[0]
    track_action = first_order.get('Actions', {}).get('Track')
    if not track_action:
        return first_order  # Return basic info if no track action

    detail_url = urls.track_detail_url(track_action)
    r2 = requests.get(detail_url, headers=headers, timeout=15)
    r2.raise_for_status()
    return r2.json()


class Customer(object):
    def __init__(self, fname='', lname='', email='', phone=''):
        self.first_name = fname.strip()
        self.last_name = lname.strip()
        self.email = email.strip()
        self.phone = str(phone).strip()


class _MenuItem(object):
    def __init__(self, data={}):
        self.code = data['Code']
        self.name = data['Name']
        self.menu_data = data
        self.categories = []


class _Menu(object):
    def __init__(self, data={}, country=COUNTRY_USA):
        self.variants = data.get('Variants', {})
        self.menu_by_code = {}
        self.root_categories = {}
        self.country = COUNTRY_USA
        if self.variants:
            self.products = self._parse_items(data['Products'])
            self.coupons = self._parse_items(data['Coupons'])
            self.preconfigured = self._parse_items(data['PreconfiguredProducts'])

    @classmethod
    def from_store(cls, store_id, lang='en', country=COUNTRY_USA):
        response = _request_json(_Urls(country).menu_url(), store_id=store_id, lang=lang)
        return cls(response)

    def _parse_items(self, parent_data):
        items = []
        for code in parent_data.keys():
            obj = _MenuItem(parent_data[code])
            self.menu_by_code[obj.code] = obj
            items.append(obj)
        return items


class Store(object):
    def __init__(self, data={}, country=COUNTRY_USA):
        self.id = str(data.get('StoreID', -1))
        self.country = country
        self.urls = _Urls(country)
        self.data = data

    def get_details(self):
        return _request_json(self.urls.info_url(), store_id=self.id)

    def get_menu(self, lang='en'):
        response = _request_json(self.urls.menu_url(), store_id=self.id, lang=lang)
        return _Menu(response, self.country)


class Address(object):
    def __init__(self, street, city, region='', zip='', country=COUNTRY_USA, *args):
        self.street = street.strip()
        self.city = city.strip()
        self.region = region.strip()
        self.zip = str(zip).strip()
        self.urls = _Urls(country)
        self.country = country

    @property
    def data(self):
        return {'Street': self.street, 'City': self.city,
                'Region': self.region, 'PostalCode': self.zip}

    @property
    def line1(self):
        return '{Street}'.format(**self.data)

    @property
    def line2(self):
        return '{City}, {Region}, {PostalCode}'.format(**self.data)

    def nearby_stores(self, service='Delivery'):
        data = _request_json(self.urls.find_url(), line1=self.line1, line2=self.line2, type=service)
        return [Store(x, self.country) for x in data['Stores']
                if x['IsOnlineNow'] and x['ServiceIsOpen'][service]]

    def closest_store(self, service='Delivery'):
        stores = self.nearby_stores(service=service)
        if not stores:
            raise Exception('No local stores are currently open')
        return stores[0]


class Order(object):
    """Minimal Order class — only used for pricing items via the price endpoint."""

    def __init__(self, store, customer, address, country=COUNTRY_USA):
        self.store = store
        self.menu = _Menu.from_store(store_id=store.id, country=country)
        self.customer = customer
        self.address = address
        self.urls = _Urls(country)
        self.data = {
            'Address': {'Street': self.address.street, 'City': self.address.city,
                        'Region': self.address.region, 'PostalCode': self.address.zip,
                        'Type': 'House'},
            'Coupons': [], 'CustomerID': '', 'Extension': '',
            'OrderChannel': 'OLO', 'OrderID': '', 'NoCombine': True,
            'OrderMethod': 'Web', 'OrderTaker': None, 'Payments': [],
            'Products': [], 'Market': '', 'Currency': '',
            'ServiceMethod': 'Delivery', 'Tags': {}, 'Version': '1.0',
            'SourceOrganizationURI': 'order.dominos.com', 'LanguageCode': 'en',
            'Partners': {}, 'NewUser': True, 'metaData': {}, 'Amounts': {},
            'BusinessDate': '', 'EstimatedWaitMinutes': '',
            'PriceOrderTime': '', 'AmountsBreakdown': {}
        }

    def add_item(self, code, qty=1, options=[]):
        item = self.menu.variants[code]
        item.update(ID=1, isNew=True, Qty=qty, AutoRemove=False)
        self.data['Products'].append(item)
        return item

    def _send(self, url, merge):
        self.data.update(
            StoreID=self.store.id, Email=self.customer.email,
            FirstName=self.customer.first_name, LastName=self.customer.last_name,
            Phone=self.customer.phone,
        )
        for key in ('Products', 'StoreID', 'Address'):
            if key not in self.data or not self.data[key]:
                raise Exception('order has invalid value for key "%s"' % key)
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }
        r = requests.post(url=url, headers=headers, json={'Order': self.data}, timeout=30)
        r.raise_for_status()
        json_data = r.json()
        if merge:
            for key, value in json_data['Order'].items():
                if value or not isinstance(value, list):
                    self.data[key] = value
        return json_data
