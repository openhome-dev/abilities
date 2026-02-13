"""
Grocery List Manager - OpenHome Voice Ability

A voice-controlled shopping list manager that allows users to add, remove,
read, and clear grocery items using natural language commands.

Perfect for hands-free list management while cooking or shopping.
"""

import json
import os

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


class GroceryListManagerCapability(MatchingCapability):
    """Voice-controlled grocery list manager for hands-free operation."""

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    grocery_list: list = []

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        """Register capability with OpenHome platform."""
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        """Entry point when ability is triggered."""
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.grocery_list = []
        self.worker.session_tasks.create(self.run())

    async def run(self):
        """Main execution loop with conversation flow."""
        try:
            await self.capability_worker.speak(
                "Grocery list ready. Say add, remove, read, or clear."
            )

            exit_words = ["stop", "exit", "quit", "done", "cancel", "goodbye"]

            while True:
                user_input = await self.capability_worker.user_response()

                if not user_input or user_input.strip() == "":
                    await self.capability_worker.speak("I didn't catch that.")
                    continue

                user_input_lower = user_input.lower()

                if any(word in user_input_lower for word in exit_words):
                    await self.capability_worker.speak("List saved. Goodbye!")
                    break

                intent = self._classify_intent(user_input)

                if intent == "add":
                    await self._add_items(user_input)
                elif intent == "remove":
                    await self._remove_items(user_input)
                elif intent == "read":
                    await self._read_list()
                elif intent == "clear":
                    await self._clear_list()
                else:
                    await self.capability_worker.speak(
                        "Say add, remove, read, or clear."
                    )

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"Grocery list error: {str(e)}"
            )
            await self.capability_worker.speak("Something went wrong. Exiting.")

        finally:
            self.capability_worker.resume_normal_flow()

    def _classify_intent(self, user_input: str) -> str:
        """
        Use LLM to classify user intent from natural language.

        Args:
            user_input: Raw user speech input

        Returns:
            One of: add, remove, read, clear, unknown
        """
        intent_prompt = f"""User said: "{user_input}"

Classify the intent. Reply with ONLY ONE WORD:

add - if adding items (e.g., "add milk", "put eggs on the list")
remove - if removing items (e.g., "remove milk", "delete eggs")
read - if reading the list (e.g., "what's on my list", "read list")
clear - if clearing all items (e.g., "clear list", "delete everything")
unknown - if unclear

Reply with ONE WORD ONLY:"""

        intent = self.capability_worker.text_to_text_response(
            intent_prompt
        ).strip().lower()

        valid_intents = ["add", "remove", "read", "clear"]
        return intent if intent in valid_intents else "unknown"

    async def _add_items(self, user_input: str):
        """Extract and add items to the grocery list."""
        extract_prompt = f"""Extract grocery item names from: "{user_input}"

Return ONLY a comma-separated list of item names.
Examples:
- "add milk and eggs" → milk, eggs
- "put bread on the list" → bread
- "I need butter, cheese, and yogurt" → butter, cheese, yogurt

Items only, no extra words:"""

        items_text = self.capability_worker.text_to_text_response(
            extract_prompt
        ).strip()

        items = [
            item.strip()
            for item in items_text.split(",")
            if item.strip() and len(item.strip()) > 0
        ]

        if not items:
            await self.capability_worker.speak("I couldn't find any items.")
            return

        self.grocery_list.extend(items)

        if len(items) == 1:
            await self.capability_worker.speak(f"Added {items[0]}.")
        else:
            await self.capability_worker.speak(f"Added {len(items)} items.")

    async def _remove_items(self, user_input: str):
        """Extract and remove items from the grocery list."""
        extract_prompt = f"""Extract grocery item names from: "{user_input}"

Return ONLY a comma-separated list of item names.
Items only, no extra words:"""

        items_text = self.capability_worker.text_to_text_response(
            extract_prompt
        ).strip()

        items = [
            item.strip()
            for item in items_text.split(",")
            if item.strip()
        ]

        if not items:
            await self.capability_worker.speak("I couldn't find any items.")
            return

        removed_items = []

        for item in items:
            if item in self.grocery_list:
                self.grocery_list.remove(item)
                removed_items.append(item)

        if removed_items:
            if len(removed_items) == 1:
                await self.capability_worker.speak(
                    f"Removed {removed_items[0]}."
                )
            else:
                await self.capability_worker.speak(
                    f"Removed {len(removed_items)} items."
                )
        else:
            await self.capability_worker.speak("Item not found.")

    async def _read_list(self):
        """Read the current grocery list aloud."""
        if not self.grocery_list:
            await self.capability_worker.speak("Your list is empty.")
            return

        count = len(self.grocery_list)

        if count == 1:
            await self.capability_worker.speak(
                f"You have one item: {self.grocery_list[0]}."
            )
        elif count <= 5:
            items_text = ", ".join(self.grocery_list)
            await self.capability_worker.speak(
                f"You have {count} items: {items_text}."
            )
        else:
            first_three = ", ".join(self.grocery_list[:3])
            await self.capability_worker.speak(
                f"You have {count} items. First three: {first_three}."
            )

    async def _clear_list(self):
        """Clear all items from the grocery list."""
        if not self.grocery_list:
            await self.capability_worker.speak("List is already empty.")
            return

        count = len(self.grocery_list)
        self.grocery_list = []

        await self.capability_worker.speak(f"Cleared {count} items.")
