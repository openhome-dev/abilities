# Crypto Insight

Voice ability that gives live crypto and gold-related price insight: current price, 24h change, RSI, and short-term trend (vs 7-day SMA). Supports any asset by name or symbol (e.g. Bitcoin, Ethereum, gold, XAUUSD) with no hardcoded IDs.

---

## How It Works

1. **Trigger** — You say a phrase that matches the ability’s trigger list (e.g. “Ethereum price”, “Gold price”, “Crypto insight”). The ability captures your utterance as the initial request.

2. **Asset from your phrase** — If what you said looks like an asset request, the ability normalizes it with the platform LLM (e.g. “what’s the price on gold” → “gold”, “XAU USD” → “gold”) and looks up the asset in CoinLore. If found, it skips the follow-up question.

3. **Otherwise ask** — If the trigger didn’t name an asset (e.g. “Crypto insight”), it asks: “Which asset would you like to check? Say a cryptocurrency, gold, or symbol.” It then normalizes your reply and resolves it to a CoinLore asset.

4. **Resolve** — The ability searches CoinLore’s ticker list by name, symbol, or nameid. “Gold” is matched to gold-backed tokens (e.g. Tether Gold, PAX Gold) on CoinLore.

5. **Fetch & analyze** — It fetches current price and 24h change from CoinLore, then historical price points for RSI (14-period) and 7-day SMA. It builds a short spoken summary: price, change, RSI interpretation, and trend vs the 7-day average.

6. **Speak** — It says something like: “Tether Gold is trading at $4,953, down 1.6% in 24 hours. RSI is 58, suggesting neutral momentum. Price is below the 7-day average by 0.2%, indicating bearish trend.”

Trigger-echo is ignored (if the first “response” is the same as the trigger phrase, it reprompts instead of using it as the asset).

---

## APIs Used

### CoinLore (no API key)

- **Base:** `https://api.coinlore.net`
- **Tickers list:** `GET /api/tickers/` — Paginated list of all coins; used to resolve a search term (name/symbol) to a CoinLore `id`. No hardcoded coin IDs; resolution is dynamic.
- **Ticker:** `GET /api/ticker/?id={id}` — Current price and 24h percent change for one coin.
- **Markets / chart data:** `GET /api/coin/markets/?id={id}` — Historical price points (e.g. `price_usd`, `time`) used to compute RSI and 7-day SMA.

All `requests` calls use a 10-second timeout. CoinLore is free and does not require an API key; rate limits (429) are handled gracefully.

### OpenHome platform LLM (Text-to-Text)

- **Usage:** Normalizing freeform user input to a single asset search term (e.g. “gold price”, “XAUUSD”, “how is XRP doing” → “gold”, “gold”, “xrp”).
- **How:** The ability calls `capability_worker.text_to_text_response(prompt)` with a short prompt asking for one lowercase asset word. The LLM is provided by the OpenHome platform; you configure the provider (e.g. API keys) in **Dashboard → Profile → Settings → API Key Settings**. This ability does not store or read any API keys itself.

---

## Trigger Words

Suggested phrases (defined in `main.py` as `MATCHING_HOTWORDS`; also configurable in the OpenHome dashboard when installing the ability):

- Crypto insight, crypto ai, check crypto  
- What’s bitcoin doing, crypto price, check ethereum  
- Bitcoin price, ethereum price  
- What’s the price on gold, price of gold, gold price  
- Just tell me the price, tell me the price  

You can say the asset in the same phrase (e.g. “Ethereum price”, “Gold price”) to get an immediate answer without a follow-up question.

---

## Setup

- No API keys are required for CoinLore.
- For best results (arbitrary phrases like “gold”, “XAUUSD”), set up OpenAI in OpenHome (Dashboard → Profile → Settings → API Key Settings). If the LLM is unavailable, the ability falls back to simple word extraction from your reply.

---

## Files

- `main.py` — Ability logic (trigger handling, LLM normalization, CoinLore resolution, price/chart fetch, RSI/SMA, speech). Defines `unique_name` and `MATCHING_HOTWORDS` for the platform.
- `__init__.py` — Empty; marks the ability package.
