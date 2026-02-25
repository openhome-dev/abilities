# Market Intelligence

A voice-first market intelligence assistant powered by **Polymarket** prediction markets and **CoinGecko** crypto data.

## What It Does

Ask natural questions about prediction markets, geopolitical events, crypto prices, or macro trends — and get spoken, data-backed answers.

## Example Conversations

```
User: "What's the market saying about Iran?"
AI:   "US airstrike on Iran by March 31st: 60% chance of Yes. 
       US airstrike by February 28th: 26% chance..."

User: "How's Bitcoin doing?"
AI:   "Bitcoin is trading at $67,490.00, up 1.2% in the last 24 hours. 
       Market cap: $1,337 billion."

User: "Any predictions on AI?"
AI:   "OpenAI valued above $500B by 2026: 72% chance of Yes..."
```

## Data Sources

- **[Polymarket Gamma API](https://gamma-api.polymarket.com)** — Real-time prediction market data (no auth required)
- **[CoinGecko API](https://www.coingecko.com/en/api)** — Crypto prices and market data (free tier, no auth required)

## Categories

The ability automatically classifies queries into:
- **Geopolitics** — Conflicts, sanctions, diplomacy
- **Crypto** — Prices, exchanges, DeFi
- **Macro** — Fed, inflation, rates, trade
- **Technology** — AI, semiconductors, IPOs
- **Corporate** — Earnings, M&A, regulation

## Requirements

- `requests` (standard in OpenHome runtime)
- No API keys needed — both Polymarket Gamma and CoinGecko free tier work without authentication

## Author

[@bishop-commits](https://github.com/bishop-commits)
