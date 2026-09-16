# OpenHome Bankr

Buy and sell any token on Base by voice through a [Bankr](https://bankr.bot) wallet. MIT licensed.

> **User:** "Buy two dollars of Bitcoin."
> **Speaker:** "Two dollars gets you about zero point zero zero zero zero two six Bitcoin at seventy-five thousand six hundred dollars. To confirm, say the amount."
> **User:** "Two dollars."
> **Speaker:** "Done. You bought about zero point zero zero zero zero two six Bitcoin for two dollars."

## What it does

| Say | Result |
|---|---|
| "what's the price of Aerodrome" / "what's Bitcoin at" | Price and 24h change |
| "how's my portfolio" / "check my crypto" | Base balances, top five by value, rounded to the dollar |
| "buy ten dollars of Degen" | Resolve token → quote → read-back naming the token → you repeat the amount → swap |
| "sell ten dollars of Ethereum" / "sell all my Degen" | Same, in reverse; sells resolve against what you hold |
| "lock my wallet" (optionally "for two hours") | No trades for 24h or the stated time. No voice unlock. |

Amounts are in US dollars. Bitcoin (cbBTC), Ethereum and dollars (USDC) resolve instantly. Any other token is looked up by name on Base (DexScreener, CoinGecko fallback) and must have ≥ $1M market cap and ≥ $250k liquidity, or it is refused. If two tokens match, it asks which. Not reachable by voice: other networks, contract addresses, transfers, leverage, settings changes.

## Trigger words

Any sentence containing: `dollar`, `bucks of`, `buy some`, `buy me`, `sell some`, `sell all`, `sell my`, `price of`, `the price`, `worth right now`, `trading at`, `token`, `coin`, `crypto`, `my portfolio`, `my wallet`, `bitcoin`, `ethereum`, `lock my wallet`.

## Setup

### 1. Bankr

1. Create an account at [bankr.bot](https://bankr.bot). Add an email backup login (recovery is tied to your login method).
2. **Security → enable passkey MFA.** After this, no API key can change a security setting.
3. **Security → limits.** Per-transaction and daily USD limits you are fine losing (e.g. $50 / $150; defaults are $500 / $500). Turn on price-impact protection at **5%** (Bankr's reference prices run a few percent stale on some tokens; 3% rejects fair sells). Turn off arbitrary contract calls.
4. Fund the wallet on **Base**: USDC to trade with, plus a little ETH for gas.
5. **[bankr.bot/api-keys](https://bankr.bot/api-keys)** → create two keys:

| Key name | Wallet API | Agent API | Token Launch | LLM Gateway | Read Only |
|---|---|---|---|---|---|
| `voice-read` | on | off | off | off | **on** |
| `voice-trade` | on | off | off | off | **off** |

Each key is shown once. Copy both.

### 2. OpenHome

Dashboard → **Settings → API Keys → Third-party keys**. Add:

| Name (exact) | Value | Provider URL |
|---|---|---|
| `bankr_read_key` | the `voice-read` key | `https://bankr.bot/api-keys` |
| `bankr_trade_key` | the `voice-trade` key (optional; omit for read-only) | `https://bankr.bot/api-keys` |

Install the ability, then say "how's my portfolio".

## Built-in limits

Enforced in `main.py` before Bankr sees a request (constants at the top of the file):

- $25 per trade, $100 per rolling 24 hours
- Confirmation is the user repeating the dollar amount; "yes" is not accepted; a mismatch cancels
- Quotes older than 45 s are re-fetched and re-confirmed
- Effective price (dollars in ÷ coins out) is checked against an independent price; more than 3% off (8% for non-menu tokens) → refused
- Non-menu tokens: ≥ $1M market cap and ≥ $250k liquidity, else refused; ambiguous names are asked about, never guessed
- Two mismatches in 10 minutes → trading paused 15 minutes
- Every exit says whether money moved: "Done." / "Sold." / "Nothing was traded." / "I'm not sure it went through" (Bankr timeout)

For a bigger trade, raise the limit on bankr.bot with a timer; it reverts on its own.

## Security model

Bankr wallets are custodial (Privy smart wallets managed by Bankr; keys are not exportable). Fund it like a hot wallet.

Anyone who can talk to the speaker, or who obtains the keys from OpenHome, can at most swap between tokens inside the wallet, up to the limits set on bankr.bot. They cannot raise limits, add recipients, withdraw to a new address, launch tokens, trade with leverage, or use the Bankr agent. Those settings are passkey-locked and the trade key does not have those permissions.

Kill switch: **Pause** on bankr.bot → Security. Voice "lock" is a convenience timer, not a security boundary.

## How it works

1. `wait_for_complete_transcription()` captures the trigger sentence. The OpenHome LLM extracts `{action, asset, usd}` as JSON against a fixed schema. The LLM only extracts; code decides everything else.
2. Token resolution: BTC/ETH/USD locally. Otherwise DexScreener search filtered to Base, scored by name match then liquidity; CoinGecko as fallback; Bankr's Agent API as a last fallback if the read key has it (needs Bankr Club). Sells match against holdings only.
3. Reads: Bankr `GET /wallet/portfolio` (read key), CoinGecko / DexScreener for prices.
4. Trade: Bankr `POST /wallet/swap-quote` → price check → read-back → amount confirmation → `POST /wallet/swap` with `minBuyAmount`, `quoteId`, one-time `idempotencyKey` (trade key).
5. `success: false` from Bankr is spoken as "didn't go through", never "done".

## External calls

- `api.bankr.bot` — `/wallet/portfolio`, `/wallet/swap-quote`, `/wallet/swap`. Sends: API key, token pair, amount, idempotency key.
- `api.dexscreener.com` — public token search, no key. Sends only the spoken token name.
- `api.coingecko.com` — public prices and search, no key. Sends only the spoken token name.
- `api.bankr.bot/agent/prompt` — optional fallback lookup with the read-only key; skipped when the account lacks Bankr Club.

## Data stored

Two non-sensitive values in OpenHome's key-value store: the lock timer and a rolling log of voice-trade dollar amounts (for the daily cap). API keys are read at runtime via `get_api_keys()` and never written or logged.

## Known limitations

- Base only.
- No transfers.
- Token lookup takes 3–8 s; BTC/ETH/USD are instant.
- Bankr has no testnet. Test with a few dollars.
- Bankr's `buyTokenPriceUsd` / `sellTokenPriceUsd` quote fields have been observed 3–14% stale (cbBTC, AERO). This ability ignores them and uses the effective execution price. Bankr's own price-impact protection does use them, so a fair sell can be rejected with a 403 at a tight setting; the ability reports "Nothing was traded." Set protection to 5%.
