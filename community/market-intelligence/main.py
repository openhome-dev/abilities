import json
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

POLYMARKET_GAMMA_URL = "https://gamma-api.polymarket.com/markets"
COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"

MATCHING_HOTWORDS = [
    "market intelligence",
    "prediction market",
    "polymarket",
    "what's the market saying",
    "market prediction",
    "betting odds",
    "prediction odds",
    "market forecast",
    "geopolitical odds",
    "crypto market",
    "market update",
    "market brief",
    "what are the odds",
    "what does polymarket say",
    "election odds",
    "strike probability",
    "market sentiment",
]

CATEGORIES = {
    "geopolitics": [
        "iran", "israel", "strike", "war", "military", "sanctions",
        "china", "taiwan", "russia", "ukraine", "nato", "conflict",
        "diplomatic", "ceasefire", "invasion", "troops",
    ],
    "crypto": [
        "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "crypto",
        "token", "defi", "nft", "stablecoin", "exchange", "coinbase",
        "binance", "kraken", "mstr", "microstrategy",
    ],
    "macro": [
        "fed", "interest rate", "inflation", "gdp", "recession",
        "unemployment", "treasury", "yield", "dollar", "euro",
        "tariff", "trade", "debt ceiling", "deficit",
    ],
    "technology": [
        "ai", "artificial intelligence", "openai", "google", "apple",
        "microsoft", "nvidia", "semiconductor", "chip", "ipo",
        "acquisition", "merger", "startup", "valuation",
    ],
    "corporate": [
        "earnings", "stock", "shares", "revenue", "profit", "ceo",
        "board", "lawsuit", "sec", "regulation", "filing",
    ],
}

CRYPTO_IDS = {
    "bitcoin": "bitcoin",
    "btc": "bitcoin",
    "ethereum": "ethereum",
    "eth": "ethereum",
    "solana": "solana",
    "sol": "solana",
    "xrp": "ripple",
    "cardano": "cardano",
    "ada": "cardano",
    "dogecoin": "dogecoin",
    "doge": "dogecoin",
    "avalanche": "avalanche-2",
    "avax": "avalanche-2",
    "polkadot": "polkadot",
    "dot": "polkadot",
    "chainlink": "chainlink",
    "link": "chainlink",
    "polygon": "matic-network",
    "matic": "matic-network",
}


class WewrwewCapability(MatchingCapability):
    """Market intelligence via Polymarket prediction markets and CoinGecko."""

    CAPABILITY_NAME = "market-intelligence"

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        return cls(
            hotwords=MATCHING_HOTWORDS,
            agent_description=(
                "A market intelligence assistant that provides prediction "
                "market data from Polymarket and crypto prices from CoinGecko. "
                "Ask about geopolitical events, crypto markets, macro trends, "
                "or any topic with active prediction markets."
            ),
        )

    def call(self, worker: AgentWorker):
        user_input = self._best_initial_input()
        if not user_input:
            worker.speak(
                "I'm your market intelligence assistant. Ask me about "
                "prediction markets, crypto prices, or geopolitical odds. "
                "For example: 'What's the market saying about Iran?' or "
                "'How's Bitcoin doing?' Say stop to exit."
            )
            user_input = worker.listen()

        history = []
        while user_input and not self._is_exit(user_input):
            response = self._handle_query(user_input, history, worker)
            if response:
                worker.speak(response)
                history.append({"role": "user", "content": user_input})
                history.append({"role": "assistant", "content": response})
            else:
                worker.speak(
                    "I couldn't find relevant data for that query. "
                    "Try asking about a specific topic like Iran, Bitcoin, "
                    "or interest rates."
                )
            user_input = worker.listen()

        worker.speak("Goodbye!")

    def _best_initial_input(self) -> str:
        input_text = self.worker_input or ""
        if input_text and not self._looks_like_trigger_echo(input_text):
            return input_text
        return ""

    def _looks_like_trigger_echo(self, text: Optional[str]) -> bool:
        if not text:
            return False
        cleaned = text.strip().lower()
        for hw in MATCHING_HOTWORDS:
            if cleaned == hw.lower() or cleaned == hw.lower().rstrip("s"):
                return True
        return False

    def _is_exit(self, text: Optional[str]) -> bool:
        if not text:
            return True
        exit_words = {"stop", "exit", "quit", "bye", "goodbye", "done", "end"}
        return text.strip().lower() in exit_words

    def _handle_query(
        self, user_input: str, history: List[Dict], worker: AgentWorker
    ) -> Optional[str]:
        category = self._classify_query(user_input)

        if category == "crypto" and self._wants_price(user_input):
            return self._handle_crypto_price(user_input)

        markets = self._search_polymarket(user_input)
        if markets:
            return self._format_market_response(markets, user_input, worker)

        if category == "crypto":
            return self._handle_crypto_price(user_input)

        return None

    def _classify_query(self, text: str) -> str:
        text_lower = text.lower()
        scores = {}
        for cat, keywords in CATEGORIES.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[cat] = score
        if scores:
            return max(scores, key=scores.get)
        return "general"

    def _wants_price(self, text: str) -> bool:
        price_words = {"price", "trading", "worth", "cost", "how much", "doing"}
        text_lower = text.lower()
        return any(w in text_lower for w in price_words)

    def _search_polymarket(self, query: str) -> List[Dict]:
        try:
            params = {
                "limit": 10,
                "active": "true",
                "closed": "false",
            }
            clean_query = re.sub(
                r"\b(what|the|market|saying|about|does|polymarket|say|"
                r"are|odds|of|for|on|is|any|predictions?)\b",
                "",
                query.lower(),
            ).strip()
            if clean_query:
                params["tag_slug"] = clean_query.replace(" ", "-")

            resp = requests.get(
                POLYMARKET_GAMMA_URL, params=params, timeout=15
            )
            resp.raise_for_status()
            markets = resp.json()

            if not markets and clean_query:
                del params["tag_slug"]
                resp = requests.get(
                    POLYMARKET_GAMMA_URL,
                    params={**params, "limit": 50},
                    timeout=15,
                )
                resp.raise_for_status()
                all_markets = resp.json()
                keywords = clean_query.split()
                markets = [
                    m for m in all_markets
                    if any(
                        kw in m.get("question", "").lower()
                        or kw in m.get("description", "").lower()
                        for kw in keywords
                        if len(kw) > 2
                    )
                ][:10]

            return markets
        except requests.RequestException:
            return []

    def _format_market_response(
        self, markets: List[Dict], query: str, worker: AgentWorker
    ) -> str:
        if not markets:
            return None

        top = markets[:5]
        lines = []

        for m in top:
            question = m.get("question", "Unknown")
            outcomes = m.get("outcomePrices", "[]")
            if isinstance(outcomes, str):
                try:
                    outcomes = json.loads(outcomes)
                except (json.JSONDecodeError, TypeError):
                    outcomes = []

            if outcomes:
                try:
                    yes_prob = float(outcomes[0]) * 100
                    lines.append(f"{question}: {yes_prob:.0f}% chance of Yes.")
                except (ValueError, IndexError):
                    lines.append(f"{question}: odds unavailable.")
            else:
                lines.append(f"{question}: odds unavailable.")

        if len(markets) > 5:
            lines.append(
                f"Plus {len(markets) - 5} more related markets on Polymarket."
            )

        return " ".join(lines)

    def _handle_crypto_price(self, text: str) -> Optional[str]:
        text_lower = text.lower()
        target_id = None
        target_name = None

        for name, cg_id in CRYPTO_IDS.items():
            if name in text_lower:
                target_id = cg_id
                target_name = name.upper()
                break

        if not target_id:
            target_id = "bitcoin"
            target_name = "Bitcoin"

        try:
            resp = requests.get(
                f"{COINGECKO_BASE_URL}/simple/price",
                params={
                    "ids": target_id,
                    "vs_currencies": "usd",
                    "include_24hr_change": "true",
                    "include_market_cap": "true",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json().get(target_id, {})

            if not data:
                return f"Couldn't fetch price data for {target_name}."

            price = data.get("usd", 0)
            change = data.get("usd_24h_change", 0)
            mcap = data.get("usd_market_cap", 0)

            direction = "up" if change >= 0 else "down"
            mcap_b = mcap / 1e9 if mcap else 0

            response = (
                f"{target_name} is trading at ${price:,.2f}, "
                f"{direction} {abs(change):.1f}% in the last 24 hours."
            )
            if mcap_b > 0:
                response += f" Market cap: ${mcap_b:,.0f} billion."

            return response
        except requests.RequestException:
            return f"Having trouble reaching CoinGecko for {target_name} data."
