# Market Intelligence

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@bishop--commits-lightgrey?style=flat-square)

## What It Does

A voice-first prediction market intelligence assistant. Ask about geopolitics, crypto, the economy, or technology — and get real-time probability data from Polymarket plus crypto prices from CoinGecko, summarized as natural spoken briefings.

This ability turns [Polymarket](https://polymarket.com)'s 500+ active prediction markets into a voice-queryable intelligence feed. Instead of reading dashboards, just ask: *"What's the market saying about Iran?"*

## Suggested Trigger Words

- "market intelligence"
- "what are the markets saying"
- "market briefing"
- "prediction markets"
- "what's the market outlook"

## Setup

**No API keys required.** This ability uses:
- [Polymarket Gamma API](https://docs.polymarket.com) — free, public, no auth
- [CoinGecko API](https://www.coingecko.com/en/api) — free tier, no auth

Just install the ability and set your trigger words. It works out of the box.

## How It Works

1. On activation, fetches the latest prediction market data from Polymarket (top 90 events by volume)
2. Categorizes markets into: Geopolitics, Crypto, Macro, Technology, Politics, Trade
3. Filters out noise (sports, entertainment) — focuses on fund-relevant signals
4. Uses LLM intent classification to understand what you're asking about
5. Formats relevant market data and generates a natural spoken briefing
6. Maintains conversation history for contextual follow-up questions

### Supported Query Types

| Query Type | Example | What You Get |
|-----------|---------|-------------|
| **Category** | "What about geopolitics?" | Top markets + probabilities for that category |
| **Topic** | "What's happening with Iran?" | Filtered markets matching the topic |
| **Crypto** | "How's crypto doing?" | Prices (BTC, ETH, SOL, ADA) + crypto prediction markets |
| **Movers** | "Any big shifts this week?" | Markets with >5% weekly probability change |
| **Overview** | "Brief me" | Top signals across all categories + biggest movers |

## Example Conversation

> **User:** "market intelligence"
> **AI:** "Market intelligence ready. What would you like to know?"

> **User:** "What's happening with Iran?"
> **AI:** "The market gives a sixty percent chance of US strikes on Iran by March 31st, up 27 points this week. The February 28th deadline is at 26 percent with about 30 million dollars in volume. The March 15th contract is at a coin flip, also surging 27 points."

> **User:** "How about crypto?"
> **AI:** "Bitcoin is at sixty-seven thousand, roughly flat today. Ethereum is around twenty-seven hundred. On the prediction side, there's only a 16 percent chance MicroStrategy sells any bitcoin this year, and the Kraken IPO by end of 2026 is at 80 percent."

> **User:** "Any big movers this week?"
> **AI:** "The biggest shift is Viking Therapeutics acquisition, jumping 45 points to 63 percent — someone's betting heavily on a buyout. On the downside, Ubisoft acquisition dropped 21 points, and Solana crash probability collapsed from about 30 to 9 percent."

> **User:** "Give me an overview"
> **AI:** "Across the board: geopolitics is dominated by Iran strike probability surging to 60 percent by March. The Fed chair nomination is nearly settled — Kevin Warsh at 94 percent. Crypto is rangebound. The biggest weekly movers are all in the Iran cluster and M&A space."

> **User:** "Stop"
> **AI:** "Goodbye!"

## Data Sources

- **[Polymarket](https://polymarket.com)** — World's largest prediction market. Binary event contracts priced by market participants. Prices = implied probabilities.
- **[CoinGecko](https://www.coingecko.com)** — Crypto price aggregator. Free API, no key needed.

## Categories Tracked

| Category | Examples |
|----------|---------|
| Geopolitics | Iran strikes, Ukraine ceasefire, China tensions |
| Crypto | BTC/ETH price targets, exchange IPOs, protocol events |
| Macro | Fed rate decisions, recession probability, inflation |
| Technology | AI company acquisitions, tech IPOs, model competitions |
| Politics | Elections, nominations, congressional votes |
| Trade | Tariffs, trade deals, sanctions |

## Technical Details

- **APIs:** Polymarket Gamma (REST, no auth) + CoinGecko (REST, no auth)
- **Pattern:** Conversation loop with LLM intent classification
- **Data refresh:** Markets fetched once per session activation (typically 500+ markets)
- **Filtering:** Volume floor of $50K removes illiquid/noise markets
- **Response style:** Natural spoken language, 3-4 sentences max per response

## Limitations

- Polymarket data is read-only intelligence — this ability does not place trades
- Market data is fetched at session start; for real-time updates, re-trigger the ability
- CoinGecko free tier has rate limits (~10-30 calls/minute) — sufficient for voice use
- Prediction market probabilities reflect market consensus, not guaranteed outcomes

## License

MIT
