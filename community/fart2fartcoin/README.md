# Fart2Fart(coin)

Detect a fart, buy Fartcoin. No questions asked.

Every time the room produces a confirmed fart, the ability sells a whole number
of dollars of USDC through your Bankr wallet and lands Fartcoin on Solana:

> "Warning. Room-clearing event detected. Magnitude six point two. Duration
> one point four seconds. Open a window and be on smell lookout."
> "Bought one dollar of Fartcoin, about seven point four one Fartcoin."

Audio never leaves the device. Only the event metadata does. Only the cloud
talks to Bankr.

## Built on

Two sibling abilities, combined. The detector and the trader are theirs; the
"every fart is a buy signal" part is new here.

- **Fart Finder** ([openhome-dev/abilities#378](https://github.com/openhome-dev/abilities/pull/378)) — the device listener, YAMNet classifier, Ripter scale and the cloud daemon, copied unchanged into `devkit_functions.py`, `listener/` and the polling loop in `background.py`.
- **openhome-bankr** ([openhome-dev/abilities#377](https://github.com/openhome-dev/abilities/pull/377)) — the Bankr Wallet API quote-then-swap path, response-to-speech mapping and dollar parsing, lifted into `trade.py` minus the voice confirmation and app-side caps this ability deliberately drops.

If those land under `community/fart-finder` and `community/openhome-bankr`, the links above are the history of where this code came from.

## Trigger words

`fart finder`, `fart detector`, `flatulence`, `fart trading`, `fart buy`, `fartcoin`

| Say | Does |
|---|---|
| "fart finder, arm" | records consent, starts listening (once) |
| "set my fart buy to three dollars" | whole dollars only, 1 and up |
| "turn fart trading on" | quotes once to check the route, then goes live |
| "turn fart trading off" | back to dry run: announces, says what it would have bought |
| "what have my farts cost me today" | count, dollars, tokens, anything blocked by your Bankr limit |
| "how much Fartcoin do I have" | Solana balance, buys still in transit |
| "how much fart money is left" | USDC and gas on the funding chain |
| "how many today", "disarm", "sensitivity high" | Fart Finder as before |

## The trade

| | |
|---|---|
| Token | Fartcoin, Solana mint `9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump`. The only official one. Every "Fartcoin" on Base is an impostor. |
| Route | `base_to_solana` (default): Base USDC to Solana Fartcoin in one Bankr `/wallet/swap`. Bankr's bridge leg delivers to your wallet's own Solana address. Fallback `solana`: same-chain, needs USDC and SOL on Solana. |
| Amount | Whole dollars of USDC per fart. Default 1. |
| Confirmation | None. That is the point. |
| Spend limit | Yours to set on bankr.bot → Security (per-transaction and daily, behind passkey). Bankr enforces it at execution; the ability just reports the refusal. There is no cap in this code. |
| Double-buy guard | The Bankr idempotency key is the fart event id. A redeploy or a retry can never buy the same fart twice. |
| Arrival | A cross-chain fill returns the Base hash. The daemon then watches the Solana balance and marks each buy landed, or says so once if it has not after ten minutes. |

## Setup, in this order

1. **Bankr keys** at bankr.bot/api-keys. Two keys:
   `bankr_read_key` read-only on, Wallet API on. `bankr_trade_key` read-only off, Wallet API on, Agent API off.
2. **Bankr limits** at bankr.bot → Security. Set a per-transaction limit at or above your buy amount and a daily limit you can live with. This is the only brake.
3. **Fund** the Bankr wallet on Base: USDC for buys, about two dollars of ETH for gas. Nothing is needed on Solana.
4. **Settings → API Keys** in OpenHome: add the two keys above, and optionally:

| Name | Values | Default |
|---|---|---|
| `fart2fart_buy_usd` | whole dollars, 1+ | `1` |
| `fart2fart_mode` | `dry_run`, `live` | `dry_run` |
| `fart2fart_route` | `base_to_solana`, `solana` | `base_to_solana` |
| `fart2fart_slippage_bps` | 10 to 2000 | `300` |
| `fartfinder_hooks` | `speak`, `buy`, `led`, `webhook` | `speak,buy` |
| `fartfinder_transport` | `devkit`, `local` | `devkit` |

   Voice settings (amount, mode) are stored in the KV store and win over these.
5. Say **"fart finder, arm"**, then **"turn fart trading on"**. Until you do, every fart is announced with a dry-run line and nothing is bought.

Treat the wallet as a hot wallet. Fund it with a few days of farts, not a treasury.

## Files

| File | Runs on | Does |
|---|---|---|
| `main.py` | cloud | Voice commands |
| `background.py` | cloud | Poll the device, announce, `buy` hook, arrival check, daily line |
| `trade.py` | source only | Pure Bankr functions: route table, requests, response mapping, journal. No SDK, fully unit tested. **Not imported at runtime**: the sandbox caches sibling modules across pushes, so `tools/inline_trade.py` copies its body into `main.py` and `background.py` between markers, and a test fails if the copies drift. Edit `trade.py`, run the tool, push. |
| `devkit_functions.py` | device | Listener daemon and RPC, unchanged from Fart Finder |
| `listener/` | device | Gate, YAMNet, magnitude, unchanged from Fart Finder |
| `pi/` | device | Install script, systemd unit, ALSA config |

## What Bankr says and what you hear

| Bankr | You hear |
|---|---|
| 200, success, hash | "Bought one dollar of Fartcoin, about seven point four one Fartcoin." |
| 200, success false | "The buy reverted on chain. Nothing spent, apart from a little gas." |
| 403 spend limit | "Bankr's spending limit stopped this one." Later farts that day skip Bankr entirely. |
| 403 read-only / paused | Once per session: "The trade key is read-only" / "The Bankr wallet is paused." |
| 400 balance / gas | Once per session: "The wallet is out of dollars on Base." / "out of gas on Base." |
| 502 | "No bridge route right now. Skipped." |
| 504 or timeout | "Not sure that one went through. I'll check." Then the arrival check resolves it. Never re-bought. |

## Status

**Verified live on 2026-09-16** with a Mac standing in for the DevKit: a fart
clip played through the speakers was detected, and nine seconds later Bankr
sold $1 of USDC on Base and landed 5.977 Fartcoin on Solana (tx
`0xf50b8ef8…d93a`). The arrival check saw the balance rise, and the voice
report and balance intents read back correctly. 123 unit tests, no network.

Two things learned the hard way, both fixed:
- Bankr requires `idempotencyKey` to be a UUID. We derive a UUID5 from the fart event id.
- The OpenHome sandbox caches sibling modules across pushes (and forbids `importlib`), so `trade.py` is inlined; see Files.

Trigger-word note: "fartcoin" is also caught by the openhomebankr ability
("coin"). Use "fart trading" or "fart finder" as the wake phrase if both are installed.
DevKit verification is still pending.
