import json
import os
import re
from typing import ClassVar, List, Optional

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# Voice ID for "American, Mid-aged, Male, News" (used for strict decimal pronunciation)
VOICE_ID = "29vD33N1CtxCmqQRPOHJ"


class StockCapability(MatchingCapability):
    worker: Optional[AgentWorker] = None
    capability_worker: Optional[CapabilityWorker] = None

    # Persistent Filename and Flag
    FILENAME: ClassVar[str] = "user_portfolio_v16.json"
    PERSIST: ClassVar[bool] = False  # False => persistent storage

    # Finnhub token (replace with a valid token)
    FINNHUB_TOKEN: ClassVar[str] = "d67pa7hr01qobepis11gd67pa7hr01qobepis120"

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")) as file:
            data = json.load(file)
        return cls(unique_name=data["unique_name"], matching_hotwords=data["matching_hotwords"])

    def call(self, worker: AgentWorker) -> None:
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run_main())

    # --- Persistent storage helpers ---
    async def get_portfolio(self) -> List[str]:
        """Read portfolio from persistent storage if present."""
        if await self.capability_worker.check_if_file_exists(self.FILENAME, self.PERSIST):
            raw_content = await self.capability_worker.read_file(self.FILENAME, self.PERSIST)
            try:
                data = json.loads(raw_content)
                return [str(s) for s in data.get("list", [])]
            except Exception:
                return []
        return []

    async def save_portfolio(self, stocks: List[str]) -> None:
        """Write portfolio using delete-then-write to avoid append behavior."""
        data_to_save = {"list": stocks}

        if await self.capability_worker.check_if_file_exists(self.FILENAME, self.PERSIST):
            await self.capability_worker.delete_file(self.FILENAME, self.PERSIST)

        await self.capability_worker.write_file(self.FILENAME, json.dumps(data_to_save), self.PERSIST)
        self.worker.editor_logging_handler.info(f"Portfolio saved to persistent storage: {stocks}")

    # --- Real-time data fetch ---
    def fetch_real_price(self, symbol: str) -> str:
        """
        Fetch current quote from Finnhub. If unavailable, fall back to LLM search.
        Always returns a string suitable for further TTS formatting.
        """
        symbol = str(symbol).strip().upper().replace('"', '')
        try:
            url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={self.FINNHUB_TOKEN}"
            r = requests.get(url, timeout=8)
            try:
                data = r.json()
            except Exception:
                data = {}

            price = None
            if isinstance(data, dict):
                price = data.get("c")

            self.worker.editor_logging_handler.info(f"FETCHING REAL DATA for {symbol}: {price}")

            if price is not None and price != 0:
                return f"{symbol} is ${float(price):.2f}"

            # LLM fallback
            llm_result = self.capability_worker.llm_search(f"current stock price for {symbol} ticker")
            if isinstance(llm_result, list):
                llm_result = " ".join(map(str, llm_result))
            elif llm_result is None:
                llm_result = f"Data for {symbol} currently unavailable."
            return str(llm_result)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"fetch_real_price error for {symbol}: {e}")
            return f"Data for {symbol} currently unavailable."

    # --- TTS helpers (force 'point' pronunciation) ---
    def _format_decimal_for_tts(self, number_str: str) -> str:
        """
        Convert a numeric string like '417.44' -> '417 point 4 4'.
        If input has no decimal point, return unchanged.
        """
        if "." not in number_str:
            return number_str
        int_part, frac_part = number_str.split(".", 1)
        try:
            int_part_clean = str(int(int_part))
        except Exception:
            int_part_clean = int_part
        frac_digits = " ".join(list(frac_part))
        return f"{int_part_clean} point {frac_digits}"

    def _make_tts_friendly_phrase(self, raw) -> str:
        """
        Turn strings like "AAPL is $417.44" -> "AAPL is 417 point 4 4 dollars".
        Defensive: coerce lists/tuples to a joined string.
        """
        if isinstance(raw, (list, tuple)):
            raw_str = " | ".join(map(str, raw))
        else:
            raw_str = str(raw)

        # Pattern captures: <TICKER> is $123.45
        pattern = re.compile(
            r"(?P<prefix>\b[A-Z0-9\.\-]+?\b)\s+is\s+\$?(?P<number>\d+(?:\.\d+)?)",
            flags=re.IGNORECASE,
        )

        def repl(m):
            ticker = m.group("prefix")
            num = m.group("number")
            formatted_num = self._format_decimal_for_tts(num)
            return f"{ticker} is {formatted_num} dollars"

        replaced = pattern.sub(repl, raw_str)

        # Looser match for $numbers if nothing matched
        if replaced == raw_str:
            loose_money = re.compile(r"\$?(?P<number>\d+\.\d+)")

            def repl2(m):
                num = m.group("number")
                return f"{self._format_decimal_for_tts(num)} dollars"

            replaced = loose_money.sub(repl2, raw_str)

        return replaced.strip()

    def _build_briefing_from_results(self, results: List[str]) -> str:
        """
        Build a short deterministic briefing (max 2 sentences) for TTS from results.
        """
        phrases = [self._make_tts_friendly_phrase(str(r)) for r in results]

        if not phrases:
            return ""

        if len(phrases) == 1:
            return phrases[0].rstrip(".") + "."

        mid = (len(phrases) + 1) // 2
        first_sentence = ". ".join(p.rstrip(".") for p in phrases[:mid]) + "."
        second_sentence = (
            ". ".join(p.rstrip(".") for p in phrases[mid:]) + "."
            if len(phrases[mid:]) > 0
            else ""
        )

        if second_sentence:
            return f"{first_sentence} {second_sentence}".strip()
        return first_sentence.strip()

    # --- Main conversation flow ---
    async def run_main(self) -> None:
        try:
            history = self.worker.agent_memory.full_message_history
            user_msg = ""
            if history:
                msg_obj = history[-1]
                user_msg = msg_obj.content if hasattr(msg_obj, "content") else str(msg_obj)

            # Extract tickers via LLM helper (simple prompt)
            extraction_prompt = (
                f"Extract stock tickers from: '{user_msg}'. "
                "Map 'Apple' to 'AAPL', 'Tesla' to 'TSLA'. "
                "Return ONLY tickers separated by commas. If none, return 'NONE'."
            )
            raw_tickers = (
                self.capability_worker.text_to_text_response(extraction_prompt)
                .strip()
                .upper()
                .replace('"', "")
            )
            extracted_list = [t.strip() for t in raw_tickers.split(",") if t.strip() and t != "NONE"]

            # Load persistent portfolio
            portfolio = await self.get_portfolio()

            lower_msg = user_msg.lower()
            if any(word in lower_msg for word in ["remove", "delete", "delet"]):
                # Remove all
                if "remove all" in lower_msg or "delete all" in lower_msg or "clear" in lower_msg:
                    if portfolio:
                        portfolio = []
                        await self.save_portfolio(portfolio)
                        await self.capability_worker.speak("All stocks have been removed from your permanent list.")
                    else:
                        await self.capability_worker.speak("Your portfolio is already empty.")
                    self.worker.editor_logging_handler.info("Performed 'remove all' on portfolio.")
                    return

                # Remove specific tickers
                if extracted_list:
                    removed_any = False
                    not_found = []
                    removed_items = []
                    for t in extracted_list:
                        if t in portfolio:
                            portfolio.remove(t)
                            removed_any = True
                            removed_items.append(t)
                        else:
                            not_found.append(t)
                    if removed_any:
                        await self.save_portfolio(portfolio)
                        msg = f"Removed {', '.join(removed_items)} from your permanent list."
                        if not_found:
                            msg += f" Note: {', '.join(not_found)} were not in your portfolio."
                        await self.capability_worker.speak(msg)
                    else:
                        await self.capability_worker.speak(f"None of {', '.join(extracted_list)} were in your portfolio.")
                    self.worker.editor_logging_handler.info(f"Removal attempted. Removed: {removed_items}, Not found: {not_found}")
                    return
                else:
                    await self.capability_worker.speak("Tell me which stocks to remove, for example: 'remove AAPL' or 'remove Apple'.")
                    return

            # Addition
            if "add" in user_msg.lower() and extracted_list:
                added_any = False
                for t in extracted_list:
                    if t not in portfolio:
                        portfolio.append(t)
                        added_any = True
                if added_any:
                    await self.save_portfolio(portfolio)
                await self.capability_worker.speak(f"Got it. I've added {', '.join(extracted_list)} to your permanent list.")

            # Build briefing
            tickers_to_check = list(set(portfolio + extracted_list))
            if not tickers_to_check:
                await self.capability_worker.speak("Your portfolio is empty. Tell me to add a stock to get started.")
            else:
                await self.capability_worker.speak("Checking the latest market prices.")
                results = [self.fetch_real_price(s) for s in tickers_to_check]
                briefing_for_tts = self._build_briefing_from_results(results)

                try:
                    await self.capability_worker.text_to_speech(briefing_for_tts, VOICE_ID)
                except Exception:
                    await self.capability_worker.speak(briefing_for_tts)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Error: {e}")
            await self.capability_worker.speak("I had a problem connecting to the market data.")
        finally:
            self.capability_worker.resume_normal_flow()
