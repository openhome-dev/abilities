import json
import os
import re
import asyncio
from typing import Optional

import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


# Replace with your own API key from https://www.alphavantage.co/support/#api-key
API_KEY = "XXXXXXXXXXXXXXX"
BASE_URL = "https://www.alphavantage.co/query"
FRANKFURTER_URL = "https://api.frankfurter.app/latest"

EXIT_WORDS: list[str] = [
    "done", "exit", "stop", "quit", "bye", "goodbye",
    "nothing else", "all good", "nope", "no thanks", "i'm good",
    "thanks", "thank you", "thank", "no", "that's all", "that's it",
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

    def _fetch_spot_price_raw(self, metal: str = "GOLD") -> tuple[Optional[float], Optional[str]]:
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

    def _fetch_exchange_rate_raw(self, from_curr: str, to_curr: str) -> tuple[Optional[float], Optional[str]]:
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

    def _fetch_spot_in_currency(self, metal: str = "GOLD", currency: str = "EUR") -> Optional[str]:
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
        """Read the last user message from the Main Flow's conversation history.

        Returns:
            The user's last message, or empty string if unavailable.
        """
        try:
            history = self.worker.agent_memory.full_message_history
            for msg in reversed(history):
                if msg.get("role") == "user" and msg.get("content", "").strip():
                    return msg["content"].strip()
        except Exception:
            pass
        return ""


    def _is_exit(self, text: str) -> bool:
        """Check whether the user's input contains an exit phrase (whole-word match)."""
        if not text:
            return False
        lower = text.lower().strip()
        words = lower.split()
        for phrase in EXIT_WORDS:
            if " " in phrase:
                # Multi-word phrase: check substring
                if phrase in lower:
                    return True
            else:
                # Single word: check whole-word match
                if phrase in words:
                    return True
        return False


    async def handle_query(self, user_input: str) -> None:
        """Classify the user's intent, fetch data from the API, and speak the result.

        If the API call fails, offers the user a retry.

        Args:
            user_input: Raw transcribed text from the user.
        """
        intent = self.classify_intent(user_input)
        intent_type = intent.get("intent", "unknown")

        if intent_type == "gold_price":
            await self.capability_worker.speak("One sec, checking gold prices.")
            result = await asyncio.to_thread(self._fetch_spot_price, "GOLD")

        elif intent_type == "silver_price":
            await self.capability_worker.speak("One sec, checking silver prices.")
            result = await asyncio.to_thread(self._fetch_spot_price, "SILVER")

        elif intent_type == "spot_in_currency":
            metal = intent.get("metal") or "GOLD"
            currency = intent.get("to_currency") or "EUR"
            name = "gold" if metal == "GOLD" else "silver"
            await self.capability_worker.speak(
                f"One sec, checking {name} price in {currency}."
            )
            result = await asyncio.to_thread(
                self._fetch_spot_in_currency, metal, currency
            )

        elif intent_type == "exchange_rate":
            from_c = intent.get("from_currency") or "USD"
            to_c = intent.get("to_currency") or "EUR"
            await self.capability_worker.speak(
                f"Hang on, checking {from_c} to {to_c}."
            )
            result = await asyncio.to_thread(
                self._fetch_exchange_rate, from_c, to_c
            )

        else:
            await self.capability_worker.speak(
                "I didn't catch that. You can ask about gold, silver, or currency rates."
            )
            return

        if result:
            await self.capability_worker.speak(result)
        else:
            await self.capability_worker.speak(
                "I couldn't get that info. Want me to try again?"
            )
            retry_input = await self.capability_worker.user_response()
            if retry_input and any(
                w in retry_input.lower()
                for w in ["yes", "yeah", "retry", "try", "again", "please", "sure"]
            ):
                await self.handle_query(user_input)


    async def run(self) -> None:
        """Main entry point. Decides between Quick Mode and Full Mode.

        Quick Mode: If the trigger context has a clear intent, answer
        immediately and offer one follow-up.

        Full Mode: Greet the user and enter a multi-turn conversation
        loop with idle and exit detection.
        """
        try:
            trigger = self.get_trigger_context()

            if trigger:
                intent = self.classify_intent(trigger)
                if intent.get("intent") != "unknown":
                    # Quick Mode
                    await self.handle_query(trigger)
                    await self.capability_worker.speak("Need anything else on prices?")
                    follow_up = await self.capability_worker.user_response()

                    if follow_up and not self._is_exit(follow_up):
                        await self.handle_query(follow_up)

                    return

            # Full Mode
            await self.capability_worker.speak(
                "Market Pulse here. Ask me about exchange rates or gold prices."
            )

            idle_count = 0

            while True:
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    idle_count += 1
                    if idle_count >= 2:
                        await self.capability_worker.speak(
                            "I'll sign off. Say my trigger word if you need me."
                        )
                        break
                    continue

                idle_count = 0

                if self._is_exit(user_input):
                    await self.capability_worker.speak("Got it, signing off.")
                    break


                await self.handle_query(user_input)
                await self.capability_worker.speak("Anything else?")

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[MarketPulse] Error: {e}")
            await self.capability_worker.speak(
                "Something went wrong. Try again later."
            )
        finally:
            self.capability_worker.resume_normal_flow()