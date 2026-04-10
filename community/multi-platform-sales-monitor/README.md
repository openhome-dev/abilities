# Multi-Platform Sales Monitor

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@ammadyousaf-lightgrey?style=flat-square)

## What It Does

Get real-time sales insights from Gumroad and Shopify with voice commands. Track revenue, compare platforms, analyze trends, and monitor your e-commerce performance—all hands-free. Works immediately in demo mode, or connect your APIs for live data.

## Suggested Trigger Words

Configure these (or similar) in the OpenHome dashboard for this ability:

- "check my sales"
- "online sales"
- "sales revenue"
- "shopify sales"
- "gumroad sales"
- "how much did I make"
- "sales dashboard"
- "store sales"

## Setup

**Demo mode (default)**

The ability runs with realistic sample data. No API keys required.

**Production mode (live sales data)**

You need API credentials from Gumroad and Shopify:

**1. Gumroad API token**

- Open https://app.gumroad.com/settings/advanced
- Under **Application**, generate an access token and copy it.

**2. Shopify Admin API**

- In Shopify Admin: **Settings** → **Apps and sales channels** → **Develop apps**
- Create an app, enable Admin API scopes such as `read_orders` (and `read_products` if needed), install the app, and copy the Admin API access token.
- Note your shop domain (e.g. `your-store.myshopify.com`).

**3. Preferences file**

Create `sales_monitor_prefs.json` with **your** secrets (never commit real tokens to git):

```json
{
  "demo_mode": false,
  "gumroad_access_token": "YOUR_GUMROAD_ACCESS_TOKEN",
  "shopify_shop_url": "your-store.myshopify.com",
  "shopify_access_token": "YOUR_SHOPIFY_ADMIN_API_ACCESS_TOKEN"
}
```

Upload this file via OpenHome file storage (or the path your deployment uses for `sales_monitor_prefs.json`).

## How It Works

1. User says a trigger phrase (e.g. "check my online sales").
2. The ability loads preferences; if `demo_mode` is true or unset, it uses demo data; otherwise it calls the Gumroad and Shopify APIs.
3. It opens with a short dashboard: today / week / month, then a second line with today’s Gumroad vs Shopify split and best seller when relevant.
4. Follow-ups are handled with keyword-based intents: platform breakdown, digital vs physical, trends, weekly/monthly totals, and more.
5. Say "thanks", "stop", "done", or similar to exit. Every exit path calls `resume_normal_flow()`.

## Example Conversation

> **User:** "Check my online sales"
>
> **AI:** "Today: 477 dollars from 6 sales. This week: 477 dollars. This month: 477 dollars."
>
> **AI:** "Gumroad: 177 dollars, Shopify: 300 dollars. Best seller: Logo T-Shirt with 2 units."
>
> **AI:** "What else would you like to know?"
>
> **User:** "What about Shopify?"
>
> **AI:** "Shopify's at 300 dollars from 3 orders."
>
> **User:** "Thanks"
>
> **AI:** "Okay, talk to you later!"

## Contributing to OpenHome (upstream PR)

To submit this ability to [OpenHome-dev/abilities](https://github.com/OpenHome-dev/abilities):

1. Fork the repo and clone it.
2. From branch `dev`, create a branch such as `add-multi-platform-sales-monitor`.
3. Copy this folder’s contents into `community/multi-platform-sales-monitor/` in the fork (`main.py`, `README.md`, and any other required files per the repo).
4. Open a **Pull Request against `dev`** (not `main`), and complete the PR template.

See the repository’s contributing guide for validation, linting, and review expectations.
