# Redcast Heritage Browser

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)

## What It Does
Browse available items on [Redcast Heritage](https://redcastheritage.com) by brand, category, and size — all by voice. Ask "show me large shirts from Iron Heart" or "what hats are available?" and get a spoken list of what's in stock.

## Suggested Trigger Words
- "redcast"
- "browse redcast"
- "redcast heritage"
- "what does redcast have"
- "show me redcast"

## Setup
- No API keys needed.
- No external services required beyond the Redcast Heritage website (Shopify-powered, public JSON endpoints).
- Uses the built-in LLM to extract filters from natural language.

## How It Works
When triggered, the ability asks what you're looking for. You can mention:
- **Brand** - "Iron Heart", "Samurai", "Warehouse", etc.
- **Category** - "shirts", "jeans", "hats", "jackets", etc.
- **Size** - "large", "medium", "31", "32", etc.

The LLM extracts these filters from your natural language request, then the ability fetches the full Redcast catalog and filters it down to items that match AND are currently in stock in your size.

**Results:** If there are 1-5 items, it reads them all. If there are more than 5, it reads the first 5 and asks if you want to hear more.

All web calls use `asyncio.to_thread()` with timeouts, and filler speech plays before network calls.

## SDK Features Used
- `speak()` / `user_response()` — voice I/O
- `text_to_text_response()` — LLM filter extraction
- `editor_logging_handler` — structured logging
- `resume_normal_flow()` — clean exit (via `try/finally`)

## Example Conversations

**Example 1: Browse by brand and size**
> **User:** "Browse redcast"
> **AI:** "What are you looking for? You can say a brand, category, or size."
> **User:** "Large shirts from Iron Heart"
> **AI:** "One sec, checking the catalog."
> **AI:** "Found 3 items: Iron Heart IHSH-33 Work Shirt, Iron Heart IHSH-62 Flannel, Iron Heart IHSH-99 Chambray."

**Example 2: Browse by category**
> **User:** "Redcast"
> **AI:** "What are you looking for? You can say a brand, category, or size."
> **User:** "What hats do you have?"
> **AI:** "One sec, checking the catalog."
> **AI:** "Found 2 items: Warehouse Duck Canvas Cap, Redcast Heritage Trucker Hat."

**Example 3: Browse by brand only**
> **User:** "Show me redcast"
> **AI:** "What are you looking for? You can say a brand, category, or size."
> **User:** "Samurai jeans"
> **AI:** "One sec, checking the catalog."
> **AI:** "Found 8 items. Here are the first five: Samurai S510XX, Samurai S710XX, Samurai S0510XX, Samurai S5000VX, Samurai S0511XX."
> **AI:** "There are 3 more. Want me to keep going?"
> **User:** "Yes"
> **AI:** "Samurai S710HXII, Samurai S0510HXII, Samurai S211VX."

**Example 4: Nothing found**
> **User:** "Redcast"
> **AI:** "What are you looking for? You can say a brand, category, or size."
> **User:** "XXL jackets from Warehouse"
> **AI:** "One sec, checking the catalog."
> **AI:** "I didn't find anything size XXL jackets from Warehouse that's in stock."
