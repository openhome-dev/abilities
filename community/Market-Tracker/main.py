import json
import os
import re
from typing import ClassVar, List

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# Voice ID for "American, Mid-aged, Male, News" (used for strict decimal pronunciation)
VOICE_ID = "29vD33N1CtxCmqQRPOHJ"


class StockCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # NEW: Persistent Filename and Flag
    FILENAME: ClassVar[str] = "user_portfolio_v16.json"
    PERSIST: ClassVar[bool] = False  # temp=False means persistent

    # YOUR VERIFIED FINNHUB TOKEN
    FINNHUB_TOKEN: ClassVar[str] = "d67pa7hr01qobepis11gd67pa7hr01qobepis120"

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")) as file:
            data = json.load(file)
        return cls(unique_name=data["unique_name"], matching_hotwords=data["matching_hotwords"])

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run_main())

    # --- NEW PERSISTENT STORAGE METHODS ---
    async def get_portfolio(self) -> List[str]:
        """Properly handles reading from persistent storage."""
        if await self.capability_worker.check_if_file_exists(self.FILENAME, self.PERSIST):
            raw_content = await self.capability_worker.read_file(self.FILENAME, self.PERSIST)
            try:
                data = json.loads(raw_content)
                return [str(s) for s in data.get("list", [])]
            except Exception:
                return []
        return []

    async def save_portfolio(self, stocks: List[str]):
        """Follows the NEW pattern: Read -> Modify -> Delete -> Write."""
        # 1. Prepare data
        data_to_save = {"list": stocks}

        # 2. DELETE the old file (Crucial because write_file appends)
        if await self.capability_worker.check_if_file_exists(self.FILENAME, self.PERSIST):
            await self.capability_worker.delete_file(self.FILENAME, self.PERSIST)

        # 3. WRITE the fresh JSON object
        await self.capability_worker.write_file(self.FILENAME, json.dumps(data_to_save), self.PERSIST)
        self.worker.editor_logging_handler.info(f"Portfolio saved to persistent storage: {stocks}")

    # --- REAL-TIME DATA ENGINE ---
    def fetch_real_price(self, symbol: str) -> str:
        """
        Always returns a string. If Finnhub returns a numeric price, return
        a formatted string. If we fall back to llm_search and it returns a list,
        join it into a string.
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
                # Keep the numeric form in the raw result so we can deterministically format for TTS later.
                return f"{symbol} is ${float(price):.2f}"

            # Backup using native LLM Search — coerce to string safely
            llm_result = self.capability_worker.llm_search(f"current stock price for {symbol} ticker")
            # If llm_result is a list, join into a single string; else convert to str
            if isinstance(llm_result, list):
                llm_result = " ".join(map(str, llm_result))
            elif llm_result is None:
                llm_result = f"Data for {symbol} currently unavailable."
            return str(llm_result)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"fetch_real_price error for {symbol}: {e}")
            return f"Data for {symbol} currently unavailable."

    # --- Helpers to force "point" pronunciation and digit separation ---
    def _format_decimal_for_tts(self, number_str: str) -> str:
        """
        Convert a numeric string like '417.44' -> '417 point 4 4'
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

    def _make_tts_friendly_phrase(self, raw):
        """
        Convert strings like: "AAPL is $417.44" -> "AAPL is 417 point 4 4 dollars"
        """
        if isinstance(raw, (list, tuple)):
            raw_str = " | ".join(map(str, raw))
        else:
            raw_str = str(raw)

        pattern = re.compile(
            r"(?P<prefix>\b[A-Z0-9\.\-]+?\b)\s+is\s+\$?(?P<number>\d+(?:\.\d+)?)",
            flags=re.IGNORECASE
        )

        def repl(m):
            ticker = m.group("prefix")
            num = m.group("number")
            formatted_num = self._format_decimal_for_tts(num)
            return f"{ticker} is {formatted_num} dollars"

        replaced = pattern.sub(repl, raw_str)

        if replaced == raw_str:
            loose_money = re.compile(r"\$?(?P<number>\d+\.\d+)")

            def repl2(m):
                num = m.group("number")
                return f"{self._format_decimal_for_tts(num)} dollars"
            replaced = loose_money.sub(repl2, raw_str)

        replaced = replaced.strip()
        return replaced

    def _build_briefing_from_results(self, results: List[str]) -> str:
        """
        Build a short briefing from the raw results list.
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
            if len(phrases[mid:]) > 0 else ""
        )

        if second_sentence:
            return f"{first_sentence} {second_sentence}".strip()
        return first_sentence.strip()

    # --- MAIN CONVERSATION ---
    async def run_main(self):
        try:
            # 1. READ HISTORY
            history = self.worker.agent_memory.full_message_history
            user_msg = ""
            if history:
                msg_obj = history[-1]
                user_msg = msg_obj.content if hasattr(msg_obj, 'content') else str(msg_obj)

            # 2. EXTRACT TICKERS
            extraction_prompt = f"""
            Extract stock tickers from: '{user_msg}'. 
            Map 'Apple' to 'AAPL', 'Tesla' to 'TSLA'.
            Return ONLY tickers separated by commas. If none, return 'NONE'.
            """
            raw_tickers = self.capability_worker.text_to_text_response(
                extraction_prompt
            ).strip().upper().replace('"', '')
            extracted_list = [
                t.strip() for t in raw_tickers.split(",") if t.strip() and t != "NONE"
            ]

            # 3. LOAD PERSISTENT PORTFOLIO
            portfolio = await self.get_portfolio()

            # 4. HANDLE REMOVAL
            lower_msg = user_msg.lower()
            if any(word in lower_msg for word in ["remove", "delete", "delet"]):
                if any(x in lower_msg for x in ["remove all", "delete all", "clear"]):
                    if portfolio:
                        portfolio = []
                        await self.save_portfolio(portfolio)
                        await self.capability_worker.speak("All stocks removed.")
                    else:
                        await self.capability_worker.speak("Your portfolio is already empty.")
                    return

                if extracted_list:
                    removed_any = False
                    for t in extracted_list:
                        if t in portfolio:
                            portfolio.remove(t)
                            removed_any = True
                    if removed_any:
                        await self.save_portfolio(portfolio)
                        await self.capability_worker.speak(f"Removed {', '.join(extracted_list)}.")
                    else:
                        await self.capability_worker.speak("Those weren't in your list.")
                    return

            # 5. HANDLE ADDITION
            if "add" in user_msg.lower() and extracted_list:
                added_any = False
                for t in extracted_list:
                    if t not in portfolio:
                        portfolio.append(t)
                        added_any = True
                if added_any:
                    await self.save_portfolio(portfolio)
                await self.capability_worker.speak(f"Added {', '.join(extracted_list)}.")

            # 6. GENERATE BRIEFING
            tickers_to_check = list(set(portfolio + extracted_list))

            if not tickers_to_check:
                await self.capability_worker.speak("Your portfolio is empty.")
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
            await self.capability_worker.speak("I had a problem connecting to market data.")
        finally:
            self.capability_worker.resume_normal_flow()
