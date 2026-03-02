# Dominos Menu Checker and Order Tracker

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@freddieliang-lightgrey?style=flat-square)

## What It Does

Look up Domino's menu items and prices from your nearest store using voice, and track existing Domino's orders by phone number.

## Suggested Trigger Words

- "check the dominos menu"
- "dominos menu"
- "dominos prices"
- "how much is a pizza"
- "pizza prices"
- "check pizza prices"
- "look up dominos"
- "what's on the dominos menu"
- "dominos price check"
- "check dominos"
- "track my order"
- "track order"
- "check my order"
- "order status"
- "where's my order"
- "dominos tracker"
- "dominos order tracker"
- "dominos tracking"

## Setup

- No API keys needed -- Domino's web API is unauthenticated
- Install dependency: `pip install requests`
- Upload the folder via the OpenHome dashboard at app.openhome.com
- Enable auto-interrupt in OpenHome settings (recommended)

## How It Works

1. **Address**: Provide your address or use a saved location from a previous session
2. **Store Lookup**: Finds your nearest open Domino's and shows its name and phone number
3. **Menu Browsing**: Ask about items naturally -- "large pepperoni pizza", "chicken wings", "two liter coke"
4. **Recap**: When you're done, get a summary of everything you looked up
5. **Order Handoff**: Get a direct link to the store's Domino's order page and their phone number
6. **Order Tracking**: Track an existing order by phone number -- say "track my order" at any time during browsing, or provide your number at the end

Say "stop", "exit", "quit", "cancel", "never mind", "go back", or "goodbye" at any point to exit.

## Example Conversation

> **User:** "Check the dominos menu"
> **AI:** "Domino's menu checker! What's your address or location?"
> **User:** "123 Main Street, Los Angeles, California"
> **AI:** "I heard: 123 Main Street, Los Angeles, CA. Is that correct?"
> **User:** "Yes"
> **AI:** "Finding your nearest Domino's... Your nearest Domino's is Store on Main St. Their phone number is 555-123-4567. Loading their menu now..."
> **AI:** "What would you like to look up?"
> **User:** "How much is a large pepperoni pizza?"
> **AI:** "Large Pepperoni Pizza (size 14) is $13.99. Want to look up anything else?"
> **User:** "Track my order"
> **AI:** "Sure! What's the phone number associated with your order?"
> **User:** "555-867-5309"
> **AI:** "Checking on your order... Your order is currently being prepared and should be ready in about 15 minutes."
> **User:** "Done"
> **AI:** "Here's a recap of what you looked up: You checked a large pepperoni pizza for $13.99."
> **AI:** "Thanks for using the Domino's menu checker!"
