import json
import os
import re
from typing import Optional

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# Replace with your own API key from https://www.alphavantage.co/support/#api-key
API_KEY = "XXXXXXXXXXXXXXX"
BASE_URL = "https://www.alphavantage.co/query"
FRANKFURTER_URL = "https://api.frankfurter.app/latest"

EXIT_COMMANDS: list[str] = [
    "exit",
    "stop",
    "quit",
    "cancel",
]

EXIT_RESPONSES: list[str] = [
    "no",
    "nope",
    "done",
    "bye",
    "goodbye",
    "thanks",
    "thank",
    "thank you",
    "no thanks",
    "nothing else",
    "all good",
    "i'm good",
    "that's all",
    "that's it",
    "sign off",
    "i'm done",
    "that's enough",
    "no more",
    "we're done",
]

FORCE_EXIT_PHRASES: list[str] = [
    "market pulse out",
    "exit market pulse",
    "close market pulse",
    "shut down",
]


class MarketPulseAbility(MatchingCapability):
    """OpenHome ability for real-time currency exchange rates and commodity prices."""

    worker: Optional[AgentWorker] = None
    capability_worker: Optional[CapabilityWorker] = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        """Load config.json and register this ability with OpenHome."""
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker) -> None:
        """Entry point invoked by the OpenHome platform when the ability is triggered."""
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    def _fetch_exchange_rate(self, from_curr: str, to_curr: str) -> Optional[str]:
        """Fetch a formatted currency exchange rate from Alpha Vantage.
        Falls back to LLM for approximate rate if the API is unavailable.

        Args:
            from_curr: Source currency code (e.g. 'USD').
            to_curr: Target currency code (e.g. 'EUR').

        Returns:
            A spoken sentence with the rate.
        """
        rate, err = self._fetch_exchange_rate_raw(from_curr, to_curr)
        if rate:
            return f"1 {from_curr} equals {rate:.2f} {to_curr}."
        # API unavailable — LLM fallback
        return self.capability_worker.text_to_text_response(
            f"What is the current approximate exchange rate from {from_curr} to {to_curr}? "
            f"Reply with ONLY one short sentence like: '1 {from_curr} equals X.XX {to_curr}.'"
        )

    def _fetch_spot_price_raw(
        self, metal: str = "GOLD"
    ) -> tuple[Optional[float], Optional[str]]:
        """Fetch the raw spot price for a metal in USD.

        Args:
            metal: 'GOLD' or 'SILVER'.

        Returns:
            Tuple of (price, error_message). One will always be None.
        """
        try:
            resp = requests.get(
                BASE_URL,
                params={
                    "function": "GOLD_SILVER_SPOT",
                    "symbol": metal,
                    "apikey": API_KEY,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if "price" in data:
                    return float(data["price"]), None
                elif "Note" in data:
                    return None, "Rate limit hit. Try again in a minute."
                elif "Information" in data:
                    return None, "API limit reached."
                elif "Error Message" in data:
                    self.worker.editor_logging_handler.error(
                        f"[MarketPulse] API error: {data['Error Message']}"
                    )
                    return None, "Something went wrong with the API."
            return None, f"API returned status {resp.status_code}."
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[MarketPulse] {metal} price error: {e}"
            )
            return None, None

    def _fetch_spot_price(self, metal: str = "GOLD") -> Optional[str]:
        """Fetch a formatted gold or silver price string in USD.

        Args:
            metal: 'GOLD' or 'SILVER'.

        Returns:
            A spoken sentence with the price, or None on failure.
        """
        price, err = self._fetch_spot_price_raw(metal)
        name = "Gold" if metal == "GOLD" else "Silver"
        if price:
            return f"{name} is at {price:.2f} dollars per ounce."
        # API unavailable — LLM fallback
        return self.capability_worker.text_to_text_response(
            f"What is the current approximate {name.lower()} spot price per troy ounce in USD? "
            f"Reply with ONLY one short sentence like: '{name} is approximately XXXX.XX dollars per ounce.'"
        )

    def _fetch_exchange_rate_raw(
        self, from_curr: str, to_curr: str
    ) -> tuple[Optional[float], Optional[str]]:
        """Fetch the raw exchange rate. Tries Alpha Vantage first, then Frankfurter.

        Args:
            from_curr: Source currency code (e.g. 'USD').
            to_curr: Target currency code (e.g. 'EUR').

        Returns:
            Tuple of (rate, error_message). One will always be None.
        """
        # Tier 1: Alpha Vantage
        try:
            resp = requests.get(
                BASE_URL,
                params={
                    "function": "CURRENCY_EXCHANGE_RATE",
                    "from_currency": from_curr,
                    "to_currency": to_curr,
                    "apikey": API_KEY,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if "Realtime Currency Exchange Rate" in data:
                    rate = data["Realtime Currency Exchange Rate"]["5. Exchange Rate"]
                    return float(rate), None
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[MarketPulse] Alpha Vantage exchange rate error: {e}"
            )

        # Tier 2: Frankfurter (free, no API key, no rate limit)
        try:
            resp = requests.get(
                FRANKFURTER_URL,
                params={"from": from_curr, "to": to_curr},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                rates = data.get("rates", {})
                if to_curr in rates:
                    return float(rates[to_curr]), None
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[MarketPulse] Frankfurter exchange rate error: {e}"
            )

        return None, "Both exchange rate APIs unavailable."

    def _fetch_spot_in_currency(
        self, metal: str = "GOLD", currency: str = "EUR"
    ) -> Optional[str]:
        """Fetch spot price in USD and convert to another currency via LLM.

        Uses a single API call for the spot price, then asks the LLM to
        approximate the currency conversion (saves API quota).

        Args:
            metal: 'GOLD' or 'SILVER'.
            currency: Target currency code (e.g. 'EUR', 'GBP').

        Returns:
            A spoken sentence with the converted price, or None on failure.
        """
        price_usd, err = self._fetch_spot_price_raw(metal)
        name = "Gold" if metal == "GOLD" else "Silver"
        if price_usd:
            # Got real price, use LLM just for conversion
            return self.capability_worker.text_to_text_response(
                f"{name} is ${price_usd:.2f} USD per ounce. "
                f"Convert this to {currency} using current approximate rates. "
                f"Reply with ONLY one short sentence like: "
                f"'{name} is at XXXX.XX {currency} per ounce.'"
            )
        # API unavailable — LLM fallback for full estimate
        return self.capability_worker.text_to_text_response(
            f"What is the current approximate {name.lower()} spot price per troy ounce in {currency}? "
            f"Reply with ONLY one short sentence like: '{name} is approximately XXXX.XX {currency} per ounce.'"
        )

    def classify_intent(self, user_input: str) -> dict:
        """Classify the user's intent from voice-transcribed input using the LLM.

        Handles messy speech-to-text by instructing the LLM to guess through
        common transcription errors (e.g. 'goal' → 'gold').

        Args:
            user_input: Raw transcribed text from the user.

        Returns:
            Dict with keys: intent, metal, from_currency, to_currency.
        """
        prompt = (
            "You are classifying voice-transcribed input. The transcription may be "
            "garbled or misspelled because it comes from speech-to-text. "
            "Use your best guess. Examples of STT errors:\n"
            "- 'goal' or 'gol' probably means 'gold'\n"
            "- 'process' or 'prices' probably means 'price'\n"
            "- 'silver' or 'solver' probably means 'silver'\n"
            "- 'dollar' 'euro' 'pound' 'yen' mean currency exchange\n\n"
            "Intent types:\n"
            "- gold_price: gold price in USD (no other currency mentioned)\n"
            "- silver_price: silver price in USD (no other currency mentioned)\n"
            "- spot_in_currency: gold or silver price in a NON-USD currency "
            "(e.g. 'gold in euro', 'silver in pounds')\n"
            "- exchange_rate: converting between two fiat currencies\n"
            "- unknown: can't determine\n\n"
            "Return ONLY valid JSON, no markdown:\n"
            '{"intent": "...", "metal": "GOLD" or "SILVER" or null, '
            '"from_currency": "3-letter code or null", '
            '"to_currency": "3-letter code or null"}\n\n'
            "IMPORTANT: If the user mentions anything that sounds like gold, "
            "prices, market, commodity — classify it, do NOT return unknown.\n\n"
            f"User said: {user_input}"
        )
        raw = self.capability_worker.text_to_text_response(prompt)
        clean = raw.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            return {"intent": "unknown"}

    def get_trigger_context(self) -> str:
        """Get the initial transcription that triggered this ability.

        Tries worker.transcription first, then worker.last_transcription.
        """
        initial_request = None
        try:
            initial_request = self.worker.transcription
        except (AttributeError, Exception):
            pass

        if not initial_request:
            try:
                initial_request = self.worker.last_transcription
            except (AttributeError, Exception):
                pass

        return initial_request.strip() if initial_request else ""

    @staticmethod
    def _clean_input(text: str) -> str:
        """Lowercase and strip punctuation from STT transcription.

        Converts 'Exit.' → 'exit', 'Gold, please!' → 'gold please', etc.
        """
        if not text:
            return ""
        # Lowercase, strip whitespace, remove all punctuation except apostrophes
        cleaned = text.lower().strip()
        cleaned = re.sub(r"[^\w\s']", "", cleaned)
        return cleaned.strip()

    def _is_exit(self, text: str) -> bool:
        """Hybrid exit detection: force-exit → keyword match → phrase match.

        Processes cleaned (lowercased, punctuation-stripped) input through
        three tiers to robustly detect exit intent.

        Args:
            text: Raw transcribed text from the user.

        Returns:
            True if the user wants to exit.
        """
        if not text:
            return False
        cleaned = self._clean_input(text)
        if not cleaned:
            return False

        # Tier 1: Force-exit phrases (instant shutdown)
        for phrase in FORCE_EXIT_PHRASES:
            if phrase in cleaned:
                return True

        # Tier 2: Exit Commands (Anywhere in the sentence)
        words = cleaned.split()
        for cmd in EXIT_COMMANDS:
            if cmd in words:
                return True

        # Tier 3: Exit Responses (Must be exact match or start of sentence)
        # We check if cleaned input IS one of these, or STARTS with one of them
        # to allow "No thanks" or "No, I'm good".
        for resp in EXIT_RESPONSES:
            if cleaned == resp:
                return True
            if cleaned.startswith(f"{resp} "):
                return True

        return False

    def _is_exit_llm(self, text: str) -> bool:
        """Use the LLM to classify ambiguous exit intent.

        Only called when keyword matching fails but the input is short
        and doesn't look like a market query.

        Args:
            text: Cleaned user input.

        Returns:
            True if the LLM thinks the user wants to exit.
        """
        try:
            result = self.capability_worker.text_to_text_response(
                "Does this message mean the user wants to END the conversation? "
                "Reply with ONLY 'yes' or 'no'.\n\n"
                f'Message: "{text}"'
            )
            return result.strip().lower().startswith("yes")
        except Exception:
            return False

    async def _process_query(self, user_input: str) -> bool:
        """Process a single user query. Returns True if successful, False if failed/retry needed."""
        intent = self.classify_intent(user_input)
        intent_type = intent.get("intent", "unknown")
        result = None

        if intent_type == "gold_price":
            await self.capability_worker.speak("Checking gold prices...")
            result = self._fetch_spot_price("GOLD")

        elif intent_type == "silver_price":
            await self.capability_worker.speak("Checking silver prices...")
            result = self._fetch_spot_price("SILVER")

        elif intent_type == "spot_in_currency":
            metal = intent.get("metal") or "GOLD"
            currency = intent.get("to_currency") or "EUR"
            name = "gold" if metal == "GOLD" else "silver"
            await self.capability_worker.speak(
                f"Checking {name} price in {currency}..."
            )
            result = self._fetch_spot_in_currency(metal, currency)

        elif intent_type == "exchange_rate":
            from_c = intent.get("from_currency") or "USD"
            to_c = intent.get("to_currency") or "EUR"
            await self.capability_worker.speak(f"Checking {from_c} to {to_c}...")
            result = self._fetch_exchange_rate(from_c, to_c)

        else:
            # Fallback for unknown queries
            fallback_response = self.capability_worker.text_to_text_response(
                f'You are Market Pulse, a professional price-tracking assistant. The user said: "{user_input}". '
                "If they are greeting you, greet them professionally. "
                "If they are chatting or asking something else, briefly explain that you track gold, silver, and exchange rates. "
                "Keep your response concise and professional, under 2 short sentences."
            )
            await self.capability_worker.speak(fallback_response)
            return True

        if result:
            await self.capability_worker.speak(result)
            return True

        return False

    async def handle_query_with_retry(self, user_input: str) -> None:
        """Handle query with one non-recursive retry."""
        success = await self._process_query(user_input)
        if not success:
            await self.capability_worker.speak(
                "I was unable to retrieve that information. Would you like me to try again?"
            )
            retry_input = await self.capability_worker.user_response()
            if retry_input and any(
                w in retry_input.lower()
                for w in ["yes", "yeah", "retry", "try", "again", "please", "sure"]
            ):
                await self._process_query(user_input)

    async def run(self) -> None:
        """Main entry point. Decides between Quick Mode and Full Mode.

        Quick Mode: If the trigger context has a clear intent, answer
        immediately and offer one follow-up.

        Full Mode: Greet the user and enter a multi-turn conversation
        loop with hybrid exit detection.
        """
        try:
            trigger = self.get_trigger_context()

            if trigger:
                cleaned = self._clean_input(trigger)
                # Check if the trigger itself is an exit command
                if cleaned and not self._is_exit(cleaned):
                    intent = self.classify_intent(cleaned)
                    if intent.get("intent") != "unknown":
                        # Quick Mode
                        await self.handle_query_with_retry(trigger)
                        await self.capability_worker.speak(
                            "Do you have any other questions regarding prices?"
                        )
                        follow_up = await self.capability_worker.user_response()

                        if follow_up and not self._is_exit(follow_up):
                            await self.handle_query_with_retry(follow_up)

                        await self.capability_worker.speak("Goodbye.")
                        return

            # Full Mode
            await self.capability_worker.speak(
                "Market Pulse here. Ask me about exchange rates or gold prices."
            )

            idle_count = 0
            max_interactions = 20

            for _ in range(max_interactions):
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    idle_count += 1
                    if idle_count >= 2:
                        await self.capability_worker.speak(
                            "Signing off. Please activate me if you need assistance."
                        )
                        break
                    continue

                idle_count = 0

                # --- Hybrid exit detection ---
                if self._is_exit(user_input):
                    await self.capability_worker.speak("Goodbye.")
                    break

                # Short ambiguous input — ask LLM if it's an exit
                cleaned = self._clean_input(user_input)
                if len(cleaned.split()) <= 4 and self._is_exit_llm(cleaned):
                    await self.capability_worker.speak("Goodbye.")
                    break

                await self.handle_query_with_retry(user_input)
                await self.capability_worker.speak("Is there anything else?")

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[MarketPulse] Error: {e}")
            await self.capability_worker.speak("Something went wrong. Try again later.")
        finally:
            self.capability_worker.resume_normal_flow()
