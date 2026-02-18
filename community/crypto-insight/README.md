# Crypto Insight

Voice-first market ability for live crypto and gold-related requests. It answers natural questions like:

- "What's the price on Bitcoin?"
- "How is XRP doing?"
- "Is gold trending up?"
- "Give me ETH RSI."

It fetches live market data and responds in short spoken language.

---

## Architecture (Voice -> LLM -> API -> Voice)

1. **Trigger gate (platform)**  
   OpenHome routes to this ability when the utterance matches configured hotwords.

2. **Context ingestion**  
   The ability captures the triggering utterance (`transcription` / recent user history fallback).

3. **LLM route/classify**  
   `text_to_text_response()` returns strict JSON:
   - `should_handle`
   - `asset`
   - `intent`

4. **Deterministic fallbacks**  
   If routing or extraction is weak, it falls back to:
   - alias mapping (`btc -> bitcoin`, `xauusd -> gold`, etc.)
   - heuristic market-term detection
   - one-word LLM asset normalization

5. **Resolve + fetch**  
   It resolves the asset dynamically via CoinLore tickers (no hardcoded IDs), then fetches:
   - current price / 24h change
   - chart points for RSI and SMA trend

6. **Voice formatting**  
   It rewrites the final answer into 1-2 conversational spoken sentences without changing numbers.

7. **No dead ends**  
   If an asset is unresolved, it suggests alternatives and asks one retry follow-up.

---

## APIs Used

### CoinLore (no API key)

- Base: `https://api.coinlore.net`
- `GET /api/tickers/` -> dynamic asset resolution by name/symbol/nameid
- `GET /api/ticker/?id={id}` -> live price + 24h change
- `GET /api/coin/markets/?id={id}` -> time series used for RSI/SMA

All requests include `timeout=10`.

### OpenHome LLM (`CapabilityWorker.text_to_text_response`)

Used for:
- request routing/classification
- asset normalization
- voice response polishing

Provider keys are managed in OpenHome dashboard settings. This ability does not store keys.

---

## Trigger Words

Triggers are only the handoff gate. Natural-language understanding is done inside the ability.
The active trigger list is loaded from `config.json` at runtime (with a code fallback).

Representative trigger phrases in `MATCHING_HOTWORDS` include:
- `crypto insight`, `crypto ai`, `check crypto`
- `bitcoin price`, `ethereum price`, `gold price`
- `quote`, `ticker`, `rsi`, `sma`, `trend`

If users say only a wake phrase, the ability asks a short follow-up: "Which asset should I check?"

---

## Behavior Guarantees

- Always speaks an outcome (answer, clarification, or fallback).
- Avoids silent exits.
- Calls `resume_normal_flow()` on exit.
- Uses `session_tasks` for async delays.

---

## Files

- `main.py` - full ability logic (routing, extraction, resolution, analysis, speech)
- `config.json` - canonical OpenHome registration fields (`unique_name`, `matching_hotwords`)
- `__init__.py` - empty package marker
