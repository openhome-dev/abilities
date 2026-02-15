# Grocery List Manager

## What It Does
A shared household grocery list managed entirely by voice. Add, remove, read, and clear items hands-free — perfect for when your hands are dirty from cooking. Uses the LLM to understand natural speech so you can say "put milk on the list" instead of rigid commands. Your list persists across sessions so items are still there when you come back.

## Suggested Trigger Words
- "grocery list"
- "shopping list"
- "add to my list"
- "what's on my list"
- "open my grocery list"
- "I need to get groceries"

## Setup
- No API keys needed.
- No external services required — uses the built-in LLM and the file storage API for persistence.

## How It Works
When triggered, it loads your saved grocery list from persistent file storage (`grocery_list.json`). If you're a returning user with items, it greets you with your item count. Each command is sent to the LLM to classify the intent (add, remove, read, clear, or exit) and extract item names from natural speech. After every add, remove, or clear, the list is saved to persistent storage using the delete-then-write pattern. Confirmations are fast ("Added milk.") and list readback always starts with the count ("You've got 6 items: ..."). Clearing the list asks for yes/no confirmation. Say "done" or "stop" to exit.

## Example Conversation
> **User:** "Open my grocery list"
> **AI:** "Welcome back. You have 3 items on your list. Add, remove, read, or clear items. Say done when you're finished."
> **User:** "Add milk and bread"
> **AI:** "Added milk and bread."
> **User:** "What's on my list?"
> **AI:** "You've got 5 items: eggs, butter, cheese, milk, and bread."
> **User:** "Remove the eggs"
> **AI:** "Removed eggs."
> **User:** "I'm done"
> **AI:** "Got it. You have 4 items saved. See you next time."
