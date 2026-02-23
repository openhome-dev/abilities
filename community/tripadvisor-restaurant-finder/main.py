import json
import os
import re
from typing import List, Optional

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# CONFIGURATION
# =============================================================================

API_BASE_URL = "https://tripadvisor16.p.rapidapi.com"
API_HOST = "tripadvisor16.p.rapidapi.com"
# Get your free API key at: https://rapidapi.com/DataCrawler/api/tripadvisor16
RAPIDAPI_KEY = "REPLACE_WITH_YOUR_KEY"

PREFS_FILE = "tripadvisor_prefs.json"

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye",
    "goodbye", "leave", "nothing", "no thanks", "i'm good", "im good",
}

PRICE_LEVEL_MAP = {
    "$": "budget-friendly",
    "$$": "moderate",
    "$$ - $$$": "moderate to upscale",
    "$$$": "upscale",
    "$$$$": "fine dining",
}

# =============================================================================
# LLM PROMPTS
# =============================================================================

PARSE_SEARCH_PROMPT = (
    "Extract restaurant search parameters from the user's speech. "
    "Return ONLY valid JSON with these keys: "
    '{"location": "string", "cuisine": "string", "price_filter": "string"}.\n'
    "Rules:\n"
    "- location = city, neighborhood, or area name. Strip 'in', 'near', 'around' prefixes.\n"
    "- cuisine = food type keyword (Italian, sushi, Thai, Mexican, BBQ, seafood, vegan, etc.) or empty string.\n"
    "- price_filter = 'cheap' if user said cheap/affordable/budget, 'fancy' if upscale/nice/fancy, or empty string.\n"
    "- If no location detected, set location to empty string.\n"
    "- 'Chinese', 'Japanese', 'Indian', 'Korean', 'Thai', 'Mexican', 'Italian', 'French' "
    "are CUISINES not locations. Default to cuisine when it's a food-related word.\n"
)

INTENT_ROUTER_PROMPT = (
    "Classify the user's restaurant-related request. "
    "Return ONLY valid JSON: "
    '{"intent": "search|details|reviews|more|exit|unknown", "reference": "string"}.\n'
    "Rules:\n"
    "- 'search' = finding restaurants (mentions location, cuisine, 'find', 'search', 'where to eat').\n"
    "- 'details' = wants more info about a specific restaurant ('tell me more', 'details on', 'number two').\n"
    "- 'reviews' = wants reviews ('reviews for', 'what do people say about').\n"
    "- 'more' = wants to hear more results from last search ('more', 'next', 'hear more').\n"
    "- 'exit' = wants to stop ('done', 'bye', 'stop', 'that's all').\n"
    "- 'unknown' = not restaurant related.\n"
    "- 'reference' = the restaurant name or number mentioned (e.g., 'number two', 'Uchi', '2'), or empty string.\n"
)

VOICE_FORMAT_PROMPT = (
    "Rewrite this restaurant description for spoken voice output. "
    "Keep it to one concise sentence. Do not add any information that wasn't in the original."
)


# =============================================================================
# MAIN CLASS
# =============================================================================


class TripAdvisorRestaurantCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    initial_request: Optional[str] = None

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

    # Do not change following tag
    #{{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.prefs = {}
        self.recent_results = []
        self.recent_search_query = ""
        self.results_shown_count = 0

        # Capture initial transcription (3-fallback pattern)
        self.initial_request = None
        try:
            self.initial_request = worker.transcription
        except Exception:
            pass
        if not self.initial_request:
            try:
                self.initial_request = worker.last_transcription
            except Exception:
                pass
        if not self.initial_request:
            try:
                self.initial_request = worker.current_transcription
            except Exception:
                pass

        self.worker.session_tasks.create(self.run())

    # =========================================================================
    # LOGGING HELPERS
    # =========================================================================

    def _log_info(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.info(f"[TripAdvisor] {msg}")

    def _log_error(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.error(f"[TripAdvisor] {msg}")

    def _log_warning(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.warning(f"[TripAdvisor] {msg}")

    # =========================================================================
    # JSON CLEANING
    # =========================================================================

    def _clean_json(self, raw: str) -> str:
        """Strip markdown fences and extract JSON object from LLM response."""
        cleaned = (raw or "").strip().replace("```json", "").replace("```", "").strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            return cleaned[start : end + 1]
        return cleaned

    # =========================================================================
    # PERSISTENCE LAYER
    # =========================================================================

    async def _load_prefs(self) -> dict:
        """Load persistent preferences, or return defaults if first run."""
        try:
            exists = await self.capability_worker.check_if_file_exists(
                PREFS_FILE, False
            )
            if exists:
                raw = await self.capability_worker.read_file(PREFS_FILE, False)
                return json.loads(raw)
        except json.JSONDecodeError:
            self._log_error("Corrupt prefs file, resetting")
            await self.capability_worker.delete_file(PREFS_FILE, False)
        except Exception as e:
            self._log_error(f"Load prefs error: {e}")
        return {}

    async def _save_prefs(self, prefs: dict):
        """Save prefs using delete-then-write pattern for JSON."""
        try:
            exists = await self.capability_worker.check_if_file_exists(
                PREFS_FILE, False
            )
            if exists:
                await self.capability_worker.delete_file(PREFS_FILE, False)
            await self.capability_worker.write_file(
                PREFS_FILE, json.dumps(prefs), False
            )
        except Exception as e:
            self._log_error(f"Save prefs error: {e}")

    # =========================================================================
    # FIRST-RUN SETUP
    # =========================================================================

    async def _run_first_time_setup(self) -> dict:
        """Collect and validate RapidAPI key. Returns prefs dict or empty on failure."""
        has_key = await self.capability_worker.run_confirmation_loop(
            "To find restaurants, I need a RapidAPI key for TripAdvisor. Do you have one?"
        )

        if not has_key:
            await self.capability_worker.speak(
                "No problem. Go to rapidapi dot com, create a free account, "
                "then search for TripAdvisor16 and subscribe to the free plan. "
                "Your API key will be in your RapidAPI dashboard. "
                "Come back when you have it."
            )
            return {}

        key_input = await self.capability_worker.run_io_loop(
            "Great. Read me your RapidAPI key."
        )

        if not key_input or not key_input.strip():
            await self.capability_worker.speak("I didn't catch that. Try again next time.")
            return {}

        api_key = key_input.strip()

        # Validate with a test call
        await self.capability_worker.speak("Let me verify that key.")
        valid = self._validate_api_key(api_key)

        if not valid:
            await self.capability_worker.speak(
                "That key didn't work. Double-check it on your RapidAPI dashboard "
                "and make sure you're subscribed to the TripAdvisor16 API."
            )
            return {}

        await self.capability_worker.speak(
            "You're connected. I can now search TripAdvisor for restaurants."
        )

        prefs = {
            "rapidapi_key": api_key,
            "default_location": "",
            "default_location_id": "",
            "location_cache": {},
        }

        # Optional: ask for default city
        wants_default = await self.capability_worker.run_confirmation_loop(
            "Would you like to set a default city for restaurant searches?"
        )

        if wants_default:
            city_input = await self.capability_worker.run_io_loop(
                "What city do you usually want restaurant recommendations for?"
            )
            if city_input and city_input.strip():
                city = city_input.strip()
                location_id = self._search_location(api_key, city)
                if location_id:
                    prefs["default_location"] = city
                    prefs["default_location_id"] = location_id
                    prefs["location_cache"] = {city.lower(): location_id}
                    await self.capability_worker.speak(
                        f"Got it. {city} is your default. You can always search other cities too."
                    )
                else:
                    await self.capability_worker.speak(
                        "I couldn't find that location, but that's fine. "
                        "You can tell me the city each time you search."
                    )

        await self._save_prefs(prefs)
        return prefs

    def _validate_api_key(self, api_key: str) -> bool:
        """Test the API key with a searchLocation call for 'New York'."""
        try:
            headers = {
                "X-RapidAPI-Key": api_key,
                "X-RapidAPI-Host": API_HOST,
            }
            resp = requests.get(
                f"{API_BASE_URL}/api/v1/restaurant/searchLocation",
                headers=headers,
                params={"query": "New York"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                return bool(data)
            self._log_error(f"Key validation returned {resp.status_code}")
            return False
        except Exception as e:
            self._log_error(f"Key validation error: {e}")
            return False

    # =========================================================================
    # API HELPERS
    # =========================================================================

    def _get_api_headers(self, api_key: str) -> dict:
        """Build standard RapidAPI headers."""
        return {
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": API_HOST,
        }

    def _search_location(self, api_key: str, query: str) -> Optional[str]:
        """Convert a place name to a TripAdvisor locationId."""
        try:
            self._log_info(f"Searching location: {query}")
            resp = requests.get(
                f"{API_BASE_URL}/api/v1/restaurant/searchLocation",
                headers=self._get_api_headers(api_key),
                params={"query": query},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                # Navigate defensively — API structure may vary
                results = data.get("data", data) if isinstance(data, dict) else data
                if isinstance(results, list) and results:
                    location_id = str(
                        results[0].get("locationId", "")
                        or results[0].get("location_id", "")
                    )
                    if location_id:
                        self._log_info(f"Resolved '{query}' -> locationId={location_id}")
                        return location_id
                self._log_warning(f"No location results for: {query}")
                return None
            self._log_error(f"searchLocation returned {resp.status_code}")
            return None
        except Exception as e:
            self._log_error(f"searchLocation error: {e}")
            return None

    def _search_restaurants(self, api_key: str, location_id: str) -> List[dict]:
        """Search restaurants by locationId."""
        try:
            self._log_info(f"Searching restaurants for locationId: {location_id}")
            resp = requests.get(
                f"{API_BASE_URL}/api/v1/restaurant/searchRestaurants",
                headers=self._get_api_headers(api_key),
                params={"locationId": location_id},
                timeout=12,
            )
            if resp.status_code == 200:
                data = resp.json()
                # Try multiple possible response structures
                restaurants = (
                    data.get("data", {}).get("data", [])
                    if isinstance(data.get("data"), dict)
                    else data.get("data", [])
                )
                if not restaurants and isinstance(data, list):
                    restaurants = data
                self._log_info(f"Found {len(restaurants)} restaurants")
                return restaurants
            self._log_error(f"searchRestaurants returned {resp.status_code}")
            return []
        except Exception as e:
            self._log_error(f"searchRestaurants error: {e}")
            return []

    def _get_restaurant_details(self, api_key: str, restaurant_id: str) -> Optional[dict]:
        """Get full details for a specific restaurant."""
        try:
            self._log_info(f"Getting details for restaurant: {restaurant_id}")
            resp = requests.get(
                f"{API_BASE_URL}/api/v1/restaurant/getRestaurantDetails",
                headers=self._get_api_headers(api_key),
                params={"restaurantsId": restaurant_id},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
            self._log_error(f"getRestaurantDetails returned {resp.status_code}")
            return None
        except Exception as e:
            self._log_error(f"getRestaurantDetails error: {e}")
            return None

    def _get_restaurant_reviews(self, api_key: str, location_id: str) -> List[dict]:
        """Get reviews for a restaurant by its locationId."""
        try:
            self._log_info(f"Getting reviews for locationId: {location_id}")
            resp = requests.get(
                f"{API_BASE_URL}/api/v1/restaurant/getRestaurantReviewsByLocationId",
                headers=self._get_api_headers(api_key),
                params={"locationId": location_id},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                reviews = (
                    data.get("data", {}).get("data", [])
                    if isinstance(data.get("data"), dict)
                    else data.get("data", [])
                )
                if not reviews and isinstance(data, list):
                    reviews = data
                return reviews
            self._log_error(f"getReviews returned {resp.status_code}")
            return []
        except Exception as e:
            self._log_error(f"getReviews error: {e}")
            return []

    # =========================================================================
    # VOICE FORMATTING HELPERS
    # =========================================================================

    def _format_rating_for_voice(self, rating) -> str:
        """Convert numeric rating to voice-friendly string. 4.5 -> 'four point five out of five'."""
        number_words = {
            0: "zero", 1: "one", 2: "two", 3: "three",
            4: "four", 5: "five", 6: "six", 7: "seven",
            8: "eight", 9: "nine",
        }
        try:
            r = float(rating)
            whole = int(r)
            decimal = round((r - whole) * 10)
            whole_word = number_words.get(whole, str(whole))
            if decimal == 0:
                return f"{whole_word} out of five"
            decimal_word = number_words.get(decimal, str(decimal))
            return f"{whole_word} point {decimal_word} out of five"
        except (ValueError, TypeError):
            return str(rating) if rating else "not rated"

    def _format_price_for_voice(self, price_level) -> str:
        """Convert price symbols to voice-friendly description."""
        if not price_level:
            return "price not listed"
        cleaned = str(price_level).strip()
        return PRICE_LEVEL_MAP.get(cleaned, cleaned)

    def _format_cuisine_for_voice(self, cuisine_list) -> str:
        """Speak first two cuisine tags only."""
        if not cuisine_list:
            return ""
        if isinstance(cuisine_list, str):
            return cuisine_list
        if isinstance(cuisine_list, list):
            tags = []
            for c in cuisine_list[:2]:
                if isinstance(c, dict):
                    tags.append(c.get("text", c.get("name", str(c))))
                else:
                    tags.append(str(c))
            return " and ".join(tags) if tags else ""
        return str(cuisine_list)

    def _truncate_review(self, text: str, max_words: int = 20) -> str:
        """Truncate review text to max_words for voice output."""
        if not text:
            return ""
        words = text.split()
        if len(words) <= max_words:
            return text
        return " ".join(words[:max_words]) + "..."

    # =========================================================================
    # LLM-BASED PARSING
    # =========================================================================

    def _parse_search_input(self, user_input: str) -> dict:
        """Use LLM to extract location, cuisine, and price filter from natural speech."""
        result = {"location": "", "cuisine": "", "price_filter": ""}
        if not user_input or not user_input.strip():
            return result
        try:
            raw = self.capability_worker.text_to_text_response(
                f"{PARSE_SEARCH_PROMPT}\n\nUser said: {user_input.strip()}"
            )
            parsed = json.loads(self._clean_json(raw))
            result["location"] = str(parsed.get("location", "")).strip()
            result["cuisine"] = str(parsed.get("cuisine", "")).strip()
            result["price_filter"] = str(parsed.get("price_filter", "")).strip()
            self._log_info(f"Parsed search: {result}")
        except Exception as e:
            self._log_error(f"Parse search error: {e}")
        return result

    def _route_intent(self, user_input: str) -> dict:
        """Classify user intent for the conversation loop."""
        result = {"intent": "unknown", "reference": ""}
        if not user_input or not user_input.strip():
            return result

        # Quick keyword check for exit
        lower = user_input.lower().strip()
        if any(w in lower for w in EXIT_WORDS):
            return {"intent": "exit", "reference": ""}

        try:
            raw = self.capability_worker.text_to_text_response(
                f"{INTENT_ROUTER_PROMPT}\n\nUser said: {user_input.strip()}"
            )
            parsed = json.loads(self._clean_json(raw))
            intent = str(parsed.get("intent", "unknown")).strip().lower()
            if intent not in ("search", "details", "reviews", "more", "exit", "unknown"):
                intent = "unknown"
            result["intent"] = intent
            result["reference"] = str(parsed.get("reference", "")).strip()
            self._log_info(f"Routed intent: {result}")
        except Exception as e:
            self._log_error(f"Route intent error: {e}")
        return result

    # =========================================================================
    # RESTAURANT REFERENCE RESOLUTION
    # =========================================================================

    def _resolve_restaurant_reference(self, reference: str) -> Optional[dict]:
        """Match a user reference to a cached restaurant result."""
        if not self.recent_results or not reference:
            return None
        ref_lower = reference.lower().strip()

        # Try numeric references: "number two", "2", "the second one"
        number_words = {
            "one": 0, "first": 0, "1": 0,
            "two": 1, "second": 1, "2": 1,
            "three": 2, "third": 2, "3": 2,
            "four": 3, "fourth": 3, "4": 3,
            "five": 4, "fifth": 4, "5": 4,
        }
        for word, idx in number_words.items():
            if word in ref_lower and idx < len(self.recent_results):
                return self.recent_results[idx]

        # Try digit extraction
        digits = re.findall(r"\d+", ref_lower)
        if digits:
            idx = int(digits[0]) - 1
            if 0 <= idx < len(self.recent_results):
                return self.recent_results[idx]

        # Try fuzzy name match
        for restaurant in self.recent_results:
            name = (restaurant.get("name", "") or "").lower()
            if name and (name in ref_lower or ref_lower in name):
                return restaurant

        return None

    # =========================================================================
    # FILTER HELPERS
    # =========================================================================

    def _filter_by_cuisine(self, restaurants: List[dict], cuisine: str) -> List[dict]:
        """Filter restaurants by cuisine keyword."""
        cuisine_lower = cuisine.lower()
        filtered = []
        for r in restaurants:
            cuisine_list = r.get("cuisines", []) or r.get("cuisine", []) or []
            if isinstance(cuisine_list, str):
                cuisine_list = [cuisine_list]
            cuisine_text = " ".join(
                c.get("text", c.get("name", str(c))) if isinstance(c, dict) else str(c)
                for c in cuisine_list
            ).lower()
            if cuisine_lower in cuisine_text:
                filtered.append(r)
        return filtered

    def _filter_by_price(self, restaurants: List[dict], price_filter: str) -> List[dict]:
        """Filter by price level. 'cheap' = $ or $$, 'fancy' = $$$ or $$$$."""
        filtered = []
        for r in restaurants:
            price = str(
                r.get("priceLevel", "")
                or r.get("price_level", "")
                or r.get("price", "")
                or ""
            ).strip()
            if price_filter == "cheap" and price in ("$", "$$"):
                filtered.append(r)
            elif price_filter == "fancy" and price in ("$$$", "$$$$"):
                filtered.append(r)
        return filtered

    # =========================================================================
    # MODE 1: FIND RESTAURANTS
    # =========================================================================

    async def _handle_search(self, user_input: str) -> None:
        """Mode 1: Find restaurants from user speech."""
        api_key = self.prefs.get("rapidapi_key", "")

        # Step 1: Parse location + cuisine from speech
        parsed = self._parse_search_input(user_input)
        location = parsed.get("location", "")
        cuisine = parsed.get("cuisine", "")
        price_filter = parsed.get("price_filter", "")

        # Step 2: If no location, try default, then ask
        if not location:
            default_loc = self.prefs.get("default_location", "")
            if default_loc:
                location = default_loc
                await self.capability_worker.speak(f"Searching in {location}.")
            else:
                location_input = await self.capability_worker.run_io_loop(
                    "What city or area should I search in?"
                )
                if not location_input or not location_input.strip():
                    await self.capability_worker.speak(
                        "I need a location to search. Try again."
                    )
                    return
                location = location_input.strip()

        # Step 3: Get locationId (check cache first to save API calls)
        location_key = location.lower()
        location_cache = self.prefs.get("location_cache", {})
        location_id = location_cache.get(location_key)

        if not location_id:
            await self.capability_worker.speak(f"Looking up {location}.")
            location_id = self._search_location(api_key, location)
            if not location_id:
                await self.capability_worker.speak(
                    f"I'm not sure where {location} is. "
                    "Try a city name like Austin, Texas."
                )
                return
            # Cache the location ID for future searches
            location_cache[location_key] = location_id
            self.prefs["location_cache"] = location_cache
            await self._save_prefs(self.prefs)

        # Step 4: Search restaurants
        await self.capability_worker.speak("Searching for restaurants now.")
        restaurants = self._search_restaurants(api_key, location_id)

        if not restaurants:
            await self.capability_worker.speak(
                f"I couldn't find any restaurants matching that in {location}. "
                "Try a different area or cuisine."
            )
            return

        # Step 5: Filter by cuisine if specified
        if cuisine:
            filtered = self._filter_by_cuisine(restaurants, cuisine)
            if filtered:
                restaurants = filtered

        # Step 6: Filter by price if specified
        if price_filter:
            filtered = self._filter_by_price(restaurants, price_filter)
            if filtered:
                restaurants = filtered

        # Step 7: Cache results for follow-up (Mode 2)
        self.recent_results = restaurants[:10]
        self.results_shown_count = 0
        self.recent_search_query = f"{cuisine} in {location}" if cuisine else location

        # Step 8: Speak top 3
        await self._speak_restaurant_results(restaurants[:3], location, start_index=0)
        self.results_shown_count = min(3, len(restaurants))

    async def _speak_restaurant_results(
        self, restaurants: List[dict], location: str, start_index: int = 0
    ) -> None:
        """Format and speak a list of restaurant results."""
        if not restaurants:
            await self.capability_worker.speak("No restaurants to report.")
            return

        if start_index == 0:
            intro = f"Here are the top restaurants in {location}. "
        else:
            intro = "Here are more options. "

        parts = [intro]

        for i, r in enumerate(restaurants, start=start_index + 1):
            name = r.get("name", "Unknown restaurant")
            rating = r.get("rating", r.get("averageRating", ""))
            num_reviews = r.get("num_reviews", r.get("userReviewCount", ""))
            price = r.get("priceLevel", r.get("price_level", ""))
            cuisines = r.get("cuisines", r.get("cuisine", []))

            rating_text = self._format_rating_for_voice(rating) if rating else "not rated"
            price_text = self._format_price_for_voice(price)
            cuisine_text = self._format_cuisine_for_voice(cuisines)

            entry = f"Number {i}: {name}, rated {rating_text}"
            if num_reviews:
                entry += f" with {num_reviews} reviews"
            entry += f". It's {price_text}"
            if cuisine_text:
                entry += f", serving {cuisine_text}"
            entry += ". "
            parts.append(entry)

        # Add follow-up hint
        total_cached = len(self.recent_results) if self.recent_results else 0
        shown_so_far = start_index + len(restaurants)
        if total_cached > shown_so_far:
            parts.append("Want to hear more, or ask about any of these?")
        else:
            parts.append("Want details or reviews on any of these?")

        await self.capability_worker.speak("".join(parts))

    # =========================================================================
    # MODE 2: RESTAURANT DETAILS + REVIEWS
    # =========================================================================

    async def _handle_details(self, reference: str) -> None:
        """Mode 2: Get and speak detailed info about a specific restaurant."""
        restaurant = self._resolve_restaurant_reference(reference)
        if not restaurant:
            await self.capability_worker.speak(
                "I'm not sure which restaurant you mean. "
                "Try saying the number, like 'number one', or the restaurant name."
            )
            return

        api_key = self.prefs.get("rapidapi_key", "")
        name = restaurant.get("name", "that restaurant")
        restaurant_id = str(
            restaurant.get("restaurantsId", "")
            or restaurant.get("location_id", "")
            or restaurant.get("locationId", "")
        )

        if not restaurant_id:
            await self.capability_worker.speak(
                f"I don't have enough info to look up {name}. Try searching again."
            )
            return

        await self.capability_worker.speak(f"Getting details on {name}.")
        details = self._get_restaurant_details(api_key, restaurant_id)

        if not details:
            await self.capability_worker.speak(
                f"Sorry, I couldn't get details for {name}. Try again in a moment."
            )
            return

        await self._speak_restaurant_details(details, name)

    async def _speak_restaurant_details(self, details: dict, name: str) -> None:
        """Format and speak restaurant details."""
        detail_data = details.get("data", details) if isinstance(details, dict) else details
        if isinstance(detail_data, dict):
            address = (
                detail_data.get("address", "")
                or detail_data.get("address_obj", {}).get("address_string", "")
            )
            rating = detail_data.get("rating", "")
            num_reviews = detail_data.get("num_reviews", detail_data.get("userReviewCount", ""))
            price = detail_data.get("price_level", detail_data.get("priceLevel", ""))
            description = detail_data.get("description", "")
            cuisines = detail_data.get("cuisine", detail_data.get("cuisines", []))
        else:
            address = rating = num_reviews = price = description = ""
            cuisines = []

        parts = []
        cuisine_text = self._format_cuisine_for_voice(cuisines)
        if cuisine_text:
            parts.append(f"{name} is a {cuisine_text} restaurant")
        else:
            parts.append(f"{name} is a restaurant")

        if address:
            parts.append(f" in {address}")
        parts.append(". ")

        if rating:
            parts.append(f"Rated {self._format_rating_for_voice(rating)}")
            if num_reviews:
                parts.append(f" based on {num_reviews} reviews")
            parts.append(". ")

        if price:
            parts.append(f"Price range is {self._format_price_for_voice(price)}. ")

        if description:
            short_desc = self.capability_worker.text_to_text_response(
                f"{VOICE_FORMAT_PROMPT}\n\nDescription: {description[:500]}"
            )
            if short_desc and short_desc.strip():
                parts.append(short_desc.strip() + " ")

        await self.capability_worker.speak("".join(parts))

    async def _handle_reviews(self, reference: str) -> None:
        """Fetch and speak top 2 reviews for a restaurant."""
        restaurant = self._resolve_restaurant_reference(reference)
        if not restaurant:
            await self.capability_worker.speak(
                "Which restaurant do you want reviews for? "
                "Say the number or name."
            )
            return

        api_key = self.prefs.get("rapidapi_key", "")
        name = restaurant.get("name", "that restaurant")
        location_id = str(
            restaurant.get("location_id", "")
            or restaurant.get("locationId", "")
            or restaurant.get("restaurantsId", "")
        )

        if not location_id:
            await self.capability_worker.speak(
                f"I don't have enough info to get reviews for {name}."
            )
            return

        await self.capability_worker.speak(f"Getting reviews for {name}.")
        reviews = self._get_restaurant_reviews(api_key, location_id)

        if not reviews:
            await self.capability_worker.speak(f"I couldn't find reviews for {name}.")
            return

        # Prioritize high-rated recent reviews (5 or 4 stars)
        sorted_reviews = sorted(
            reviews,
            key=lambda r: (float(r.get("rating", 0) or 0), r.get("published_date", "")),
            reverse=True,
        )

        # Speak max 2 review excerpts
        parts = [f"Here's what people are saying about {name}. "]
        for review in sorted_reviews[:2]:
            title = review.get("title", "")
            text = review.get("text", "")
            if title:
                parts.append(
                    f"One reviewer titled their review '{self._truncate_review(title, 10)}'. "
                )
            elif text:
                parts.append(
                    f"A reviewer said: '{self._truncate_review(text, 20)}'. "
                )

        if len(parts) == 1:
            parts.append("No detailed reviews available.")

        await self.capability_worker.speak("".join(parts))

    # =========================================================================
    # MAIN CONVERSATION LOOP
    # =========================================================================

    async def run(self):
        """Main entry point: setup -> initial query -> conversation loop -> exit."""
        try:
            if self.worker:
                await self.worker.session_tasks.sleep(0.2)

            # Step 1: Load prefs
            self.prefs = await self._load_prefs()

            # Step 2: First-run setup if no API key
            if not self.prefs.get("rapidapi_key"):
                self.prefs = await self._run_first_time_setup()
                if not self.prefs.get("rapidapi_key"):
                    return

            # Step 3: Determine initial input
            initial_input = (self.initial_request or "").strip()

            # Step 4: If initial input has a search query, process it immediately
            if initial_input:
                # Check if it looks like a restaurant search
                search_keywords = [
                    "restaurant", "find", "search", "where", "eat", "food",
                    "dinner", "lunch", "brunch", "sushi", "italian", "mexican",
                    "thai", "chinese", "indian", "best", "good", "cheap", "fancy",
                ]
                lower_input = initial_input.lower()
                looks_like_search = any(kw in lower_input for kw in search_keywords)

                if looks_like_search:
                    await self._handle_search(initial_input)
                else:
                    await self.capability_worker.speak(
                        "Welcome to the restaurant finder. "
                        "Tell me a city and cuisine, like 'Italian restaurants in Austin'. "
                        "Or ask about a restaurant by name. Say stop when you're done."
                    )
            else:
                await self.capability_worker.speak(
                    "Welcome to the restaurant finder. "
                    "Tell me a city and optionally a cuisine, "
                    "like 'find sushi in San Francisco'. Say stop when you're done."
                )

            # Step 5: Conversation loop
            idle_count = 0
            max_turns = 10

            for _ in range(max_turns):
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    idle_count += 1
                    if idle_count >= 2:
                        await self.capability_worker.speak(
                            "Seems like you're all set. Happy dining!"
                        )
                        break
                    continue

                idle_count = 0
                input_lower = user_input.lower().strip()

                # Quick exit check
                if any(w in input_lower for w in EXIT_WORDS):
                    await self.capability_worker.speak("Happy dining! Goodbye.")
                    break

                # Route intent
                route = self._route_intent(user_input)
                intent = route["intent"]
                reference = route["reference"]

                if intent == "search":
                    await self._handle_search(user_input)

                elif intent == "details":
                    await self._handle_details(reference or user_input)

                elif intent == "reviews":
                    await self._handle_reviews(reference or user_input)

                elif intent == "more":
                    if self.recent_results and self.results_shown_count < len(
                        self.recent_results
                    ):
                        next_batch = self.recent_results[
                            self.results_shown_count : self.results_shown_count + 3
                        ]
                        await self._speak_restaurant_results(
                            next_batch,
                            self.recent_search_query,
                            start_index=self.results_shown_count,
                        )
                        self.results_shown_count += len(next_batch)
                    else:
                        await self.capability_worker.speak(
                            "No more results to show. Try a new search."
                        )

                elif intent == "exit":
                    await self.capability_worker.speak("Happy dining! Goodbye.")
                    break

                else:
                    await self.capability_worker.speak(
                        "I can find restaurants, get details, or read reviews. "
                        "Try saying something like 'find Thai food in Brooklyn'."
                    )

        except Exception as e:
            self._log_error(f"Unexpected error: {e}")
            if self.capability_worker:
                await self.capability_worker.speak(
                    "Sorry, something went wrong with the restaurant finder. "
                    "Please try again."
                )
        finally:
            if self.capability_worker:
                self.capability_worker.resume_normal_flow()
