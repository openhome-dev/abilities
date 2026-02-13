# Grocery List Manager

## What It Does
A shared household grocery list managed entirely by voice. Add, remove, read, and clear items hands-free — perfect for when your hands are dirty from cooking. Uses the LLM to understand natural speech so you can say "put milk on the list" instead of rigid commands.

## Suggested Trigger Words
- "grocery list"
- "shopping list"
- "add to my list"
- "what's on my list"
- "open my grocery list"
- "I need to get groceries"

## Setup
- No API keys needed.
- No external services required — uses only the built-in LLM and in-memory storage.

## How It Works
When triggered, it opens a voice loop that listens for commands. Each command is sent to the LLM to classify the intent (add, remove, read, clear, or exit) and extract item names from natural speech. Items are stored in a Python list in memory. Confirmations are fast ("Added milk.") and list readback always starts with the count ("You've got 6 items: ..."). Clearing the list asks for yes/no confirmation. Say "done" or "stop" to exit.

## Example Conversation
> **User:** "Open my grocery list"
> **AI:** "Grocery list is open. Add, remove, read, or clear items. Say done when you're finished."
> **User:** "Add milk, eggs, and butter"
> **AI:** "Added milk, eggs and butter."
> **User:** "Put bread on the list"
> **AI:** "Added bread."
> **User:** "What's on my list?"
> **AI:** "You've got 4 items: milk, eggs, butter, and bread."
> **User:** "Remove the eggs"
> **AI:** "Removed eggs."
> **User:** "I'm done"
> **AI:** "Got it. You have 3 items saved. See you next time."
