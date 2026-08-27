import uuid
from datetime import datetime

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

STORAGE_KEY = "life_admin_tracker_data"

HOTWORDS = [
    "life admin", "my renewals", "what's due", "what's expiring",
    "add a renewal", "track my passport", "track my mot",
    "track my insurance", "what's coming up", "any renewals",
    "due soon", "expiring soon", "mark as renewed", "subscription costs",
    "my subscriptions", "admin tracker", "renewal tracker",
    "renewals tracker", "life admin tracker",
]

EXIT_WORDS = {"stop", "done", "exit", "quit", "bye", "cancel", "nothing"}
EXIT_PHRASES = {"that's all", "thats all", "no thanks"}

INTENT_PROMPT = (
    "Classify the user's intent for a Life Admin and Renewals tracker.\n"
    "Intents:\n"
    "ADD — add a new item to track\n"
    "CHECK — see what's due or expiring soon, or list all items\n"
    "RENEW — mark an existing item as renewed or updated with a new date\n"
    "REMOVE — delete or remove an item\n"
    "COST — check subscription or cost summary\n"
    "STATUS — check the expiry status of one specific item\n"
    "EXIT — user wants to stop\n"
    "Return ONLY the intent label.\n"
    "Input: \"{text}\""
)

DATE_EXTRACT_PROMPT = (
    "Extract an expiry or renewal date from natural speech. "
    "Today's date is {today}. "
    "Return an ISO date YYYY-MM-DD only. "
    "If unclear or no date mentioned, return UNKNOWN. "
    "Examples: 'next March' → next year's March 1st, "
    "'in 3 years' → 3 years from today, "
    "'2027' → 2027-01-01, "
    "'6 months time' → 6 months from today, "
    "'March 2027' → 2027-03-01. "
    "Input: \"{text}\""
)

ITEM_NAME_PROMPT = (
    "Extract the item name from this utterance about life admin or renewals tracking. "
    "Return only the item name (e.g. 'passport', 'car insurance', 'MOT', "
    "'Netflix subscription', 'boiler service'). "
    "Input: \"{text}\""
)

CATEGORY_PROMPT = (
    "Classify this item into one of: "
    "document, vehicle, home, insurance, subscription, warranty, other. "
    "Item: \"{name}\". "
    "Return ONLY the category label."
)

COST_EXTRACT_PROMPT = (
    "Extract a cost amount and period from this text. "
    "Return as 'AMOUNT PERIOD' where PERIOD is 'monthly' or 'annual'. "
    "Examples: '£10 a month' → '10.00 monthly', '$120 per year' → '120.00 annual'. "
    "If no cost mentioned, return 'NONE'. "
    "Input: \"{text}\""
)

NAME_EXTRACT_PROMPT = (
    "Extract the person's first name from this text. "
    "Return only the first name, nothing else. "
    "Input: \"{text}\""
)


class LifeAdminTrackerCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    def does_match(self, text: str) -> bool:
        t = text.lower()
        return any(hw in t for hw in HOTWORDS)

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self._run())

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def _load_data(self) -> dict:
        try:
            result = self.capability_worker.get_single_key(STORAGE_KEY)
            if result and result.get("value"):
                return result["value"]
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[LifeAdmin] Load error: {e!r}")
        return {}

    def _save_data(self, data: dict):
        try:
            result = self.capability_worker.create_key(STORAGE_KEY, data)
            if not result.get("success"):
                self.capability_worker.update_key(STORAGE_KEY, data)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[LifeAdmin] Save error: {e!r}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_exit(self, text: str) -> bool:
        text_lower = text.lower().strip()
        if any(p in text_lower for p in EXIT_PHRASES):
            return True
        tokens = set(text_lower.split())
        return bool(tokens & EXIT_WORDS)

    def _today(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _days_until(self, expiry_date: str) -> int:
        try:
            exp = datetime.strptime(expiry_date, "%Y-%m-%d").date()
            return (exp - datetime.now().date()).days
        except Exception:
            return 9999

    def _format_days(self, days: int) -> str:
        if days < 0:
            return f"expired {abs(days)} day{'s' if abs(days) > 1 else ''} ago"
        if days == 0:
            return "today"
        if days == 1:
            return "tomorrow"
        if days < 31:
            return f"in {days} days"
        if days < 60:
            return "in about a month"
        months = round(days / 30)
        if months < 12:
            return f"in about {months} months"
        years = round(days / 365)
        return f"in about {years} year{'s' if years > 1 else ''}"

    def _classify_intent(self, text: str) -> str:
        raw = self.capability_worker.text_to_text_response(
            INTENT_PROMPT.format(text=text)
        )
        result = raw.strip().upper().split()[0]
        valid = {"ADD", "CHECK", "RENEW", "REMOVE", "COST", "STATUS", "EXIT"}
        return result if result in valid else "CHECK"

    def _extract_date(self, text: str) -> str:
        raw = self.capability_worker.text_to_text_response(
            DATE_EXTRACT_PROMPT.format(today=self._today(), text=text)
        )
        extracted = raw.strip().split()[0]
        if extracted == "UNKNOWN":
            return ""
        try:
            datetime.strptime(extracted, "%Y-%m-%d")
            return extracted
        except Exception:
            return ""

    def _extract_item_name(self, text: str) -> str:
        return self.capability_worker.text_to_text_response(
            ITEM_NAME_PROMPT.format(text=text)
        ).strip()

    def _extract_category(self, name: str) -> str:
        raw = self.capability_worker.text_to_text_response(
            CATEGORY_PROMPT.format(name=name)
        ).strip().lower()
        valid = {"document", "vehicle", "home", "insurance", "subscription", "warranty"}
        return raw if raw in valid else "other"

    def _extract_cost(self, text: str):
        raw = self.capability_worker.text_to_text_response(
            COST_EXTRACT_PROMPT.format(text=text)
        ).strip()
        parts = raw.split()
        if not parts or parts[0].upper() == "NONE":
            return None, None
        try:
            amount = float(parts[0])
            period = parts[1] if len(parts) > 1 else "monthly"
            return amount, period
        except Exception:
            return None, None

    def _find_item(self, data: dict, name_hint: str) -> dict:
        name_lower = name_hint.lower()
        for item in data.get("items", []):
            if item["name"].lower() == name_lower:
                return item
        for item in data.get("items", []):
            if name_lower in item["name"].lower() or item["name"].lower() in name_lower:
                return item
        return None

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    async def _load_user_name(self) -> str:
        for filename in ("user_profile.md", "user_summary.md"):
            try:
                content = await self.capability_worker.read_file(
                    filename, in_ability_directory=False
                )
                if content:
                    name = self.capability_worker.text_to_text_response(
                        f"Extract the person's first name from this profile text. "
                        f"Return only the name, or UNKNOWN if not found.\n{content}"
                    ).strip()
                    if name and name != "UNKNOWN":
                        return name
            except Exception:
                pass
        return ""

    async def _handle_setup(self, data: dict) -> dict:
        name = await self._load_user_name()
        if not name:
            await self.capability_worker.speak(
                "Hi! I'm your Life Admin tracker. I'll keep on top of your renewals and "
                "expiry dates and remind you automatically before anything's due. "
                "What's your name?"
            )
            reply = await self.capability_worker.user_response()
            if reply:
                name = self.capability_worker.text_to_text_response(
                    NAME_EXTRACT_PROMPT.format(text=reply)
                ).strip()
        data["user_name"] = name
        data["setup_complete"] = True
        data["items"] = []
        self._save_data(data)
        greeting = f"Got it, {name}!" if name else "Got it!"
        await self.capability_worker.speak(
            f"{greeting} Say 'add a renewal' to start tracking something, "
            f"or 'what's due soon' any time to check your list."
        )
        return data

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------

    async def _handle_add(self, data: dict, trigger_text: str):
        item_name = ""
        if trigger_text:
            item_name = self._extract_item_name(trigger_text)

        if not item_name or len(item_name) < 2:
            await self.capability_worker.speak("What would you like to track?")
            reply = await self.capability_worker.user_response()
            if not reply:
                return
            item_name = self._extract_item_name(reply)
            trigger_text = reply

        expiry_date = self._extract_date(trigger_text)

        if not expiry_date:
            await self.capability_worker.speak(f"When does your {item_name} expire or renew?")
            date_reply = await self.capability_worker.user_response()
            if not date_reply:
                return
            expiry_date = self._extract_date(date_reply)

        if not expiry_date:
            await self.capability_worker.speak(
                "I couldn't catch a date. Try something like 'March 2027' or 'in 2 years'."
            )
            return

        category = self._extract_category(item_name)
        cost, cost_period = None, None

        if category == "subscription":
            await self.capability_worker.speak(
                f"How much does {item_name} cost? Say 'skip' to leave that out."
            )
            cost_reply = await self.capability_worker.user_response()
            if cost_reply and "skip" not in cost_reply.lower():
                cost, cost_period = self._extract_cost(cost_reply)

        new_item = {
            "id": uuid.uuid4().hex[:8],
            "name": item_name.title(),
            "category": category,
            "expiry_date": expiry_date,
            "cost": cost,
            "cost_period": cost_period,
            "added_date": self._today(),
            "last_nudge_threshold": None,
            "last_nudge_date": None,
        }
        data.setdefault("items", []).append(new_item)
        self._save_data(data)
        self.worker.editor_logging_handler.info(f"[LifeAdmin] Added: {item_name}, expires {expiry_date}")

        days = self._days_until(expiry_date)
        due_str = self._format_days(days)
        if category == "subscription" and cost:
            period_label = "month" if cost_period == "monthly" else "year"
            await self.capability_worker.speak(
                f"Got it — {item_name.title()} logged at £{cost:.0f}/{period_label}, "
                f"renewing {due_str}. I'll remind you 90, 30, and 7 days before."
            )
        else:
            await self.capability_worker.speak(
                f"Got it — {item_name.title()} logged, expires {due_str}. "
                f"I'll remind you 90, 30, and 7 days before."
            )

    async def _handle_check(self, data: dict):
        items = data.get("items", [])
        if not items:
            await self.capability_worker.speak(
                "Nothing tracked yet. Say 'add a renewal' to get started."
            )
            return

        scored = sorted(
            [(item, self._days_until(item["expiry_date"])) for item in items],
            key=lambda x: x[1]
        )

        urgent = [(i, d) for i, d in scored if d <= 30]
        soon = [(i, d) for i, d in scored if 30 < d <= 90]
        upcoming = [(i, d) for i, d in scored if 90 < d <= 365]

        if not urgent and not soon:
            if upcoming:
                nxt, nd = upcoming[0]
                await self.capability_worker.speak(
                    f"Nothing due in the next 3 months. "
                    f"Your next renewal is your {nxt['name']} {self._format_days(nd)}."
                )
            else:
                await self.capability_worker.speak(
                    "All your renewals are more than a year away. You're all good."
                )
            return

        parts = []
        for item, days in (urgent + soon)[:5]:
            if days <= 0:
                parts.append(f"your {item['name']} has already expired")
            else:
                parts.append(f"your {item['name']} {self._format_days(days)}")

        if len(parts) == 1:
            msg = parts[0].capitalize() + "."
        elif len(parts) == 2:
            msg = f"{parts[0].capitalize()} and {parts[1]}."
        else:
            msg = ", ".join(p.capitalize() for p in parts[:-1]) + f", and {parts[-1]}."

        remaining = len(scored) - len(urgent) - len(soon)
        if remaining > 0:
            msg += f" Plus {remaining} more item{'s' if remaining > 1 else ''} further out."

        await self.capability_worker.speak(msg)

    async def _handle_renew(self, data: dict, trigger_text: str):
        items = data.get("items", [])
        if not items:
            await self.capability_worker.speak("Nothing tracked yet to mark as renewed.")
            return

        item = None
        if trigger_text:
            name_hint = self._extract_item_name(trigger_text)
            item = self._find_item(data, name_hint)

        if not item:
            names = ", ".join(i["name"] for i in items[:5])
            await self.capability_worker.speak(
                f"Which item are you renewing? You're tracking: {names}."
            )
            reply = await self.capability_worker.user_response()
            if not reply:
                return
            item = self._find_item(data, self._extract_item_name(reply))

        if not item:
            await self.capability_worker.speak(
                "Couldn't find that one. Try again with the exact name."
            )
            return

        await self.capability_worker.speak(
            f"When is the new expiry date for your {item['name']}?"
        )
        date_reply = await self.capability_worker.user_response()
        if not date_reply:
            return

        new_date = self._extract_date(date_reply)
        if not new_date:
            await self.capability_worker.speak(
                "Couldn't catch that date. Try 'March 2027' or 'in a year'."
            )
            return

        item["expiry_date"] = new_date
        item["last_nudge_threshold"] = None
        item["last_nudge_date"] = None
        self._save_data(data)
        self.worker.editor_logging_handler.info(f"[LifeAdmin] Renewed: {item['name']}, new expiry {new_date}")
        await self.capability_worker.speak(
            f"Done — {item['name']} updated. Next renewal {self._format_days(self._days_until(new_date))}."
        )

    async def _handle_remove(self, data: dict, trigger_text: str):
        items = data.get("items", [])
        if not items:
            await self.capability_worker.speak("Nothing tracked yet.")
            return

        item = None
        if trigger_text:
            item = self._find_item(data, self._extract_item_name(trigger_text))

        if not item:
            names = ", ".join(i["name"] for i in items[:5])
            await self.capability_worker.speak(
                f"Which item would you like to remove? You're tracking: {names}."
            )
            reply = await self.capability_worker.user_response()
            if not reply:
                return
            item = self._find_item(data, self._extract_item_name(reply))

        if not item:
            await self.capability_worker.speak("Couldn't find that one.")
            return

        data["items"] = [i for i in items if i["id"] != item["id"]]
        self._save_data(data)
        self.worker.editor_logging_handler.info(f"[LifeAdmin] Removed: {item['name']}")
        await self.capability_worker.speak(f"Removed {item['name']}.")

    async def _handle_cost(self, data: dict):
        subs = [i for i in data.get("items", []) if i.get("cost") is not None]
        if not subs:
            await self.capability_worker.speak(
                "No subscription costs tracked yet. "
                "When you add a subscription, I'll ask for the cost."
            )
            return

        monthly_total = 0.0
        lines = []
        for sub in subs:
            cost = sub["cost"]
            period = sub.get("cost_period", "monthly")
            monthly_total += cost if period == "monthly" else cost / 12
            lines.append(
                f"{sub['name']} £{cost:.0f} {'a month' if period == 'monthly' else 'a year'}"
            )

        annual_total = monthly_total * 12
        cost_list = ", ".join(lines)
        await self.capability_worker.speak(
            f"You have {len(subs)} subscription{'s' if len(subs) > 1 else ''}: {cost_list}. "
            f"That's £{monthly_total:.0f} a month or £{annual_total:.0f} a year."
        )

    async def _handle_status(self, data: dict, trigger_text: str):
        item = None
        if trigger_text:
            item = self._find_item(data, self._extract_item_name(trigger_text))

        if not item:
            await self.capability_worker.speak("Which item do you want to check?")
            reply = await self.capability_worker.user_response()
            if not reply:
                return
            item = self._find_item(data, self._extract_item_name(reply))

        if not item:
            await self.capability_worker.speak("Couldn't find that one in your list.")
            return

        days = self._days_until(item["expiry_date"])
        await self.capability_worker.speak(
            f"Your {item['name']} expires on {item['expiry_date']} — "
            f"that's {self._format_days(days)}."
        )

    async def _dispatch(self, intent: str, data: dict, trigger_text: str):
        self.worker.editor_logging_handler.info(f"[LifeAdmin] Intent: {intent}")
        if intent == "ADD":
            await self._handle_add(data, trigger_text)
        elif intent == "CHECK":
            await self._handle_check(data)
        elif intent == "RENEW":
            await self._handle_renew(data, trigger_text)
        elif intent == "REMOVE":
            await self._handle_remove(data, trigger_text)
        elif intent == "COST":
            await self._handle_cost(data)
        elif intent == "STATUS":
            await self._handle_status(data, trigger_text)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run(self):
        try:
            trigger = await self.capability_worker.wait_for_complete_transcription()
            self.worker.editor_logging_handler.info(f"[LifeAdmin] Trigger: {trigger!r}")

            data = self._load_data()

            if not data.get("setup_complete"):
                await self._handle_setup(data)
                return

            intent = self._classify_intent(trigger or "")
            await self._dispatch(intent, data, trigger or "")

            while True:
                reply = await self.capability_worker.user_response()
                if reply is None:
                    break
                reply_clean = reply.strip()
                if not reply_clean:
                    break
                if trigger and reply_clean.lower() == trigger.strip().lower():
                    continue
                if self._is_exit(reply_clean):
                    break
                data = self._load_data()
                intent = self._classify_intent(reply_clean)
                if intent == "EXIT":
                    break
                await self._dispatch(intent, data, reply_clean)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[LifeAdmin] Error: {e!r}")
            await self.capability_worker.speak(
                "Something went wrong. Try again in a moment."
            )
        finally:
            self.capability_worker.resume_normal_flow()
