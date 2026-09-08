# PantryPro — Voice-Guided Pantry Assistant

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Status](https://img.shields.io/badge/Status-Stage%201-blue?style=flat-square)

A voice-first pantry assistant for OpenHome. Track what's in the pantry and fridge, get meal ideas from what you already have (oldest food first), hear alerts before things go bad, and build a shopping list from the gaps.

**Reduce waste. Save money.**

---

## What it does

| Feature | What you say | What happens |
| --- | --- | --- |
| **Track inventory** | "add milk to the fridge, expires Friday" | Logs item, location, quantity, and best-by date |
| **Smart suggestions** | "what can I cook?" | Matches stock to real recipes (TheMealDB), prioritizing food that's about to expire |
| **Email the recipe** | "email the recipe" | Sends the picked recipe (ingredients + steps) to your phone |
| **Email the shopping list** | "email the shopping list" | Sends the grocery list, with no extra questions |
| **Expiration alerts** | (automatic) | Background daemon speaks up when items expire today, tomorrow, or within 3 days |
| **Shopping made easy** | "we're out of pasta" | Removes it from stock and offers to put it on the grocery list; missing recipe ingredients can be added the same way |

No API key required for pantry tracking. Recipes use the free [TheMealDB](https://www.themealdb.com) API, with an LLM fallback if the network is down. Emailing to your phone is optional (see Setup).

---

## Suggested trigger words

Dashboard triggers must be **at least 4 letters**. Recommended:

`pantry`, `pantry pro`, `what's in the fridge`, `what's in the pantry`, `what's expiring`, `what can I cook`, `recipe ideas`, `food inventory`, `grocery run`

In-session phrases (after PantryPro is already running):

| Phrase | What it does |
| --- | --- |
| `"add pasta and canned beans"` | Add items (asks for a date if you skip one) |
| `"check the fridge"` / `"what's in stock"` | Read back inventory |
| `"what's going bad"` | Items expiring within 5 days |
| `"I used the last of the milk"` | Remove + offer to restock on the shopping list |
| `"what can I cook"` | 3 meal ideas from current stock |
| `"email the recipe"` | Email the last picked recipe |
| `"email the shopping list"` | Email the grocery list right away |
| `"what's on my shopping list"` | Read the list, then offer to email it |
| `"clear the shopping list"` | Confirm, then wipe it |
| `"done"` | Save and return to the Agent |

---

## Example conversation

**User:** “Pantry pro.”

**PantryPro:** “You have pasta, tomato sauce, and canned beans. Want recipe ideas?”

**User:** “Yes.”

**PantryPro:** “One sec, matching what you've got to some meals.”

**PantryPro:** “Using tomato sauce before it goes. I can do 1, Pasta and Beans. 2, Tomato and Herb Pasta. 3, Bean chilli. Pick a number, or say skip.”

**User:** “1.”

**PantryPro:** “Pasta and Beans. You're missing onion and garlic. Add those to the shopping list?”

**User:** “Yes.”

**PantryPro:** “Added onion and garlic to the shopping list. Want me to email you the Pasta and Beans recipe?”

**User:** “Yes.”

**PantryPro:** “Sent the recipe to you at gmail dot com.”

**User:** “We're out of milk.”

**PantryPro:** “Removed milk. Add milk to the shopping list?”

**User:** “Yes.”

**PantryPro:** “Added milk to the shopping list.”

**User:** “What's on my shopping list?”

**PantryPro:** “3 items: onion, garlic, and milk. Want me to email it?”

**User:** “Yes.”

**PantryPro:** “Sent the shopping list.”

**User:** “Done.”

**PantryPro:** “Saved. 3 items in stock, 3 on the shopping list.”

Background, later that session:

**PantryPro:** “Heads up — yogurt in the fridge expires tomorrow. Want a recipe that uses it? Say pantry pro.”

---

## How it works

1. Trigger with `pantry` (or a specific ask like “what's expiring”).
2. Inventory loads from persistent storage (`pantrypro_inventory.json`).
3. A specific ask is handled immediately (quick mode). A bare “pantry pro” greets with what's on hand and offers recipes.
4. Natural speech is classified by the LLM — add, used-up, list, recipes, shopping, email recipe, email list, tips.
5. Recipe search hits TheMealDB using your soonest-to-expire ingredient, then compares the ingredient list to stock. After you pick a meal, PantryPro can **email** the full recipe (not read it aloud). The LLM fallback also reads `user_profile.md` (diet, household size) — read-only, never written.
6. Shopping list email is its own command: **email the shopping list** sends it immediately. Asking **what's on my shopping list** only reads it (and offers to email). Say **done** to hand control back. The background daemon keeps watching expiry dates for the rest of the session.

### Background daemon

Runs while the Agent session is alive. Checks every 5 minutes (90-second startup grace so it doesn't talk over boot).

| Days to expiry | What happens |
| --- | --- |
| 3 days | First heads-up (once per day) |
| 1 day / today | Daily urgent alert |
| Already expired | Daily reminder until you remove it |

Alerts are grouped: *“Urgent — 2 items need using: milk expires today and spinach expires tomorrow.”*

---

## Setup

1. Install the ability and set dashboard triggers (see above).
2. Talk to it. First run starts empty — log a few items to get recipe ideas and alerts.
3. **Optional — email to your phone.** OpenHome cannot send SMS by itself. Email is the way to get a copy on your device:
   - In OpenHome **Settings → API Keys**, add `pantrypro_sender_email` (a Gmail address) and `pantrypro_sender_password` (a [Gmail app password](https://support.google.com/accounts/answer/185833)).
   - PantryPro asks for your address once and remembers it.
   - Recipe emails happen when you pick a meal (or say **email the recipe**).
   - **Email the shopping list** sends the grocery list immediately. Asking **what's on my shopping list** only reads it, then offers to email.

Cook-along steps stay in Mealmate / Smart Sous Chef / Recipe Coach.

---

## Project layout

```
community/pantry-pro/
├── README.md
├── .openhome.json
├── main.py          # voice skill
├── background.py    # expiry alerts
└── __init__.py
```

Runtime (user storage, not shipped): `pantrypro_inventory.json`

---

## Related

Nearby kitchen abilities — PantryPro is the persistent *stock + expiry* layer, not a duplicate of these:

- [`community/grocery-list-manager`](../grocery-list-manager/) — shopping list only
- [`community/mealmate-ability`](../mealmate-ability/) — recipe search; you list ingredients each time
- [`community/smart-sous-chef`](../smart-sous-chef/) — hands-free cook-along
- [`community/recipe-coach`](../recipe-coach/) — LLM-generated walkthroughs
- [`community/food-water-log`](../food-water-log/) — what you *ate*, not what's on the shelf

---

## Status

Stage 1 is live-testable: add/remove stock → expiry dates → recipe ideas from inventory → shopping gaps → email recipe or list → background alerts.
