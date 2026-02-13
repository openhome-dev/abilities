import json
import os
import re
import requests
from typing import Dict, List, Optional, Tuple
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# CRYPTO INSIGHT ABILITY
# Provides real-time cryptocurrency price analysis with technical indicators
# Uses CoinGecko free API (no authentication required)
# =============================================================================

# --- COINGECKO API ENDPOINTS ---
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
PRICE_ENDPOINT = f"{COINGECKO_BASE}/simple/price"
OHLC_ENDPOINT = f"{COINGECKO_BASE}/coins/{{coin_id}}/ohlc"
SEARCH_ENDPOINT = f"{COINGECKO_BASE}/search"

# --- POPULAR CRYPTO MAPPINGS ---
# Common names/symbols to CoinGecko IDs
CRYPTO_MAP = {
    "bitcoin": "bitcoin",
    "btc": "bitcoin",
    "ethereum": "ethereum",
    "eth": "ethereum",
    "dogecoin": "dogecoin",
    "doge": "dogecoin",
    "cardano": "cardano",
    "ada": "cardano",
    "solana": "solana",
    "sol": "solana",
    "ripple": "ripple",
    "xrp": "ripple",
    "polkadot": "polkadot",
    "dot": "polkadot",
    "litecoin": "litecoin",
    "ltc": "litecoin",
    "chainlink": "chainlink",
    "link": "chainlink",
    "matic": "matic-network",
    "polygon": "matic-network",
}


class CryptoInsightCapability(MatchingCapability):
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

    def _log_info(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.info(msg)

    def _log_error(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.error(msg)

    def _extract_crypto_name(self, text: str) -> str:
        """Extract cryptocurrency name from user input."""
        # Common patterns: "what's bitcoin doing", "check ethereum", "bitcoin price"
        text_lower = text.lower().strip()
        
        # Remove common words
        for word in ["what's", "whats", "check", "price", "doing", "crypto", "cryptocurrency"]:
            text_lower = text_lower.replace(word, "")
        
        text_lower = text_lower.strip()
        
        # Try to find a known crypto
        for key in CRYPTO_MAP:
            if key in text_lower:
                return key
        
        # Return first word if nothing matches
        words = text_lower.split()
        return words[0] if words else "bitcoin"

    def _map_to_coin_id(self, crypto_name: str) -> str:
        """Map user input to CoinGecko coin ID."""
        crypto_lower = crypto_name.lower().strip()
        return CRYPTO_MAP.get(crypto_lower, crypto_lower)

    def search_coin(self, query: str) -> Optional[str]:
        """
        Search CoinGecko for a coin and return its ID.
        Falls back to query as-is if search fails.
        """
        try:
            self._log_info(f"[CryptoInsight] Searching for: {query}")
            response = requests.get(
                SEARCH_ENDPOINT,
                params={"query": query},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                coins = data.get("coins", [])
                if coins:
                    coin_id = coins[0]["id"]
                    self._log_info(f"[CryptoInsight] Found coin: {coin_id}")
                    return coin_id
            
            # Fallback to using query as coin_id
            self._log_info(f"[CryptoInsight] Using query as coin_id: {query}")
            return query
            
        except Exception as e:
            self._log_error(f"[CryptoInsight] Search error: {e}")
            return query

    def fetch_price_data(self, coin_id: str) -> Optional[Dict]:
        """
        Fetch current price and 24h change from CoinGecko.
        Returns dict with price, change_24h, or None on failure.
        """
        try:
            self._log_info(f"[CryptoInsight] Fetching price for: {coin_id}")
            response = requests.get(
                PRICE_ENDPOINT,
                params={
                    "ids": coin_id,
                    "vs_currencies": "usd",
                    "include_24hr_change": "true"
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if coin_id in data:
                    coin_data = data[coin_id]
                    return {
                        "price": coin_data.get("usd"),
                        "change_24h": coin_data.get("usd_24h_change")
                    }
                else:
                    self._log_error(f"[CryptoInsight] Coin not found in response: {coin_id}")
                    return None
            else:
                self._log_error(f"[CryptoInsight] Price API returned {response.status_code}")
                return None
                
        except Exception as e:
            self._log_error(f"[CryptoInsight] Price fetch error: {e}")
            return None

    def fetch_ohlc_data(self, coin_id: str, days: int = 14) -> Optional[List[float]]:
        """
        Fetch OHLC (candlestick) data and return closing prices.
        Returns list of closing prices, or None on failure.
        """
        try:
            self._log_info(f"[CryptoInsight] Fetching OHLC for: {coin_id}")
            url = OHLC_ENDPOINT.format(coin_id=coin_id)
            response = requests.get(
                url,
                params={
                    "vs_currency": "usd",
                    "days": str(days)
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                # OHLC format: [[timestamp, open, high, low, close], ...]
                # Extract closing prices (index 4)
                closes = [candle[4] for candle in data]
                self._log_info(f"[CryptoInsight] Got {len(closes)} closing prices")
                return closes
            else:
                self._log_error(f"[CryptoInsight] OHLC API returned {response.status_code}")
                return None
                
        except Exception as e:
            self._log_error(f"[CryptoInsight] OHLC fetch error: {e}")
            return None

    def calculate_rsi(self, closes: List[float], period: int = 14) -> Optional[float]:
        """
        Calculate RSI (Relative Strength Index).
        Returns RSI value (0-100), or None if insufficient data.
        """
        if len(closes) < period + 1:
            return None
        
        try:
            # Calculate price changes
            changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
            
            # Separate gains and losses
            gains = [max(change, 0) for change in changes]
            losses = [max(-change, 0) for change in changes]
            
            # Calculate average gain and loss over period
            avg_gain = sum(gains[-period:]) / period
            avg_loss = sum(losses[-period:]) / period
            
            # Calculate RSI
            if avg_loss == 0:
                return 100.0
            
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
            self._log_info(f"[CryptoInsight] RSI calculated: {rsi:.1f}")
            return rsi
            
        except Exception as e:
            self._log_error(f"[CryptoInsight] RSI calculation error: {e}")
            return None

    def calculate_sma(self, closes: List[float], period: int) -> Optional[float]:
        """
        Calculate Simple Moving Average.
        Returns SMA value, or None if insufficient data.
        """
        if len(closes) < period:
            return None
        
        try:
            sma = sum(closes[-period:]) / period
            self._log_info(f"[CryptoInsight] SMA-{period} calculated: {sma:.2f}")
            return sma
        except Exception as e:
            self._log_error(f"[CryptoInsight] SMA calculation error: {e}")
            return None

    def interpret_rsi(self, rsi: float) -> str:
        """Interpret RSI value for voice response."""
        if rsi < 30:
            return "oversold, possibly indicating a buying opportunity"
        elif rsi > 70:
            return "overbought, suggesting a potential correction"
        else:
            return "neutral momentum"

    def interpret_trend(self, current_price: float, sma: float, period: int) -> str:
        """Interpret price vs SMA for trend analysis."""
        if current_price > sma:
            pct_above = ((current_price - sma) / sma) * 100
            return f"above the {period}-day average by {pct_above:.1f}%, indicating bullish trend"
        else:
            pct_below = ((sma - current_price) / sma) * 100
            return f"below the {period}-day average by {pct_below:.1f}%, indicating bearish trend"

    def format_price(self, price: float) -> str:
        """Format price for voice output."""
        if price >= 1000:
            return f"${price:,.0f}"
        elif price >= 1:
            return f"${price:.2f}"
        elif price >= 0.01:
            return f"${price:.4f}"
        else:
            return f"${price:.6f}"

    def format_change(self, change: float) -> str:
        """Format 24h change for voice output."""
        direction = "up" if change > 0 else "down"
        return f"{direction} {abs(change):.1f}%"

    async def analyze_crypto(self, coin_id: str, coin_name: str) -> Optional[str]:
        """
        Perform complete crypto analysis and return formatted response.
        """
        # Fetch price data
        price_data = self.fetch_price_data(coin_id)
        if not price_data or price_data["price"] is None:
            return None
        
        current_price = price_data["price"]
        change_24h = price_data.get("change_24h", 0)
        
        # Fetch OHLC data for indicators
        closes = self.fetch_ohlc_data(coin_id, days=14)
        
        # Build response
        price_str = self.format_price(current_price)
        change_str = self.format_change(change_24h)
        
        response_parts = [
            f"{coin_name.capitalize()} is trading at {price_str}, {change_str} in 24 hours."
        ]
        
        # Add RSI if we have data
        if closes and len(closes) >= 15:
            rsi = self.calculate_rsi(closes, period=14)
            if rsi is not None:
                rsi_interpretation = self.interpret_rsi(rsi)
                response_parts.append(f"RSI is {rsi:.0f}, suggesting {rsi_interpretation}.")
        
        # Add SMA trend if we have data
        if closes and len(closes) >= 7:
            sma_7 = self.calculate_sma(closes, period=7)
            if sma_7 is not None:
                trend = self.interpret_trend(current_price, sma_7, period=7)
                response_parts.append(f"Price is {trend}.")
        
        return " ".join(response_parts)

    async def run(self):
        try:
            # Get initial request to extract crypto name
            initial_request = None
            try:
                initial_request = self.worker.transcription
            except Exception:
                pass
            
            if not initial_request:
                try:
                    initial_request = self.worker.last_transcription
                except Exception:
                    pass
            
            coin_name = "bitcoin"  # Default
            
            # Try to extract crypto from initial request
            if initial_request:
                coin_name = self._extract_crypto_name(initial_request)
                self._log_info(f"[CryptoInsight] Extracted crypto: {coin_name}")
            else:
                # Ask user which crypto they want
                await self.capability_worker.speak("Which cryptocurrency would you like to check?")
                user_input = await self.capability_worker.user_response()
                if user_input:
                    coin_name = self._extract_crypto_name(user_input)
            
            # Map to CoinGecko ID
            coin_id = self._map_to_coin_id(coin_name)
            
            # If not in our map, try searching
            if coin_id == coin_name and coin_name.lower() not in CRYPTO_MAP:
                coin_id = self.search_coin(coin_name)
            
            self._log_info(f"[CryptoInsight] Using coin_id: {coin_id}")
            
            # Speak working message
            await self.capability_worker.speak(f"Let me check {coin_name} for you.")
            
            # Perform analysis
            analysis = await self.analyze_crypto(coin_id, coin_name)
            
            if analysis:
                await self.capability_worker.speak(analysis)
            else:
                await self.capability_worker.speak(
                    f"Sorry, I couldn't find data for {coin_name}. "
                    "Make sure the name is correct, or try a popular coin like Bitcoin or Ethereum."
                )
            
        except Exception as e:
            self._log_error(f"[CryptoInsight] Unexpected error: {e}")
            if self.capability_worker:
                await self.capability_worker.speak(
                    "Sorry, something went wrong while checking crypto prices. Please try again."
                )
        finally:
            # ALWAYS resume normal flow
            if self.capability_worker:
                self.capability_worker.resume_normal_flow()
