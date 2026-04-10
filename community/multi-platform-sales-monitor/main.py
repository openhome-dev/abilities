"""
Multi-Platform Sales Monitor - OpenHome Ability
Voice-activated sales dashboard for Gumroad and Shopify.
Combines revenue data from multiple platforms into unified analytics.

Author: Ammad Yousaf
Version: 1.0
"""

import json
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# Demo mode - set to False when you have real credentials
DEMO_MODE = True  # Default: demo mode with realistic test data

# API Configuration
GUMROAD_API_BASE = "https://api.gumroad.com/v2"
SHOPIFY_API_VERSION = "2024-01"

# Cache settings
CACHE_TTL = 900  # 15 minutes
EXIT_WORDS = ["stop", "quit", "exit", "done", "cancel", "thanks", "thank you"]
PREFS_FILE = "sales_monitor_prefs.json"

# Hardcoded configuration
UNIQUE_NAME = "multi_sales_monitor"


class MultiSalesMonitorCapability(MatchingCapability):
    """Voice-activated multi-platform sales monitoring capability."""

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register_capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run_sales_monitor())

    # ========== FILE OPERATIONS ==========

    async def _load_prefs(self) -> Dict[str, Any]:
        """Load preferences using OpenHome File Storage API."""
        try:
            if await self.capability_worker.check_if_file_exists(PREFS_FILE, False):
                content = await self.capability_worker.read_file(PREFS_FILE, False)
                return json.loads(content)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Failed to load prefs: {e}")

        return {"demo_mode": DEMO_MODE}

    async def _save_prefs(self, prefs: Dict[str, Any]):
        """Save preferences using SDK-compliant delete-then-write pattern."""
        try:
            # SDK requirement: delete file before writing
            if await self.capability_worker.check_if_file_exists(PREFS_FILE, False):
                await self.capability_worker.delete_file(PREFS_FILE, False)

            await self.capability_worker.write_file(
                PREFS_FILE,
                json.dumps(prefs, indent=2),
                False,
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Failed to save prefs: {e}")

    # ========== GUMROAD API ==========

    async def _fetch_gumroad_sales(
        self, start_date: str, end_date: str
    ) -> List[Dict[str, Any]]:
        """Fetch sales from Gumroad API."""
        prefs = await self._load_prefs()

        if prefs.get("demo_mode", DEMO_MODE):
            return self._generate_demo_gumroad_sales()

        try:
            access_token = prefs.get("gumroad_access_token")

            if not access_token:
                self.worker.editor_logging_handler.warning("No Gumroad token configured")
                return []

            # Gumroad API call
            url = f"{GUMROAD_API_BASE}/sales"
            headers = {"Authorization": f"Bearer {access_token}"}
            params = {
                "after": start_date,
                "before": end_date,
            }

            self.worker.editor_logging_handler.info(f"Calling Gumroad API: {url}")
            response = requests.get(url, headers=headers, params=params, timeout=15)

            self.worker.editor_logging_handler.info(f"Gumroad response: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                sales = data.get("sales", [])
                self.worker.editor_logging_handler.info(f"Gumroad returned {len(sales)} sales")
                return sales
            else:
                self.worker.editor_logging_handler.error(
                    f"Gumroad API error: {response.status_code} - {response.text}"
                )
                return []

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Gumroad fetch error: {e}")
            return []

    def _generate_demo_gumroad_sales(self) -> List[Dict[str, Any]]:
        """Generate demo Gumroad sales data."""
        now = datetime.now(timezone.utc)
        return [
            {
                "id": "sale_1",
                "product_name": "React Mastery Course",
                "price": 9900,  # Gumroad uses cents
                "currency": "usd",
                "created_at": (now - timedelta(hours=2)).isoformat(),
                "email": "customer1@example.com",
            },
            {
                "id": "sale_2",
                "product_name": "Python Guide eBook",
                "price": 4900,
                "currency": "usd",
                "created_at": (now - timedelta(hours=5)).isoformat(),
                "email": "customer2@example.com",
            },
            {
                "id": "sale_3",
                "product_name": "Notion Templates Pack",
                "price": 2900,
                "currency": "usd",
                "created_at": (now - timedelta(hours=8)).isoformat(),
                "email": "customer3@example.com",
            },
        ]

    # ========== SHOPIFY API ==========

    async def _fetch_shopify_orders(
        self, start_date: str, end_date: str
    ) -> List[Dict[str, Any]]:
        """Fetch orders from Shopify API."""
        prefs = await self._load_prefs()

        if prefs.get("demo_mode", DEMO_MODE):
            return self._generate_demo_shopify_orders()

        try:
            shop_url = prefs.get("shopify_shop_url")
            access_token = prefs.get("shopify_access_token")

            if not shop_url or not access_token:
                self.worker.editor_logging_handler.warning("No Shopify credentials configured")
                return []

            # Shopify API call
            url = f"https://{shop_url}/admin/api/{SHOPIFY_API_VERSION}/orders.json"
            headers = {"X-Shopify-Access-Token": access_token}
            params = {
                "created_at_min": start_date,
                "created_at_max": end_date,
                "status": "any",
                "limit": 250,  # Max per request
            }

            self.worker.editor_logging_handler.info(f"Calling Shopify API: {url}")
            response = requests.get(url, headers=headers, params=params, timeout=15)

            self.worker.editor_logging_handler.info(f"Shopify response: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                orders = data.get("orders", [])
                self.worker.editor_logging_handler.info(f"Shopify returned {len(orders)} orders")
                return orders
            else:
                self.worker.editor_logging_handler.error(
                    f"Shopify API error: {response.status_code} - {response.text}"
                )
                return []

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Shopify fetch error: {e}")
            return []

    def _generate_demo_shopify_orders(self) -> List[Dict[str, Any]]:
        """Generate demo Shopify orders data."""
        now = datetime.now(timezone.utc)
        return [
            {
                "id": 12345,
                "created_at": (now - timedelta(hours=1)).isoformat(),
                "total_price": "59.98",
                "currency": "USD",
                "line_items": [
                    {"title": "Logo T-Shirt", "price": "29.99", "quantity": 2}
                ],
                "customer": {"email": "customer4@example.com"},
            },
            {
                "id": 12346,
                "created_at": (now - timedelta(hours=4)).isoformat(),
                "total_price": "89.99",
                "currency": "USD",
                "line_items": [
                    {"title": "Coffee Mug", "price": "19.99", "quantity": 1},
                    {"title": "Sticker Pack", "price": "14.99", "quantity": 1},
                ],
                "customer": {"email": "customer5@example.com"},
            },
            {
                "id": 12347,
                "created_at": (now - timedelta(hours=6)).isoformat(),
                "total_price": "149.99",
                "currency": "USD",
                "line_items": [
                    {"title": "Premium Hoodie", "price": "79.99", "quantity": 1},
                ],
                "customer": {"email": "customer6@example.com"},
            },
        ]

    # ========== DATA AGGREGATION ==========

    def _aggregate_sales_data(
        self, gumroad_sales: List, shopify_orders: List
    ) -> Dict[str, Any]:
        """Aggregate sales data from both platforms."""
        # Calculate Gumroad totals (Gumroad uses cents)
        gumroad_revenue = sum(
            sale.get("price", 0) / 100 for sale in gumroad_sales
        )
        gumroad_count = len(gumroad_sales)

        # Calculate Shopify totals
        shopify_revenue = sum(
            float(order.get("total_price", 0)) for order in shopify_orders
        )
        shopify_count = len(shopify_orders)

        # Combined totals
        total_revenue = gumroad_revenue + shopify_revenue
        total_count = gumroad_count + shopify_count

        # Average order value
        avg_order_value = total_revenue / total_count if total_count > 0 else 0

        return {
            "total_revenue": total_revenue,
            "total_count": total_count,
            "gumroad_revenue": gumroad_revenue,
            "gumroad_count": gumroad_count,
            "shopify_revenue": shopify_revenue,
            "shopify_count": shopify_count,
            "digital_revenue": gumroad_revenue,  # Gumroad = digital
            "physical_revenue": shopify_revenue,  # Shopify = physical
            "avg_order_value": avg_order_value,
        }

    # ========== FORMATTING HELPERS ==========

    def _format_currency(self, amount: float, currency: str = "USD") -> str:
        """Format amount as currency for voice."""
        if amount == 0:
            return "zero dollars"
        rounded = round(amount, 2)
        if rounded == int(rounded):
            return f"{int(rounded)} dollars"
        return f"{rounded} dollars"

    def _format_percentage(self, value: float) -> str:
        """Format percentage for voice."""
        return f"{round(value)} percent"

    # ========== INTENT CLASSIFICATION ==========

    def _classify_intent(self, user_input: str) -> str:
        """Classify user intent using simple keyword matching."""
        if not user_input:
            return "unknown"

        text = user_input.lower()

        # Digital vs physical (MUST come before "compare" check)
        if ("digital" in text and "physical" in text) or \
           ("digital" in text and ("vs" in text or "versus" in text)) or \
           ("physical" in text and ("vs" in text or "versus" in text)):
            return "digital_vs_physical"

        # Platform-specific queries (includes "breakdown" and "platform")
        if "gumroad" in text or "shopify" in text or "breakdown" in text or "platform" in text:
            return "platform_breakdown"

        # Time-based queries
        if "week" in text or "weekly" in text:
            return "this_week"
        if "month" in text or "monthly" in text:
            return "this_month"
        if "all time" in text or "total revenue" in text or "lifetime" in text or "since" in text or "overall" in text:
            return "all_time"
        if "yesterday" in text:
            return "yesterday"

        # Product queries
        if "best" in text or "top" in text or "most popular" in text:
            return "best_seller"
        if "product" in text and ("how many" in text or "total" in text or "catalog" in text):
            return "product_count"

        # Customer count
        if "customer" in text:
            return "customer_count"

        # Average order
        if "average" in text:
            return "average_order"

        # Trends (MUST come AFTER digital_vs_physical)
        if "trend" in text or "compare" in text or "growth" in text:
            return "trends"

        # Default to total sales for general queries
        if any(word in text for word in ["total", "how much", "revenue", "sales", "made", "earning", "today"]):
            return "total_sales"

        return "unknown"

    def _is_exit_word(self, text: Optional[str]) -> bool:
        """Check if user said an exit word."""
        if not text:
            return False
        return any(word in text.lower() for word in EXIT_WORDS)

    # ========== MAIN LOOP ==========

    async def run_sales_monitor(self) -> None:
        """Main conversation loop for sales monitoring."""
        try:
            # Start with comprehensive dashboard summary
            await self._handle_dashboard_summary()

            # Conversation loop
            while True:
                await self.capability_worker.speak("What else would you like to know?")
                response = await self.capability_worker.user_response()

                if not response or self._is_exit_word(response):
                    await self.capability_worker.speak("Okay, talk to you later!")
                    break

                intent = self._classify_intent(response)

                if intent == "total_sales":
                    await self._handle_total_sales()
                elif intent == "this_week":
                    await self._handle_this_week()
                elif intent == "this_month":
                    await self._handle_this_month()
                elif intent == "all_time":
                    await self._handle_all_time()
                elif intent == "yesterday":
                    await self._handle_yesterday()
                elif intent == "best_seller":
                    await self._handle_best_seller()
                elif intent == "product_count":
                    await self._handle_product_count()
                elif intent == "platform_breakdown":
                    await self._handle_platform_breakdown(response)
                elif intent == "digital_vs_physical":
                    await self._handle_digital_vs_physical()
                elif intent == "customer_count":
                    await self._handle_customer_count()
                elif intent == "average_order":
                    await self._handle_average_order()
                elif intent == "trends":
                    await self._handle_trends()
                else:
                    await self.capability_worker.speak(
                        "I can help with your total sales, platform breakdown, or compare digital versus physical sales. What would you like to know?"
                    )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Sales monitor error: {e}")
            await self.capability_worker.speak("Something went wrong. Try again later.")
        finally:
            self.capability_worker.resume_normal_flow()

    # ========== INTENT HANDLERS ==========

    async def _handle_dashboard_summary(self) -> None:
        """Provide comprehensive sales dashboard overview."""
        today = datetime.now(timezone.utc).date()

        # Today's data
        today_start = today.isoformat()
        today_end = (today + timedelta(days=1)).isoformat()
        gumroad_today = await self._fetch_gumroad_sales(today_start, today_end)
        shopify_today = await self._fetch_shopify_orders(today_start, today_end)
        today_stats = self._aggregate_sales_data(gumroad_today, shopify_today)

        # This week's data
        week_start = today - timedelta(days=today.weekday())
        week_start_str = week_start.isoformat()
        gumroad_week = await self._fetch_gumroad_sales(week_start_str, today_end)
        shopify_week = await self._fetch_shopify_orders(week_start_str, today_end)
        week_stats = self._aggregate_sales_data(gumroad_week, shopify_week)

        # This month's data
        month_start = today.replace(day=1)
        month_start_str = month_start.isoformat()
        gumroad_month = await self._fetch_gumroad_sales(month_start_str, today_end)
        shopify_month = await self._fetch_shopify_orders(month_start_str, today_end)
        month_stats = self._aggregate_sales_data(gumroad_month, shopify_month)

        # Build summary
        parts = []

        # Today's sales
        if today_stats["total_count"] == 0:
            parts.append("No sales yet today")
        else:
            today_str = self._format_currency(today_stats["total_revenue"])
            parts.append(f"Today: {today_str} from {today_stats['total_count']} sales")

        # This week
        if week_stats["total_count"] > 0:
            week_str = self._format_currency(week_stats["total_revenue"])
            parts.append(f"This week: {week_str}")

        # This month
        if month_stats["total_count"] > 0:
            month_str = self._format_currency(month_stats["total_revenue"])
            parts.append(f"This month: {month_str}")

        # Platform breakdown (today)
        if today_stats["gumroad_count"] > 0 or today_stats["shopify_count"] > 0:
            gumroad_str = self._format_currency(today_stats["gumroad_revenue"])
            shopify_str = self._format_currency(today_stats["shopify_revenue"])
            parts.append(f"Gumroad: {gumroad_str}, Shopify: {shopify_str}")

        # Best seller (last 30 days)
        best_seller_info = await self._get_best_seller_info()
        if best_seller_info:
            parts.append(f"Best seller: {best_seller_info}")

        # Combine into natural speech
        summary = ". ".join(parts) + "."
        await self.capability_worker.speak(summary)

    async def _get_best_seller_info(self) -> Optional[str]:
        """Get best seller information for summary."""
        today = datetime.now(timezone.utc).date()
        start_date = (today - timedelta(days=30)).isoformat()
        end_date = (today + timedelta(days=1)).isoformat()

        gumroad_sales = await self._fetch_gumroad_sales(start_date, end_date)
        shopify_orders = await self._fetch_shopify_orders(start_date, end_date)

        product_sales = {}

        for sale in gumroad_sales:
            product = sale.get("product_name", "Unknown Product")
            product_sales[product] = product_sales.get(product, 0) + 1

        for order in shopify_orders:
            for item in order.get("line_items", []):
                product = item.get("title", "Unknown Product")
                quantity = item.get("quantity", 1)
                product_sales[product] = product_sales.get(product, 0) + quantity

        if not product_sales:
            return None

        best_seller = max(product_sales.items(), key=lambda x: x[1])
        product_name, count = best_seller
        return f"{product_name} with {count} units"

    async def _handle_total_sales(self) -> None:
        """Fetch and speak total sales across all platforms."""
        today = datetime.now(timezone.utc).date()
        start_date = today.isoformat()
        end_date = (today + timedelta(days=1)).isoformat()

        gumroad_sales = await self._fetch_gumroad_sales(start_date, end_date)
        shopify_orders = await self._fetch_shopify_orders(start_date, end_date)

        stats = self._aggregate_sales_data(gumroad_sales, shopify_orders)
        total_str = self._format_currency(stats["total_revenue"])

        if stats["total_count"] == 0:
            await self.capability_worker.speak(
                "You haven't made any sales today yet. But hey, the day's not over!"
            )
        elif stats["total_count"] == 1:
            await self.capability_worker.speak(
                f"You've got one sale today for {total_str}. Not bad!"
            )
        else:
            await self.capability_worker.speak(
                f"Nice! You've made {total_str} today from {stats['total_count']} sales."
            )

    async def _handle_platform_breakdown(self, user_query: str = "") -> None:
        """Break down sales by platform."""
        today = datetime.now(timezone.utc).date()
        start_date = today.isoformat()
        end_date = (today + timedelta(days=1)).isoformat()

        gumroad_sales = await self._fetch_gumroad_sales(start_date, end_date)
        shopify_orders = await self._fetch_shopify_orders(start_date, end_date)

        stats = self._aggregate_sales_data(gumroad_sales, shopify_orders)

        gumroad_str = self._format_currency(stats["gumroad_revenue"])
        shopify_str = self._format_currency(stats["shopify_revenue"])

        # Check if they asked about a specific platform
        user_query_lower = user_query.lower()
        asking_gumroad = "gumroad" in user_query_lower
        asking_shopify = "shopify" in user_query_lower

        # If they asked about only one platform, report only that one
        if asking_gumroad and not asking_shopify:
            if stats["gumroad_count"] == 0:
                await self.capability_worker.speak("No Gumroad sales yet today.")
            else:
                await self.capability_worker.speak(
                    f"Gumroad's at {gumroad_str} from {stats['gumroad_count']} sales."
                )
        elif asking_shopify and not asking_gumroad:
            if stats["shopify_count"] == 0:
                await self.capability_worker.speak("No Shopify orders yet today.")
            else:
                await self.capability_worker.speak(
                    f"Shopify's at {shopify_str} from {stats['shopify_count']} orders."
                )
        else:
            # They asked for both or for a comparison
            if stats["gumroad_count"] == 0 and stats["shopify_count"] == 0:
                await self.capability_worker.speak(
                    "No sales on either platform today."
                )
            elif stats["gumroad_count"] == 0:
                await self.capability_worker.speak(
                    f"All your sales came from Shopify today - {shopify_str} from {stats['shopify_count']} orders. Nothing on Gumroad yet."
                )
            elif stats["shopify_count"] == 0:
                await self.capability_worker.speak(
                    f"All your sales came from Gumroad today - {gumroad_str} from {stats['gumroad_count']} sales. Nothing on Shopify yet."
                )
            else:
                await self.capability_worker.speak(
                    f"Gumroad's at {gumroad_str} from {stats['gumroad_count']} sales, "
                    f"and Shopify's at {shopify_str} from {stats['shopify_count']} orders."
                )

    async def _handle_digital_vs_physical(self) -> None:
        """Compare digital vs physical product sales."""
        today = datetime.now(timezone.utc).date()
        start_date = today.isoformat()
        end_date = (today + timedelta(days=1)).isoformat()

        gumroad_sales = await self._fetch_gumroad_sales(start_date, end_date)
        shopify_orders = await self._fetch_shopify_orders(start_date, end_date)

        stats = self._aggregate_sales_data(gumroad_sales, shopify_orders)

        total = stats["total_revenue"]
        if total > 0:
            digital_pct = (stats["digital_revenue"] / total) * 100
            physical_pct = (stats["physical_revenue"] / total) * 100
        else:
            digital_pct = 0
            physical_pct = 0

        digital_str = self._format_currency(stats["digital_revenue"])
        physical_str = self._format_currency(stats["physical_revenue"])

        if total == 0:
            await self.capability_worker.speak(
                "No sales to compare yet today."
            )
        elif stats["digital_revenue"] == 0:
            await self.capability_worker.speak(
                f"All physical products today - {physical_str} total. No digital sales yet."
            )
        elif stats["physical_revenue"] == 0:
            await self.capability_worker.speak(
                f"All digital products today - {digital_str} total. No physical sales yet."
            )
        else:
            await self.capability_worker.speak(
                f"Digital's at {digital_str}, that's about {self._format_percentage(digital_pct)} of your revenue. "
                f"Physical's at {physical_str}, which is {self._format_percentage(physical_pct)}."
            )

    async def _handle_customer_count(self) -> None:
        """Report unique customer count."""
        today = datetime.now(timezone.utc).date()
        start_date = today.isoformat()
        end_date = (today + timedelta(days=1)).isoformat()

        gumroad_sales = await self._fetch_gumroad_sales(start_date, end_date)
        shopify_orders = await self._fetch_shopify_orders(start_date, end_date)

        # Count unique emails
        emails = set()
        for sale in gumroad_sales:
            if sale.get("email"):
                emails.add(sale["email"])
        for order in shopify_orders:
            if order.get("customer", {}).get("email"):
                emails.add(order["customer"]["email"])

        customer_count = len(emails)

        if customer_count == 0:
            await self.capability_worker.speak("No customers yet today, but the day's still young!")
        elif customer_count == 1:
            await self.capability_worker.speak("Just one customer so far today.")
        elif customer_count < 5:
            await self.capability_worker.speak(f"You've had {customer_count} customers today.")
        else:
            await self.capability_worker.speak(f"Nice! {customer_count} customers today.")

    async def _handle_average_order(self) -> None:
        """Report average order value."""
        today = datetime.now(timezone.utc).date()
        start_date = today.isoformat()
        end_date = (today + timedelta(days=1)).isoformat()

        gumroad_sales = await self._fetch_gumroad_sales(start_date, end_date)
        shopify_orders = await self._fetch_shopify_orders(start_date, end_date)

        stats = self._aggregate_sales_data(gumroad_sales, shopify_orders)

        if stats["total_count"] == 0:
            await self.capability_worker.speak("No sales yet, so no average to calculate.")
        else:
            avg_str = self._format_currency(stats["avg_order_value"])
            await self.capability_worker.speak(
                f"Your average order today is {avg_str}."
            )

    async def _handle_this_week(self) -> None:
        """Report this week's sales."""
        today = datetime.now(timezone.utc).date()
        week_start = today - timedelta(days=today.weekday())
        start_date = week_start.isoformat()
        end_date = (today + timedelta(days=1)).isoformat()

        gumroad_sales = await self._fetch_gumroad_sales(start_date, end_date)
        shopify_orders = await self._fetch_shopify_orders(start_date, end_date)

        stats = self._aggregate_sales_data(gumroad_sales, shopify_orders)
        total_str = self._format_currency(stats["total_revenue"])

        if stats["total_count"] == 0:
            await self.capability_worker.speak("No sales this week yet.")
        else:
            await self.capability_worker.speak(
                f"This week you've made {total_str} from {stats['total_count']} sales."
            )

    async def _handle_this_month(self) -> None:
        """Report this month's sales."""
        today = datetime.now(timezone.utc).date()
        month_start = today.replace(day=1)
        start_date = month_start.isoformat()
        end_date = (today + timedelta(days=1)).isoformat()

        gumroad_sales = await self._fetch_gumroad_sales(start_date, end_date)
        shopify_orders = await self._fetch_shopify_orders(start_date, end_date)

        stats = self._aggregate_sales_data(gumroad_sales, shopify_orders)
        total_str = self._format_currency(stats["total_revenue"])

        if stats["total_count"] == 0:
            await self.capability_worker.speak("No sales this month yet.")
        else:
            await self.capability_worker.speak(
                f"This month you've made {total_str} from {stats['total_count']} sales so far."
            )

    async def _handle_all_time(self) -> None:
        """Report all-time revenue (last 365 days as proxy)."""
        today = datetime.now(timezone.utc).date()
        year_ago = today - timedelta(days=365)
        start_date = year_ago.isoformat()
        end_date = (today + timedelta(days=1)).isoformat()

        gumroad_sales = await self._fetch_gumroad_sales(start_date, end_date)
        shopify_orders = await self._fetch_shopify_orders(start_date, end_date)

        stats = self._aggregate_sales_data(gumroad_sales, shopify_orders)
        total_str = self._format_currency(stats["total_revenue"])

        if stats["total_count"] == 0:
            await self.capability_worker.speak("No sales in the past year.")
        else:
            await self.capability_worker.speak(
                f"In the past year, you've made {total_str} from {stats['total_count']} total sales."
            )

    async def _handle_yesterday(self) -> None:
        """Report yesterday's sales."""
        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)
        start_date = yesterday.isoformat()
        end_date = today.isoformat()

        gumroad_sales = await self._fetch_gumroad_sales(start_date, end_date)
        shopify_orders = await self._fetch_shopify_orders(start_date, end_date)

        stats = self._aggregate_sales_data(gumroad_sales, shopify_orders)
        total_str = self._format_currency(stats["total_revenue"])

        if stats["total_count"] == 0:
            await self.capability_worker.speak("No sales yesterday.")
        else:
            await self.capability_worker.speak(
                f"Yesterday you made {total_str} from {stats['total_count']} sales."
            )

    async def _handle_best_seller(self) -> None:
        """Report best-selling product."""
        today = datetime.now(timezone.utc).date()
        start_date = (today - timedelta(days=30)).isoformat()
        end_date = (today + timedelta(days=1)).isoformat()

        gumroad_sales = await self._fetch_gumroad_sales(start_date, end_date)
        shopify_orders = await self._fetch_shopify_orders(start_date, end_date)

        # Count product sales
        product_sales = {}

        for sale in gumroad_sales:
            product = sale.get("product_name", "Unknown Product")
            product_sales[product] = product_sales.get(product, 0) + 1

        for order in shopify_orders:
            for item in order.get("line_items", []):
                product = item.get("title", "Unknown Product")
                quantity = item.get("quantity", 1)
                product_sales[product] = product_sales.get(product, 0) + quantity

        if not product_sales:
            await self.capability_worker.speak("No products sold in the last 30 days.")
        else:
            best_seller = max(product_sales.items(), key=lambda x: x[1])
            product_name, count = best_seller
            await self.capability_worker.speak(
                f"Your best seller in the last month is {product_name} with {count} sales."
            )

    async def _handle_product_count(self) -> None:
        """Report total products available (demo approximation)."""
        today = datetime.now(timezone.utc).date()
        start_date = (today - timedelta(days=90)).isoformat()
        end_date = (today + timedelta(days=1)).isoformat()

        gumroad_sales = await self._fetch_gumroad_sales(start_date, end_date)
        shopify_orders = await self._fetch_shopify_orders(start_date, end_date)

        # Count unique products
        products = set()

        for sale in gumroad_sales:
            product = sale.get("product_name")
            if product:
                products.add(product)

        for order in shopify_orders:
            for item in order.get("line_items", []):
                product = item.get("title")
                if product:
                    products.add(product)

        count = len(products)

        if count == 0:
            await self.capability_worker.speak("I haven't seen any products sold recently.")
        elif count == 1:
            await self.capability_worker.speak("You have 1 product that's been sold recently.")
        else:
            await self.capability_worker.speak(
                f"You have {count} different products that have sold in the last 90 days."
            )

    async def _handle_trends(self) -> None:
        """Compare today vs yesterday."""
        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)

        # Today's sales
        today_start = today.isoformat()
        today_end = (today + timedelta(days=1)).isoformat()
        gumroad_today = await self._fetch_gumroad_sales(today_start, today_end)
        shopify_today = await self._fetch_shopify_orders(today_start, today_end)
        today_stats = self._aggregate_sales_data(gumroad_today, shopify_today)

        # Yesterday's sales
        yesterday_start = yesterday.isoformat()
        yesterday_end = today.isoformat()
        gumroad_yesterday = await self._fetch_gumroad_sales(yesterday_start, yesterday_end)
        shopify_yesterday = await self._fetch_shopify_orders(yesterday_start, yesterday_end)
        yesterday_stats = self._aggregate_sales_data(gumroad_yesterday, shopify_yesterday)

        today_rev = today_stats["total_revenue"]
        yesterday_rev = yesterday_stats["total_revenue"]

        if yesterday_rev == 0 and today_rev == 0:
            await self.capability_worker.speak("No sales today or yesterday to compare.")
        elif yesterday_rev == 0:
            today_str = self._format_currency(today_rev)
            await self.capability_worker.speak(
                f"Today you're at {today_str}, compared to zero yesterday. Looking up!"
            )
        else:
            change_pct = ((today_rev - yesterday_rev) / yesterday_rev) * 100
            if change_pct > 0:
                await self.capability_worker.speak(
                    f"You're up {self._format_percentage(abs(change_pct))} compared to yesterday. Nice!"
                )
            elif change_pct < 0:
                await self.capability_worker.speak(
                    f"You're down {self._format_percentage(abs(change_pct))} compared to yesterday."
                )
            else:
                await self.capability_worker.speak("Same as yesterday.")
