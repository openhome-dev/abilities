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
| **Expiration alerts** | (automatic) | Background daemon speaks up when items expire today, tomorrow, or within 3 days |
| **Shopping made easy** | "we're out of pasta" | Removes it from stock and offers to put it on the grocery list; missing recipe ingredients can be added the same way |

No API key required. Recipes use the free [TheMealDB](https://www.themealdb.com) API, with an LLM fallback if the network is down.

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
| `"what's on my shopping list"` | Read the list |
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

**PantryPro:** “Added onion and garlic to the shopping list.”

**User:** “We're out of milk.”

**PantryPro:** “Removed milk. Add milk to the shopping list?”

**User:** “Yes. Done.”

**PantryPro:** “Saved. 3 items in stock, 3 on the shopping list.”

Background, later that session:

**PantryPro:** “Heads up — yogurt in the fridge expires tomorrow. Want a recipe that uses it? Say pantry pro.”

---

## How it works

1. Trigger with `pantry` (or a specific ask like “what's expiring”).
2. Inventory loads from persistent storage (`pantrypro_inventory.json`).
3. A specific ask is handled immediately (quick mode). A bare “pantry pro” greets with what's on hand and offers recipes.
4. Natural speech is classified by the LLM — add, used-up, list, recipes, shopping, tips.
5. Recipe search hits TheMealDB using your soonest-to-expire ingredient, then compares the ingredient list to stock. The LLM fallback also reads `user_profile.md` (diet, household size) — read-only, never written.
6. Say **done** to hand control back. The background daemon keeps watching expiry dates for the rest of the session.

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
2. No API keys or extra config.
3. Talk to it. First run starts empty — log a few items to get recipe ideas and alerts.

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

Stage 1 is live-testable: add/remove stock → expiry dates → recipe ideas from inventory → shopping gaps → background alerts. Cook-along steps stay in Mealmate / Smart Sous Chef / Recipe Coach.
