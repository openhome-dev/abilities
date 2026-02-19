# Mealmate

## What It Does
A voice-powered recipe assistant that searches 1000+ recipes, guides you through cooking steps, and generates shopping lists.  
Find recipes by dish name, ingredients you have, cuisine, category, or get a random surprise — all hands-free.

## Suggested Trigger Words
- recipe
- cooking
- food recipe
- what to cook
- recipe ideas
- meal ideas
- find a recipe
- cooking assistant
- meal helper
- mealmate

## Setup
- **No API key required.** Uses the free TheMealDB API (https://www.themealdb.com).
- No configuration needed — works out of the box.

## How It Works
1. User triggers with "recipe" (or similar)
2. Assistant asks how to help — by dish name, pantry ingredients, category, cuisine, or random
3. Based on choice, searches TheMealDB and presents options
4. User picks a recipe from the list
5. Shows full recipe details: ingredients, category, cuisine
6. Offers next actions:
   - **'cook'** → Guided step-by-step cooking mode with next/back/repeat commands
   - **'list'** → Shopping list of all ingredients
   - **'another'** → Start a new search
   - **'done'** → Exit

## Supported Search Modes
- **Name** — Search by dish name (e.g., "chicken tikka", "spaghetti")
- **Pantry** — Find recipes using ingredients you have (e.g., "chicken, onion, rice")
- **Category** — Browse by category (Beef, Chicken, Dessert, Pasta, Seafood, Vegetarian, etc.)
- **Area/Cuisine** — Browse by cuisine (American, British, Chinese, French, Indian, Italian, Japanese, Mexican, Thai, etc.)
- **Random** — Get a surprise meal

## Example Conversation

**User:** recipe  
**AI:** 🍳 Mealmate here! Tell me how to help: Say a dish name (e.g., 'chicken curry'), say 'pantry' to use your ingredients, say 'category' or 'area' to browse, or say 'random' to surprise you.

**User:** chicken tikka  
**AI:** I found:  
1) Chicken Tikka Masala  
2) Tandoori Chicken  
3) Chicken Curry  
Pick a number (or 'cancel'):

**User:** 1  
**AI:** **Chicken Tikka Masala**  
Category: Chicken • Area: Indian  
Ingredients:  
- 500g chicken breast  
- 200ml yogurt  
- 2 tbsp tikka paste  
- ...  
Type 'cook' for guided steps, 'list' for shopping list, 'another' for new search, or 'done' to exit.

**User:** cook  
**AI:** 👩‍🍳 Entering cook mode. Commands: next / back / repeat / exit  
Step 1: Marinate chicken in yogurt and tikka paste for 30 minutes.

**User:** next  
**AI:** Step 2: Heat oil in a pan and add marinated chicken.

**User:** next  
**AI:** Step 3: Cook for 10-12 minutes until browned.  
...  
**AI:** 🎉 All done. Bon appétit!

**User:** recipe  
**AI:** How should I help?

**User:** pantry  
**AI:** List ingredients you have (comma-separated), e.g., 'chicken, onion, rice':

**User:** chicken, rice, tomato  
**AI:** Here are some options:  
1) Chicken Biryani  
2) Spanish Rice  
3) Chicken Fried Rice  
Pick a number (or 'cancel'):
