# OpenHome Bankr

Buy and sell Bitcoin and Ethereum by voice through a [Bankr](https://bankr.bot) wallet. MIT licensed.

> **User:** "Buy two dollars of Bitcoin."
> **Speaker:** "Two dollars gets you about zero point zero zero zero zero two six Bitcoin at seventy-five thousand six hundred dollars. To confirm, say the amount."
> **User:** "Two dollars."
> **Speaker:** "Done. You bought about zero point zero zero zero zero two six Bitcoin for two dollars."

## What it does

| Say | Result |
|---|---|
| "what's Bitcoin at" / "Ethereum price" | Price and 24h change |
| "how's my portfolio" / "check my crypto" | Base balances, rounded to the dollar |
| "buy twenty dollars of Bitcoin" | Quote → read-back → you repeat the amount → swap |
| "sell ten dollars of Ethereum" / "sell all my Bitcoin" | Same, in reverse |
| "lock my wallet" (optionally "for two hours") | No trades for 24h or the stated time. No voice unlock. |

Amounts are in US dollars. Assets: Bitcoin (cbBTC), Ethereum (ETH), dollars (USDC), all on Base. Nothing else is reachable by voice: no other tokens, no transfers, no addresses, no leverage, no settings changes.

## Trigger words

Any sentence containing: `bitcoin`, `ethereum`, `my portfolio`, `my crypto`, `my wallet`, `buy some`, `sell some`, `sell all`, `dollars of`, `crypto price`, `lock my wallet`.

## Setup

### 1. Bankr

1. Create an account at [bankr.bot](https://bankr.bot). Add an email backup login (recovery is tied to your login method).
2. **Security → enable passkey MFA.** After this, no API key can change a security setting.
3. **Security → limits.** Per-transaction and daily USD limits you are fine losing (e.g. $50 / $150; defaults are $500 / $500). Turn on price-impact protection (3%). Turn off arbitrary contract calls.
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
- Effective price (dollars in ÷ coins out) is checked against CoinGecko; more than 3% off → refused
- Two mismatches in 10 minutes → trading paused 15 minutes
- Every exit says whether money moved: "Done." / "Sold." / "Nothing was traded." / "I'm not sure it went through" (Bankr timeout)

For a bigger trade, raise the limit on bankr.bot with a timer; it reverts on its own.

## Security model

Bankr wallets are custodial (Privy smart wallets managed by Bankr; keys are not exportable). Fund it like a hot wallet.

Anyone who can talk to the speaker, or who obtains the keys from OpenHome, can at most swap between USD, BTC and ETH inside the wallet, up to the limits set on bankr.bot. They cannot raise limits, add recipients, withdraw to a new address, launch tokens, trade with leverage, or use the Bankr agent. Those settings are passkey-locked and the trade key does not have those permissions.

Kill switch: **Pause** on bankr.bot → Security. Voice "lock" is a convenience timer, not a security boundary.

## How it works

1. `wait_for_complete_transcription()` captures the trigger sentence. The OpenHome LLM extracts `{action, asset, usd}` as JSON against a fixed schema. The LLM only extracts; code decides everything else.
2. Reads: Bankr `GET /wallet/portfolio` (read key), CoinGecko for prices.
3. Trade: Bankr `POST /wallet/swap-quote` → price check → read-back → amount confirmation → `POST /wallet/swap` with `minBuyAmount`, `quoteId`, one-time `idempotencyKey` (trade key).
4. `success: false` from Bankr is spoken as "didn't go through", never "done".

## External calls

- `api.bankr.bot` — `/wallet/portfolio`, `/wallet/swap-quote`, `/wallet/swap`. Sends: API key, token pair, amount, idempotency key.
- `api.coingecko.com` — public price endpoint, no key, nothing about the user.

## Data stored

Two non-sensitive values in OpenHome's key-value store: the lock timer and a rolling log of voice-trade dollar amounts (for the daily cap). API keys are read at runtime via `get_api_keys()` and never written or logged.

## Known limitations

- Base only; cbBTC and ETH only.
- No transfers.
- Bankr has no testnet. Test with a few dollars.
- Bankr's `buyTokenPriceUsd` / `sellTokenPriceUsd` quote fields have been observed ~14% stale for cbBTC. This ability ignores them and uses the effective execution price. Bankr's own price-impact protection does use them, so a fair cbBTC sell can be rejected with a 403; the ability reports "Nothing was traded."
