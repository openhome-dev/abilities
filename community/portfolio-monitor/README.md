# Portfolio Monitor

A passive background ability that tracks your stock portfolio in real time, fires proactive alerts when positions move beyond your thresholds, and delivers a full P&L breakdown on demand — all by voice.

Just add your stocks once and it handles the rest: morning open summary, live price monitoring every 5 minutes during market hours, and an end-of-day wrap-up when the bell rings.

## Setup

1. Get a free API key at [finnhub.io](https://finnhub.io) (60 calls/minute, no daily cap)
2. In OpenHome, go to **Settings → API Keys** and add your key as `finnhub_api_key`
3. Optionally get an [Alpha Vantage](https://www.alphavantage.co) key (25 calls/day free) and add it as `alphavantage_api_key`

## Trigger Phrases

- `portfolio monitor` / `my portfolio` / `portfolio update`
- `check my stocks` / `stock update` / `stock check`
- `check Apple` / `how's Tesla` / `how's NVDA doing`
- `compare my stocks` / `day over day` / `versus yesterday` / `how did my stocks do`
- `add a stock` / `add to portfolio` / `log a stock`
- `update my position` / `bought more` / `I sold` / `add more shares` / `sold some`
- `remove from portfolio` / `remove a stock`
- `set a stock alert` / `price alert`
- `biggest movers` / `what's moving` / `gainers today` / `losers today`
- `how are the markets` / `market update` / `market pulse` / `market today`
- `clear my portfolio` / `wipe my portfolio`

## Features

**Passive Monitoring**
- Polls every 5 minutes during market hours (9:30am–4:00pm ET, Mon–Fri)
- Sleeps 30 minutes outside market hours — no wasted API calls
- Price cache with 3-minute TTL prevents redundant fetches

**Proactive Alerts**
- Morning open: brief summary of what you're tracking when market opens
- Price alerts: fires immediately when a stock drops or rises beyond your threshold (day change %)
- End-of-day wrap-up: portfolio value, day P&L, top gainer and loser
- Each alert fires at most once per day per direction per stock

**Interactive Queries**
- PORTFOLIO: opens with a quick snapshot (total value, today's P&L, overall P&L), then offers navigation — say 'breakdown', 'compare', 'movers', 'market', or a stock name
- BREAKDOWN: full per-stock detail — price, day change %, position value, and overall P&L (chunked at 4 stocks, asks if you want more)
- COMPARE: day-over-day view — each stock's price move and dollar change vs yesterday's close
- CHECK: current price, day change, and position P&L for a specific stock; follow-up loop to check multiple stocks back-to-back
- MOVERS: biggest gainer and loser in your portfolio today
- MARKET: live pulse on S&P 500, Nasdaq, and Dow Jones
- ADD: add a stock by name or ticker — specify shares and avg cost in one shot or via follow-up prompts; loop to add multiple stocks; offers UPDATE if stock already exists
- UPDATE: modify an existing position — bought more shares (recalculates weighted avg cost), sold some (reduces share count or removes if fully sold), or correct/overwrite values
- SET_ALERT: set drop/rise percentage thresholds per stock; loop to set alerts for multiple stocks
- REMOVE: remove a stock from your portfolio (with confirmation)
- CLEAR: wipe the entire portfolio (with confirmation)

**Smart Details**
- LLM intent router handles natural, complex requests reliably ("what happened to my Google position", "how's the portfolio looking")
- Resolves company names to tickers (say "Apple", not "AAPL"); LLM fallback for any company not in the built-in map
- Finnhub primary API with Alpha Vantage fallback
- On-demand price fetch if cache is empty; TTL-aware refresh so data is always current
- Market-hours-aware ET timezone detection (DST handled, no external library)

## Example Conversation

> **You:** my portfolio
>
> **Assistant:** Portfolio at $47,200 — down $380 today, up $3,100 (7%) overall. Say 'breakdown' for full detail, 'compare' for day-over-day, 'movers' for biggest movers, 'market' for market indices, or a stock name.
>
> **You:** market
>
> **Assistant:** Markets today: S&P 500 down 0.8%, Nasdaq down 1.2%, Dow Jones down 0.5%.
>
> **You:** how's Apple doing
>
> **Assistant:** Apple is at $189, down 1% today. Your 20 shares are worth $3,780 — up $620 (20%) on your position.
>
> **You:** breakdown
>
> **Assistant:** Apple: $189, down 1% today, up $620 (20%) overall. Tesla: $242, down 2% today, down $180 (4%) overall. Nvidia: $875, up 3% today, up $4,100 (68%) overall. Microsoft: $415, flat today, up $900 (12%) overall. Want to hear the rest?
>
> **You:** yes
>
> **Assistant:** Amazon: $198, down 0% today, up $260 (7%) overall.

---

> **You:** I bought more Tesla
>
> **Assistant:** Tesla: 10 shares at $220 average, total cost $2,200. Say 'bought more', 'sold some', or 'correct' to overwrite.
>
> **You:** bought more
>
> **Assistant:** How many shares did you buy, and at what price? Say both — like '5 at 210'.
>
> **You:** 5 at 245
>
> **Assistant:** Updated — Tesla now 15 shares at $228 average.

---

> **[Background alert, proactive]**
>
> **Assistant:** Heads up — Nvidia is down 5% today. Your position is up $3,200. Say 'portfolio monitor' to review.

## Notes

- Price alerts are based on the day's change percentage (vs previous close), not vs your avg cost
- The background daemon only runs while OpenHome is active — not a 24/7 service
- Supports 50+ major US companies by name out of the box; any ticker symbol works directly
- Trigger phrases for UPDATE: `update my position`, `bought more`, `I sold`, `add more shares`, `sold some`
- Trigger phrases for MARKET: `how are the markets`, `market update`, `market pulse`, `market today`
