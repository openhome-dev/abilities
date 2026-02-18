import json
import os
import asyncio
import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# REDCAST HERITAGE BROWSER
# Browse available items by brand, category, and size on redcastheritage.com
# "Show me large shirts from Iron Heart" or "What hats are available?"
# =============================================================================

BASE_URL = "https://redcastheritage.com"
CATALOG_URL = f"{BASE_URL}/collections/all/products.json?limit=250"

FILTER_SYSTEM_PROMPT = (
    "You are a product filter assistant. Extract the brand, category, and size "
    "from the user's request. Return ONLY valid JSON, no other text."
)

FILTER_PROMPT = """Extract the brand, category, and size from this request.

Return ONLY JSON: {{"brand": "<brand_name or empty>", "category": "<category or empty>", "size": "<size or empty>"}}

Common brands on Redcast Heritage:
- Iron Heart (also "IH")
- Samurai Jeans (also just "Samurai")
- Warehouse & Co (also "Warehouse")
- The Flat Head
- Buzz Rickson's
- Redcast (the store's own brand)

Categories - BE SPECIFIC:
- "t-shirt" or "tee" = t-shirts only (not button-ups, not flannels)
- "shirt" = any shirt (button-ups, work shirts, flannels, etc.)
- "jeans" or "denim" = jeans/denim pants
- "jacket" = jackets
- "hat" = hats
- etc.

Sizes: S, M, L, XL, XXL, XXXL, or numbers like 30, 31, 32, etc.

IMPORTANT for sizes:
- If you hear "X L" or "extra large", write it as "XL"
- If you hear "X X L" or "double X L", write it as "XXL"
- If you hear just "X", it probably means "XL"
- Always write sizes without spaces: "XL" not "X L"

IMPORTANT for brands:
- "Samurai Jeans" or "Samurai" should be extracted as "Samurai"
- Don't default to "Redcast" unless the user specifically mentions it
- If no brand is mentioned, leave it as an empty string ""

IMPORTANT for categories:
- If user says "t-shirt" or "tee", write "t-shirt" (not just "shirt")
- If user says "flannel" or "button-up", write "shirt" (generic)
- Be specific when the user is specific

If something isn't mentioned, leave it as an empty string.

User said: "{input}"
"""


class RedcastBrowserCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

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

    def log(self, msg):
        self.worker.editor_logging_handler.info(f"[Redcast] {msg}")

    def log_err(self, msg):
        self.worker.editor_logging_handler.error(f"[Redcast] {msg}")

    def parse_llm_json(self, raw: str) -> dict:
        clean = raw.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(clean)
        except (json.JSONDecodeError, ValueError):
            return {}

    def fetch_catalog(self) -> list:
        try:
            resp = requests.get(CATALOG_URL, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("products", [])
            self.log_err(f"Catalog HTTP {resp.status_code}")
            return []
        except Exception as e:
            self.log_err(f"Catalog fetch error: {e}")
            return []

    def extract_filters(self, user_input: str) -> dict:
        prompt = FILTER_PROMPT.format(input=user_input)
        raw = self.capability_worker.text_to_text_response(
            prompt, system_prompt=FILTER_SYSTEM_PROMPT
        )
        return self.parse_llm_json(raw)

    def filter_products(self, products: list, brand: str, category: str, size: str) -> list:
        """Filter products by brand, category, and size availability."""
        results = []
        
        for p in products:
            title = p.get("title", "").lower()
            vendor = p.get("vendor", "").lower()
            product_type = p.get("product_type", "").lower()
            
            # Filter by brand (check both vendor and title)
            if brand:
                brand_lower = brand.lower()
                # Remove "jeans" from brand name for matching (e.g., "samurai jeans" -> "samurai")
                brand_clean = brand_lower.replace(" jeans", "").replace(" denim", "").strip()
                if brand_clean not in vendor and brand_clean not in title:
                    continue
            
            # Filter by category (check product_type and title)
            if category:
                category_lower = category.lower()
                
                # Normalize category variations
                if category_lower in ["t-shirt", "tshirt", "tee", "t shirt"]:
                    category_lower = "t-shirt"
                elif category_lower in ["button up", "button-up", "dress shirt", "work shirt"]:
                    category_lower = "button-shirt"
                
                # Check if category matches
                category_match = False
                
                if category_lower == "t-shirt":
                    # For t-shirts, look for "tee" or "t-shirt" specifically
                    # Exclude flannels, work shirts, button-ups
                    if any(word in title or word in product_type for word in ["tee", "t-shirt", "tshirt"]):
                        if not any(word in title or word in product_type for word in ["flannel", "work shirt", "button", "oxford", "chambray"]):
                            category_match = True
                elif category_lower == "button-shirt":
                    # For button-up shirts, exclude t-shirts
                    if "shirt" in title or "shirt" in product_type:
                        if not any(word in title or word in product_type for word in ["tee", "t-shirt", "tshirt"]):
                            category_match = True
                elif category_lower in ["shirt", "shirts"]:
                    # Generic "shirt" - match any shirt but exclude jeans/pants
                    if "shirt" in title or "shirt" in product_type:
                        if not any(word in title or word in product_type for word in ["jean", "pant", "trouser", "chino"]):
                            category_match = True
                elif category_lower in ["jean", "jeans", "pant", "pants", "denim"]:
                    # Jeans/pants - exclude shirts/jackets
                    if any(word in title or word in product_type for word in ["jean", "pant", "denim", "trouser"]):
                        if not any(word in title or word in product_type for word in ["shirt", "jacket", "coat"]):
                            category_match = True
                else:
                    # Other categories - simple match
                    category_variations = [category_lower, category_lower + "s", category_lower.rstrip("s")]
                    category_match = any(var in product_type or var in title for var in category_variations)
                
                if not category_match:
                    continue
            
            # Filter by size availability
            if size:
                size_lower = size.lower().replace(" ", "")  # Remove spaces: "x l" -> "xl"
                variants = p.get("variants", [])
                has_size_in_stock = False
                
                for v in variants:
                    variant_size = (v.get("option1") or v.get("title", "")).lower().replace(" ", "")
                    available = v.get("available", False)
                    
                    # Normalize both sides to a canonical form before comparing
                    SIZE_ALIASES = {
                        "s": "s", "small": "s",
                        "m": "m", "medium": "m", "med": "m",
                        "l": "l", "large": "l",
                        "x": "xl", "xl": "xl", "extralarge": "xl", "extra-large": "xl",
                        "xx": "xxl", "xxl": "xxl", "2xl": "xxl", "extraextralarge": "xxl",
                        "xxx": "xxxl", "xxxl": "xxxl", "3xl": "xxxl",
                    }
                    norm_input = SIZE_ALIASES.get(size_lower, size_lower)
                    norm_variant = SIZE_ALIASES.get(variant_size, variant_size)
                    size_match = norm_input == norm_variant
                    
                    if size_match and available:
                        has_size_in_stock = True
                        break
                
                if not has_size_in_stock:
                    continue
            else:
                # No size specified - just check if anything is in stock
                variants = p.get("variants", [])
                if not any(v.get("available", False) for v in variants):
                    continue
            
            results.append({
                "title": p.get("title", ""),
                "handle": p.get("handle", ""),
                "vendor": p.get("vendor", ""),
            })
        
        return results

    async def run(self):
        try:
            # Ask what they're looking for
            await self.capability_worker.speak(
                "What are you looking for? You can say a brand, category, or size."
            )
            user_input = await self.capability_worker.user_response()
            
            if not user_input:
                await self.capability_worker.speak("I didn't catch that.")
                return

            # Extract filters
            filters = self.extract_filters(user_input)
            brand = filters.get("brand", "")
            category = filters.get("category", "")
            size = filters.get("size", "")
            
            self.log(f"User said: '{user_input}'")
            self.log(f"Extracted filters - Brand: '{brand}', Category: '{category}', Size: '{size}'")

            # Fetch and filter catalog
            await self.capability_worker.speak("One sec, checking the catalog.")
            
            catalog = await asyncio.to_thread(self.fetch_catalog)
            if not catalog:
                await self.capability_worker.speak(
                    "I couldn't reach the Redcast site. Try again in a bit."
                )
                return

            results = self.filter_products(catalog, brand, category, size)
            
            # Speak results
            if not results:
                filter_desc = []
                if size:
                    filter_desc.append(f"size {size}")
                if category:
                    filter_desc.append(category)
                if brand:
                    filter_desc.append(f"from {brand}")
                
                desc = " ".join(filter_desc) if filter_desc else "matching that"
                await self.capability_worker.speak(
                    f"I didn't find anything {desc} that's in stock."
                )
                return
            
            # Build response
            count = len(results)
            
            if count == 1:
                await self.capability_worker.speak(
                    f"Found one item: {results[0]['title']}."
                )
            elif count <= 5:
                # Read all of them
                items = ", ".join([r["title"] for r in results])
                await self.capability_worker.speak(
                    f"Found {count} items: {items}."
                )
            else:
                # Too many - read first 5 and summarize
                first_five = ", ".join([r["title"] for r in results[:5]])
                await self.capability_worker.speak(
                    f"Found {count} items. Here are the first five: {first_five}."
                )
                await self.capability_worker.speak(
                    f"There are {count - 5} more. Want me to keep going?"
                )
                
                response = await self.capability_worker.user_response()
                if response and "yes" in response.lower():
                    # Read next batch
                    next_batch = ", ".join([r["title"] for r in results[5:10]])
                    await self.capability_worker.speak(next_batch)

        except Exception as e:
            self.log_err(f"Error: {e}")
            await self.capability_worker.speak(
                "Something went wrong. Try again."
            )
        finally:
            self.capability_worker.resume_normal_flow()
