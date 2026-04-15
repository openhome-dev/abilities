# Multi-Platform Sales Monitor

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@ammadyousaf-lightgrey?style=flat-square)

## What It Does

Get real-time sales insights from Gumroad and Shopify with voice commands. Track revenue, compare platforms, analyze trends, and monitor your e-commerce performance—all hands-free.

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
  "gumroad_access_token": "YOUR_GUMROAD_ACCESS_TOKEN",
  "shopify_shop_url": "your-store.myshopify.com",
  "shopify_access_token": "YOUR_SHOPIFY_ADMIN_API_ACCESS_TOKEN"
}
```

Upload this file via OpenHome file storage (or the path your deployment uses for `sales_monitor_prefs.json`).

## How It Works

1. User says a trigger phrase (e.g. "check my online sales").
2. The ability loads preferences from `sales_monitor_prefs.json` and calls the Gumroad and Shopify APIs.
3. It opens with a short dashboard summary: "Today you're at X dollars from Y sales. Want the full breakdown?"
4. If user says "yes", "sure", or "go ahead", it provides comprehensive stats (week, month, platform breakdown, best seller).
5. Follow-up queries are handled with LLM-based intent classification:
   - Platform breakdown ("What about Shopify?", "Check Gumroad sales")
   - Digital vs physical sales comparison
   - Trends (today vs yesterday growth)
   - Weekly/monthly totals
   - Best sellers, customer counts, average orders
6. Multi-number responses are split into separate speak calls for better pacing.
7. Follow-up prompts vary ("What else?", "Anything else?", "Want to know more?") to feel more natural.
8. Say "thanks", "stop", "done", or similar to exit. Every exit path calls `resume_normal_flow()`.

## Example Conversation

> **User:** "Check my online sales"
>
> **AI:** "Today you're at 477 dollars from 6 sales. Want the full breakdown?"
>
> **User:** "Yes"
>
> **AI:** "This week you're at 477 dollars, and this month 477 dollars."
>
> **AI:** "Today, Gumroad's at 177 dollars and Shopify's at 300 dollars."
>
> **AI:** "Your best seller this month is Logo T-Shirt with 2 units."
>
> **AI:** "Anything else?"
>
> **User:** "What about Shopify?"
>
> **AI:** "Shopify's at 300 dollars from 3 orders."
>
> **AI:** "Want to know more?"
>
> **User:** "Check trends"
>
> **AI:** "You're up 15 percent compared to yesterday."
>
> **AI:** "What else would you like to know?"
>
> **User:** "Thanks"
>
> **AI:** "Okay, talk to you later!"

## Features

- **LLM Intent Classification**: Uses `text_to_text_response()` to understand natural phrases like "how's business been" or "what did I pull in today"
- **Smart Platform Detection**: "Check Shopify sales" only reports Shopify, not both platforms
- **Paced Responses**: Multi-number responses split into separate speak calls for better comprehension
- **Varied Prompts**: Rotates through 5 different follow-up phrases to feel less robotic
- **Comprehensive Breakdown**: Say "yes" after opening to get week/month/platform/best seller stats
- **Multiple Time Ranges**: Today, yesterday, this week, this month, all-time (past year)
- **Product Analytics**: Best sellers, product counts, sales by item
- **Customer Insights**: Unique customer counts, average order values
- **Growth Tracking**: Compare today vs yesterday with percentage changes

## Contributing to OpenHome (upstream PR)

To submit this ability to [OpenHome-dev/abilities](https://github.com/OpenHome-dev/abilities):

1. Fork the repo and clone it.
2. From branch `dev`, create a branch such as `add-multi-platform-sales-monitor`.
3. Copy this folder's contents into `community/multi-platform-sales-monitor/` in the fork (`main.py`, `README.md`, and any other required files per the repo).
4. Open a **Pull Request against `dev`** (not `main`), and complete the PR template.

See the repository's contributing guide for validation, linting, and review expectations.