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

    FILENAME: ClassVar[str] = "user_portfolio_v16.json"
    PERSIST: ClassVar[bool] = False
    FINNHUB_TOKEN: ClassVar[str] = "d67pa7hr01qobepis11gd67pa7hr01qobepis120"

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
        self.worker.session_tasks.create(self.run_main())

    async def get_portfolio(self) -> List[str]:
        if await self.capability_worker.check_if_file_exists(
            self.FILENAME, self.PERSIST
        ):
            raw_content = await self.capability_worker.read_file(
                self.FILENAME, self.PERSIST
            )
            try:
                data = json.loads(raw_content)
                return [str(s) for s in data.get("list", [])]
            except Exception:
                return []
        return []

    async def save_portfolio(self, stocks: List[str]):
        data_to_save = {"list": stocks}

        if await self.capability_worker.check_if_file_exists(
            self.FILENAME, self.PERSIST
        ):
            await self.capability_worker.delete_file(
                self.FILENAME, self.PERSIST
            )

        await self.capability_worker.write_file(
            self.FILENAME,
            json.dumps(data_to_save),
            self.PERSIST,
        )

        self.worker.editor_logging_handler.info(
            f"Portfolio saved to persistent storage: {stocks}"
        )

    def fetch_real_price(self, symbol: str) -> str:
        symbol = str(symbol).strip().upper().replace('"', "")

        try:
            url = (
                f"https://finnhub.io/api/v1/quote?"
                f"symbol={symbol}&token={self.FINNHUB_TOKEN}"
            )
            response = requests.get(url, timeout=8)

            try:
                data = response.json()
            except Exception:
                data = {}

            price = None
            if isinstance(data, dict):
                price = data.get("c")

            self.worker.editor_logging_handler.info(
                f"FETCHING REAL DATA for {symbol}: {price}"
            )

            if price is not None and price != 0:
                return f"{symbol} is ${float(price):.2f}"

            llm_result = self.capability_worker.llm_search(
                f"current stock price for {symbol} ticker"
            )

            if isinstance(llm_result, list):
                llm_result = " ".join(map(str, llm_result))
            elif llm_result is None:
                llm_result = (
                    f"Data for {symbol} currently unavailable."
                )

            return str(llm_result)

        except Exception as error:
            self.worker.editor_logging_handler.error(
                f"fetch_real_price error for {symbol}: {error}"
            )
            return f"Data for {symbol} currently unavailable."

    def _format_decimal_for_tts(self, number_str: str) -> str:
        if "." not in number_str:
            return number_str

        int_part, frac_part = number_str.split(".", 1)

        try:
            int_part_clean = str(int(int_part))
        except Exception:
            int_part_clean = int_part

        frac_digits = " ".join(list(frac_part))
        return f"{int_part_clean} point {frac_digits}"

    def _make_tts_friendly_phrase(self, raw: str) -> str:
        if isinstance(raw, (list, tuple)):
            raw_str = " | ".join(map(str, raw))
        else:
            raw_str = str(raw)

        pattern = re.compile(
            r"(?P<prefix>\b[A-Z0-9\.\-]+?\b)\s+is\s+\$?"
            r"(?P<number>\d+(?:\.\d+)?)",
            flags=re.IGNORECASE,
        )

        def repl(match):
            ticker = match.group("prefix")
            number = match.group("number")
            formatted = self._format_decimal_for_tts(number)
            return f"{ticker} is {formatted} dollars"

        replaced = pattern.sub(repl, raw_str)

        if replaced == raw_str:

            loose_money = re.compile(r"\$?(?P<number>\d+\.\d+)")

            def repl2(match):
                number = match.group("number")
                formatted = self._format_decimal_for_tts(number)
                return f"{formatted} dollars"

            replaced = loose_money.sub(repl2, raw_str)

        return replaced.strip()

    def _build_briefing_from_results(
        self, results: List[str]
    ) -> str:
        phrases = [
            self._make_tts_friendly_phrase(str(r))
            for r in results
        ]

        if not phrases:
            return ""

        if len(phrases) == 1:
            return phrases[0].rstrip(".") + "."

        mid = (len(phrases) + 1) // 2

        first_sentence = (
            ". ".join(p.rstrip(".") for p in phrases[:mid])
            + "."
        )

        second_sentence = ""
        if phrases[mid:]:
            second_sentence = (
                ". ".join(
                    p.rstrip(".") for p in phrases[mid:]
                )
                + "."
            )

        return f"{first_sentence} {second_sentence}".strip()

    async def run_main(self):
        try:
            history = (
                self.worker.agent_memory.full_message_history
            )
            user_msg = ""

            if history:
                msg_obj = history[-1]
                user_msg = (
                    msg_obj.content
                    if hasattr(msg_obj, "content")
                    else str(msg_obj)
                )

            extraction_prompt = f"""
            Extract stock tickers from: '{user_msg}'.
            Map 'Apple' to 'AAPL', 'Tesla' to 'TSLA'.
            Return ONLY tickers separated by commas.
            If none, return 'NONE'.
            """

            raw_tickers = (
                self.capability_worker
                .text_to_text_response(extraction_prompt)
                .strip()
                .upper()
                .replace('"', "")
            )

            extracted_list = [
                ticker.strip()
                for ticker in raw_tickers.split(",")
                if ticker.strip() and ticker != "NONE"
            ]

            portfolio = await self.get_portfolio()
            lower_msg = user_msg.lower()

            if any(
                word in lower_msg
                for word in ["remove", "delete", "delet"]
            ):

                if (
                    "remove all" in lower_msg
                    or "delete all" in lower_msg
                    or "clear" in lower_msg
                ):
                    if portfolio:
                        portfolio = []
                        await self.save_portfolio(portfolio)
                        await self.capability_worker.speak(
                            "All stocks have been removed from your permanent list."
                        )
                    else:
                        await self.capability_worker.speak(
                            "Your portfolio is already empty."
                        )
                    return

                if extracted_list:
                    removed_items = []
                    not_found = []

                    for ticker in extracted_list:
                        if ticker in portfolio:
                            portfolio.remove(ticker)
                            removed_items.append(ticker)
                        else:
                            not_found.append(ticker)

                    if removed_items:
                        await self.save_portfolio(portfolio)
                        message = (
                            f"Removed {', '.join(removed_items)} "
                            "from your permanent list."
                        )

                        if not_found:
                            message += (
                                f" Note: {', '.join(not_found)} "
                                "were not in your portfolio."
                            )

                        await self.capability_worker.speak(
                            message
                        )
                    else:
                        await self.capability_worker.speak(
                            f"None of {', '.join(extracted_list)} "
                            "were in your portfolio."
                        )
                    return

                await self.capability_worker.speak(
                    "Tell me which stocks to remove."
                )
                return

            if "add" in lower_msg and extracted_list:
                added_any = False

                for ticker in extracted_list:
                    if ticker not in portfolio:
                        portfolio.append(ticker)
                        added_any = True

                if added_any:
                    await self.save_portfolio(portfolio)

                await self.capability_worker.speak(
                    f"Added {', '.join(extracted_list)} "
                    "to your permanent list."
                )

            tickers_to_check = list(
                set(portfolio + extracted_list)
            )

            if not tickers_to_check:
                await self.capability_worker.speak(
                    "Your portfolio is empty."
                )
                return

            await self.capability_worker.speak(
                "Checking the latest market prices."
            )

            results = [
                self.fetch_real_price(symbol)
                for symbol in tickers_to_check
            ]

            briefing = self._build_briefing_from_results(
                results
            )

            try:
                await self.capability_worker.text_to_speech(
                    briefing,
                    VOICE_ID,
                )
            except Exception:
                await self.capability_worker.speak(
                    briefing
                )

        except Exception as error:
            self.worker.editor_logging_handler.error(
                f"Error: {error}"
            )
            await self.capability_worker.speak(
                "I had a problem connecting to the market data."
            )
        finally:
            self.capability_worker.resume_normal_flow()
