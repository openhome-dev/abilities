import json
import os
import urllib.request
import urllib.parse
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


# --- API Helpers ---

POLYMARKET_API = "https://gamma-api.polymarket.com"
COINGECKO_API = "https://api.coingecko.com/api/v3"

HTTP_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "OpenHome-MarketIntelligence/1.0",
}

# Categories for filtering and routing
CATEGORY_KEYWORDS = {
    "geopolitics": ["iran", "strike", "ukraine", "russia", "china", "nato", "war", "sanctions", "ceasefire", "military"],
    "crypto": ["bitcoin", "btc", "eth", "ethereum", "crypto", "solana", "sol", "stablecoin", "defi", "nft"],
    "macro": ["fed", "rate", "recession", "gdp", "inflation", "cpi", "interest", "treasury", "debt"],
    "technology": ["ai", "openai", "google", "nvidia", "tesla", "apple", "microsoft", "acquisition", "ipo"],
    "politics": ["president", "election", "congress", "senate", "trump", "democrat", "republican", "vote"],
    "trade": ["tariff", "trade", "sanctions", "import", "export"],
}

# Skip noise categories
SKIP_KEYWORDS = [
    "nba", "nfl", "premier league", "champions league", "super bowl",
    "bachelor", "grammy", "oscar", "survivor", "dating",
]

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "that's all"}


def fetch_json(url):
    """Fetch JSON from a URL with proper headers."""
    try:
        req = urllib.request.Request(url, headers=HTTP_HEADERS)
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def get_polymarket_events(limit=30, offset=0):
    """Fetch active Polymarket events sorted by volume."""
    url = f"{POLYMARKET_API}/events?limit={limit}&active=true&closed=false&order=volume&ascending=false&offset={offset}"
    return fetch_json(url) or []


def categorize_market(question, title=""):
    """Assign a category to a market based on keywords."""
    combined = (title + " " + question).lower()

    if any(kw in combined for kw in SKIP_KEYWORDS):
        return None

    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in combined for kw in keywords):
            return category

    return "other"


def parse_market(m, event_title=""):
    """Extract clean market data from a raw Polymarket market object."""
    if m.get("closed"):
        return None

    question = m.get("question", event_title)
    category = categorize_market(question, event_title)
    if category is None:
        return None

    outcomes = m.get("outcomes", "[]")
    prices = m.get("outcomePrices", "[]")
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except (json.JSONDecodeError, TypeError):
            return None
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except (json.JSONDecodeError, TypeError):
            return None

    if not outcomes or not prices or len(outcomes) != len(prices):
        return None

    yes_pct = None
    for i, outcome in enumerate(outcomes):
        if outcome.lower() == "yes" and i < len(prices):
            try:
                yes_pct = round(float(prices[i]) * 100, 1)
            except (ValueError, TypeError):
                pass
            break

    volume = 0
    try:
        volume = float(m.get("volumeNum", 0) or m.get("volume", 0) or 0)
    except (ValueError, TypeError):
        pass

    if volume < 50000:
        return None

    return {
        "question": question,
        "category": category,
        "yes_pct": yes_pct,
        "volume": round(volume),
        "week_change": m.get("oneWeekPriceChange"),
        "day_change": m.get("oneDayPriceChange"),
    }


def fetch_markets():
    """Fetch and parse all fund-relevant Polymarket markets."""
    markets = []
    seen = set()

    for offset in [0, 30, 60]:
        events = get_polymarket_events(limit=30, offset=offset)
        if not isinstance(events, list):
            continue

        for event in events:
            for m in event.get("markets", []):
                parsed = parse_market(m, event.get("title", ""))
                if parsed and parsed["question"] not in seen:
                    seen.add(parsed["question"])
                    markets.append(parsed)

    markets.sort(key=lambda x: x.get("volume", 0), reverse=True)
    return markets


def get_weekly_movers(markets, threshold=5.0):
    """Return markets with >threshold% weekly probability shift."""
    movers = [
        m for m in markets
        if m.get("week_change") and abs(m["week_change"] * 100) >= threshold
    ]
    movers.sort(key=lambda x: abs(x.get("week_change", 0)), reverse=True)
    return movers[:10]


def get_markets_by_category(markets, category):
    """Filter markets to a specific category."""
    return [m for m in markets if m.get("category") == category]


def get_crypto_prices():
    """Fetch top crypto prices from CoinGecko."""
    url = f"{COINGECKO_API}/simple/price?ids=bitcoin,ethereum,solana,cardano&vs_currencies=usd&include_24hr_change=true"
    data = fetch_json(url)
    if not data:
        return None

    prices = {}
    name_map = {"bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL", "cardano": "ADA"}
    for coin_id, symbol in name_map.items():
        if coin_id in data:
            prices[symbol] = {
                "price": data[coin_id].get("usd"),
                "change_24h": data[coin_id].get("usd_24h_change"),
            }
    return prices


def format_markets_for_speech(markets, limit=5):
    """Format a list of markets into a speech-friendly string."""
    lines = []
    for m in markets[:limit]:
        prob = f"{m['yes_pct']:.0f}%" if m.get("yes_pct") is not None else "unknown"
        chg = ""
        if m.get("week_change"):
            direction = "up" if m["week_change"] > 0 else "down"
            chg = f", {direction} {abs(m['week_change'] * 100):.0f} points this week"
        lines.append(f"{prob}{chg} for {m['question']}")
    return ". ".join(lines)


def format_crypto_for_speech(prices):
    """Format crypto prices for speech."""
    if not prices:
        return "I couldn't fetch crypto prices right now."
    parts = []
    for symbol, data in prices.items():
        price = data.get("price")
        change = data.get("change_24h")
        if price:
            price_str = f"${price:,.0f}" if price > 100 else f"${price:.2f}"
            chg_str = ""
            if change is not None:
                direction = "up" if change > 0 else "down"
                chg_str = f", {direction} {abs(change):.1f}% today"
            parts.append(f"{symbol} at {price_str}{chg_str}")
    return ". ".join(parts)


def format_movers_for_speech(movers):
    """Format weekly movers for speech."""
    if not movers:
        return "No major probability shifts this week."
    parts = []
    for m in movers[:5]:
        direction = "up" if m["week_change"] > 0 else "down"
        points = abs(m["week_change"] * 100)
        prob = f"{m['yes_pct']:.0f}%" if m.get("yes_pct") is not None else "unknown"
        parts.append(f"{m['question'][:60]}, {direction} {points:.0f} points to {prob}")
    return ". ".join(parts)


# --- Intent Classification ---

INTENT_PROMPT = """Classify this user query about markets/predictions into ONE category.
Return ONLY a JSON object: {"intent": "string", "topic": "string"}

Intents:
- "geopolitics" — wars, strikes, military, sanctions, ceasefire, Iran, Ukraine, China
- "crypto" — Bitcoin, Ethereum, crypto prices, DeFi, stablecoins
- "macro" — Fed, interest rates, recession, inflation, GDP, economy
- "technology" — AI companies, IPOs, acquisitions, tech stocks
- "politics" — elections, nominations, Congress, policy
- "trade" — tariffs, trade deals, imports/exports
- "movers" — biggest changes, what moved, weekly shifts, surprises
- "overview" — general market summary, what's happening, brief me
- "unknown" — can't determine

"topic" is a short keyword for the specific subject (e.g. "iran", "bitcoin", "fed rates").

User query: {query}"""


def classify_intent(capability_worker, query):
    """Use LLM to classify user intent."""
    prompt = INTENT_PROMPT.format(query=query)
    raw = capability_worker.text_to_text_response(prompt)
    clean = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(clean)
    except (json.JSONDecodeError, TypeError):
        return {"intent": "overview", "topic": ""}


# --- Response Generation ---

SUMMARIZE_PROMPT = """You are a voice market briefing assistant. Convert this market data into
a natural spoken response. Rules:
- Maximum 3-4 sentences
- Use natural language, not bullet points
- Say percentages as words ("sixty percent", not "60%")
- Round large numbers ("about 30 million dollars", not "$29,525,610")
- Focus on the most significant signals
- If there are notable weekly moves, highlight them
- Sound like a knowledgeable analyst briefing someone verbally

User asked: {query}
Category: {category}
Market data:
{data}"""


def generate_spoken_response(capability_worker, query, category, data_str, history):
    """Generate a natural spoken response using LLM."""
    prompt = SUMMARIZE_PROMPT.format(query=query, category=category, data=data_str)
    return capability_worker.text_to_text_response(prompt, history=history)


# --- Main Ability ---

class MarketIntelligenceCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

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

    async def run(self):
        await self.capability_worker.speak("Market intelligence ready. What would you like to know?")

        # Pre-fetch markets once for the session
        await self.capability_worker.speak("Loading latest market data.")
        markets = fetch_markets()
        crypto_prices = get_crypto_prices()
        history = []

        if not markets:
            await self.capability_worker.speak(
                "I'm having trouble reaching market data right now. Try again in a moment."
            )
            self.capability_worker.resume_normal_flow()
            return

        while True:
            user_input = await self.capability_worker.user_response()

            if not user_input:
                continue

            if any(w in user_input.lower().strip() for w in EXIT_WORDS):
                await self.capability_worker.speak("Goodbye!")
                break

            # Classify intent
            intent_result = classify_intent(self.capability_worker, user_input)
            intent = intent_result.get("intent", "overview")
            topic = intent_result.get("topic", "")

            # Build data string based on intent
            data_str = ""

            if intent == "movers":
                movers = get_weekly_movers(markets)
                data_str = format_movers_for_speech(movers)

            elif intent == "crypto":
                # Combine crypto prices + crypto prediction markets
                crypto_data = format_crypto_for_speech(crypto_prices)
                crypto_markets = get_markets_by_category(markets, "crypto")
                market_data = format_markets_for_speech(crypto_markets, limit=3)
                data_str = f"Prices: {crypto_data}\nPrediction markets: {market_data}"

            elif intent == "overview":
                # Top signals across categories
                priority_cats = ["geopolitics", "macro", "crypto", "technology"]
                parts = []
                for cat in priority_cats:
                    cat_markets = get_markets_by_category(markets, cat)[:2]
                    if cat_markets:
                        parts.append(f"{cat.title()}: {format_markets_for_speech(cat_markets, limit=2)}")
                movers = get_weekly_movers(markets, threshold=10.0)
                if movers:
                    parts.append(f"Biggest movers: {format_movers_for_speech(movers[:3])}")
                data_str = "\n".join(parts)

            elif intent in CATEGORY_KEYWORDS:
                # Specific category query
                cat_markets = get_markets_by_category(markets, intent)
                if topic:
                    # Filter further by topic keyword
                    topic_filtered = [
                        m for m in cat_markets
                        if topic.lower() in m.get("question", "").lower()
                    ]
                    if topic_filtered:
                        cat_markets = topic_filtered
                data_str = format_markets_for_speech(cat_markets, limit=5)
                if not data_str:
                    data_str = f"No active prediction markets found for {topic or intent}."

            else:
                # Fallback: search all markets for the topic
                if topic:
                    matching = [
                        m for m in markets
                        if topic.lower() in m.get("question", "").lower()
                    ]
                    data_str = format_markets_for_speech(matching, limit=5) if matching else f"No markets found matching '{topic}'."
                else:
                    data_str = "I'm not sure what you're asking about. Try asking about geopolitics, crypto, the economy, or biggest movers."

            # Generate spoken response via LLM
            history.append({"role": "user", "content": user_input})

            response = generate_spoken_response(
                self.capability_worker,
                user_input,
                intent,
                data_str,
                history,
            )

            if response:
                history.append({"role": "assistant", "content": response})
                await self.capability_worker.speak(response)
            else:
                await self.capability_worker.speak("I couldn't generate a response. Try rephrasing.")

        self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())
