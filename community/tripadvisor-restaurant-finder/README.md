# TripAdvisor Restaurant Finder

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)

## What It Does

Voice-activated restaurant discovery powered by TripAdvisor. Say a city and optionally a cuisine — get the top-rated restaurants with name, rating, price range, and cuisine type. Ask for details or reviews on any result.

## Suggested Trigger Words

- "restaurant" / "restaurants"
- "where to eat" / "where should I eat"
- "find food" / "good food" / "places to eat"
- "best restaurant" / "food near"
- "dinner" / "lunch" / "brunch"
- "find me a restaurant" / "recommend a restaurant"
- "tripadvisor" / "trip advisor"
- "reviews for" / "restaurant reviews"

## Setup

1. Go to [rapidapi.com](https://rapidapi.com) and create a free account
2. Search for **TripAdvisor16** by DataCrawler and subscribe to the free plan
3. Copy your API key from your RapidAPI dashboard
4. When you first use this ability, it will ask you to provide the key by voice

Free tier allows ~500 requests/month (~250 searches since each search uses 2 API calls).

## How It Works

**Mode 1 — Find Restaurants:**
1. Say a location and optionally a cuisine (e.g., "Find Italian restaurants in Austin")
2. The ability searches TripAdvisor and speaks back the top 3 results
3. Each result includes: name, rating, review count, price range, and cuisine
4. Say "more" to hear additional results

**Mode 2 — Details & Reviews:**
1. Say "tell me more about number two" or "reviews for Uchi"
2. Get full details: address, rating, price, description
3. Hear top review excerpts (max 2, truncated for voice)

## Example Conversation

> **User:** "Find Italian restaurants in Austin"
> **AI:** "Here are the top restaurants in Austin. Number one: Uchi, rated four point five out of five with 2847 reviews. It's upscale, serving Japanese and Sushi. Number two: ..."

> **User:** "Tell me more about number one"
> **AI:** "Uchi is a Japanese restaurant in 801 S Lamar Blvd, Austin. Rated four point five out of five based on 2847 reviews. Price range is upscale."

> **User:** "Reviews for number one"
> **AI:** "Here's what people are saying about Uchi. One reviewer titled their review 'Best sushi in Texas'. A reviewer said: 'Incredible omakase experience with creative...'."

> **User:** "Find cheap Thai food in Brooklyn"
> **AI:** "Searching in Brooklyn. Here are the top restaurants..."

> **User:** "Stop"
> **AI:** "Happy dining! Goodbye."
