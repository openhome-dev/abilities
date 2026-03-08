# crypto-insight Ability

A voice-driven market data ability that delivers live crypto and gold price updates, RSI analysis, and trend insights using the [CoinLore](https://www.coinlore.com/cryptocurrency-data-api) public API.

---

## Features

- Live price quotes for any cryptocurrency or gold (XAU/USD)
- 24-hour percentage change
- RSI (14-period) with overbought/oversold interpretation
- 7-day SMA trend direction
- Voice-optimized output formatting via LLM
- Multi-turn conversation loop with follow-up support
- Fuzzy asset resolution — handles aliases like `btc`, `eth`, `xau`, `doge`

---

## Requirements

- Python 3.8+
- `requests` library
- Access to the agent framework (`src.agent`, `src.main`) with:
  - `Matchingability`
  - `abilityWorker`
  - `AgentWorker`

Install dependencies:

```bash
pip install requests
```

---

## Installation

1. Copy the ability folder into your agent's abilities directory.

2. Create a `config.json` file alongside the main module:

```json
{
  "unique_name": "crypto-insight",
  "matching_hotwords": [
    "crypto insight",
    "crypto ai",
    "check crypto",
    "crypto price",
    "bitcoin price",
    "ethereum price"
  ]
}
```

3. Register the ability with your agent by calling:

```python
CryptoAiability.register_ability()
```

---

## How It Works

### Activation

The ability activates when the agent detects a hotword match (e.g. *"crypto price"*, *"check crypto"*, *"bitcoin price"*). It can also be triggered directly via voice with phrases like **"crypto insight"** or **"crypto AI"**.

### Conversation Flow

```
User speaks trigger phrase
        │
        ▼
ability resolves asset from speech
(alias lookup → LLM normalization → CoinLore search)
        │
        ▼
Fetches live price + market data from CoinLore
        │
        ▼
Calculates RSI and SMA if enough data is available
        │
        ▼
LLM rewrites result for natural spoken delivery
        │
        ▼
Asks if user wants another asset (up to 3 turns)
```

### Asset Resolution

Assets are resolved in this priority order:

1. **Alias table** — common names/symbols like `btc → bitcoin`, `xau → gold`
2. **LLM normalization** — converts freeform speech to a searchable term
3. **CoinLore search** — scans up to 2,500 coins across 25 pages

If resolution fails, the ability suggests similar asset names and prompts the user to retry.

---

## API Usage

This ability uses the **CoinLore public API** — no API key required.

| Endpoint | Purpose |
|---|---|
| `/api/tickers/` | Asset search and resolution |
| `/api/ticker/` | Live price and 24h change |
| `/api/coin/markets/` | Market price points for RSI/SMA |

Rate limits are handled gracefully — the ability will inform the user if CoinLore returns a `429` response.

---

## Configuration

Key constants you may want to adjust in the source file:

| Constant | Default | Description |
|---|---|---|
| `COINLORE_SEARCH_PAGES` | `25` | Pages to scan when resolving an asset |
| `COINLORE_PAGE_SIZE` | `100` | Results per page |
| `COINLORE_SUGGESTION_PAGES` | `8` | Pages to scan when generating suggestions |

---

## Extending

**Add a new asset alias:**

```python
ASSET_ALIASES["pepe"] = "pepe"
ASSET_ALIASES["wif"] = "dogwifhat"
```

**Add a new hotword trigger:**

Add the phrase to both `MATCHING_HOTWORDS` in the source and `matching_hotwords` in `config.json`.

**Adjust RSI/SMA periods:**

The `analyze_crypto()` method calls `calculate_rsi(closes, period=14)` and `calculate_sma(closes, period=7)`. Pass different values to change the analysis window.

---

## Exit Words

Users can end the session at any time by saying:

> *stop, exit, quit, done, cancel, bye, goodbye, leave, nothing*

---

## Logging

The ability logs to `worker.editor_logging_handler` with the prefix `[CryptoInsight]`. Check these logs to debug asset resolution, API calls, and LLM routing decisions.

---

## License

Refer to your agent framework's license. CoinLore API usage is subject to their [terms of service](https://www.coinlore.com/cryptocurrency-data-api).
