# Market Mind Ability

A voice-first market intelligence ability for crypto, stocks, forex, and commodities. It combines TradingView scanner data, LLM intent routing, and concise spoken analysis to provide actionable market context in natural conversation.

---

## Features

- Multi-asset analysis across crypto, stocks, forex, and metals
- Market mover scanning (top gainers/losers style summaries)
- Morning brief mode using your saved watchlist + snapshot deltas
- Watchlist add/remove/show with cross-session persistence
- Risk calculator flow (position sizing and risk/reward framing)
- Multi-turn follow-up loop for conversational trading queries
- Voice-safe number formatting for better TTS readability

---

## Requirements

- Python 3.8+
- `requests`
- OpenHome runtime modules:
  - `src.agent.capability`
  - `src.agent.capability_worker`
  - `src.main`
- Optional: `num2words` (used when available for richer spoken number formatting)

---

## Installation

1. Place this folder under `community/market-mind/`.
2. Ensure these files are present:
   - `main.py`
   - `config.json`
   - `README.md`
   - `__init__.py` (empty)
3. Enable/install the ability in OpenHome and configure trigger words in the dashboard.

---

## How It Works

### Activation

The ability activates via configured hotwords (for example: `market mind`, `market update`, `check bitcoin`, `morning brief`).

### Conversation Flow

```text
User triggers Market Mind
        │
        ▼
Capture initial utterance context
        │
        ▼
LLM router classifies intent
(ANALYZE / SCAN / BRIEF / WATCHLIST / RISK / EXIT)
        │
        ▼
Resolve asset/action (alias map + LLM fallback)
        │
        ▼
Fetch TradingView scanner data
        │
        ▼
Generate concise spoken response
        │
        ▼
Offer follow-up turn or exit
        │
        ▼
resume_normal_flow()
```

### Asset Coverage

Out of the box this ability maps common aliases and symbols for:

- **Crypto:** BTC, ETH, SOL, XRP, DOGE, ADA, AVAX, LINK, DOT, LTC
- **US equities/indices:** AAPL, TSLA, NVDA, MSFT, AMZN, GOOGL, META, AMD, SPY, QQQ, SPX
- **Forex/metals/macro:** EURUSD, GBPUSD, USDJPY, Gold (XAU), Silver, DXY, US10Y

---

## APIs Used

### TradingView Scanner Endpoints (keyless in current implementation)

- `https://scanner.tradingview.com/crypto/scan`
- `https://scanner.tradingview.com/america/scan`
- `https://scanner.tradingview.com/forex/scan`

Used for:

- single-asset technical snapshots
- market scans / movers
- briefing data for watchlist assets

All requests include explicit timeouts and error handling.

### OpenHome LLM (`CapabilityWorker.text_to_text_response`)

Used for:

- request intent routing
- asset-resolution fallback
- concise spoken synthesis of technical data

---

## Persistence

This ability uses OpenHome file storage for user-level memory:

- `watchlist.json` — saved watchlist symbols
- `market_mind_snapshots.json` — prior data snapshots for change detection

---

## Suggested Trigger Words

- `market mind`
- `market update`
- `check bitcoin`
- `analyze`
- `morning brief`
- `what's moving`
- `scan for movers`
- `top gainers`
- `position size`
- `risk calculator`
- `watchlist`
- `how's gold doing`

---

## Example Conversation

> **User:** "Market mind, check bitcoin"
>
> **AI:** "Market Mind on it. Pulling up Bitcoin for you... Anything else? Ask another question or say stop."
>
> **User:** "What's moving in crypto?"
>
> **AI:** "Scanning the markets for top movers..."
>
> **User:** "Add solana to my watchlist."
>
> **AI:** "Added Solana to your watchlist."
>
> **User:** "Stop."
>
> **AI:** "Alright, signing off."

---

## Technical Notes

- LLM-first intent router with deterministic fallback logic
- TradingView scanner columns include RSI, MACD, EMA/SMA, ADX, ATR, BB, and recommendation fields
- TTS normalization converts numeric outputs into spoken-friendly phrases
- Uses `session_tasks` patterns and calls `resume_normal_flow()` on exit paths
- Logs through `editor_logging_handler` with `[MarketMind]` prefix

---

## Exit Words

Users can exit with phrases like:

> `stop`, `exit`, `quit`, `bye`, `goodbye`
