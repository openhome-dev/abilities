import json
import os

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# GROCERY LIST MANAGER
# A shared household grocery list managed entirely by voice. Add, remove,
# read, and clear items hands-free — perfect when your hands are dirty
# from cooking. Uses the LLM to extract item names from natural speech
# so users can say "put milk on the list" instead of exact commands.
# =============================================================================

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave",
    "nothing else", "all good", "nope", "no thanks",
    "i'm good", "that's all", "all done", "finished",
}

# Namespaced filename to avoid collisions with other abilities
STORAGE_FILE = "grocery_list.json"

INTENT_SYSTEM_PROMPT = (
    "You are a grocery list intent classifier. Given user input, determine the "
    "intent and extract grocery item names. Return ONLY valid JSON, no other text."
)

INTENT_PROMPT = """Classify this grocery list command. Return ONLY JSON in this exact format:
{{"intent": "<intent>", "items": ["<item1>", "<item2>"]}}

Possible intents:
- "add" — user wants to add items (e.g. "add milk", "put eggs on the list", "I need butter and bread", "don't forget the cheese")
- "remove" — user wants to remove items (e.g. "remove the eggs", "take off milk", "delete bread", "I already got the butter")
- "read" — user wants to hear the list (e.g. "what's on my list", "read the list", "what do I need", "read it back")
- "clear" — user wants to clear the entire list (e.g. "clear the list", "empty the list", "start over", "wipe it clean")
- "exit" — user wants to stop or leave (e.g. "stop", "I'm done", "exit", "quit", "bye", "that's all", "goodbye", "leave", "cancel", "finished", "no more", "all done", "close the list", "never mind")
- "unknown" — not a grocery list command

Rules:
- For "add" and "remove", extract item names into "items" as a list of lowercase strings.
- For "read", "clear", "exit", and "unknown", set "items" to an empty list.
- Normalize items to their simple form: "some eggs" becomes "eggs", "a gallon of milk" becomes "milk", "organic bananas" becomes "bananas".
- Split multiple items: "eggs and butter" becomes ["eggs", "butter"]. "eggs, butter, and milk" becomes ["eggs", "butter", "milk"].

User said: "{input}"
"""


class GroceryManagerCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    grocery_list: list = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.grocery_list = []
        self.worker.session_tasks.create(self.run())

    def classify_intent(self, user_input: str) -> dict:
        """Use the LLM to classify intent and extract item names from natural speech."""
        prompt = INTENT_PROMPT.format(input=user_input)
        raw = self.capability_worker.text_to_text_response(
            prompt, system_prompt=INTENT_SYSTEM_PROMPT
        )
        clean = raw.replace("```json", "").replace("```", "").strip()
        try:
            result = json.loads(clean)
            if "intent" not in result:
                result["intent"] = "unknown"
            if "items" not in result:
                result["items"] = []
            return result
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[GroceryList] Failed to parse intent: {e} | Raw: {raw}"
            )
            return {"intent": "unknown", "items": []}

    async def load_list(self):
        """Load grocery list from persistent storage, or start empty."""
        try:
            if await self.capability_worker.check_if_file_exists(STORAGE_FILE, False):
                raw = await self.capability_worker.read_file(STORAGE_FILE, False)
                self.grocery_list = json.loads(raw)
                self.worker.editor_logging_handler.info(
                    f"[GroceryList] Loaded {len(self.grocery_list)} items from storage"
                )
            else:
                self.grocery_list = []
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[GroceryList] Failed to load list: {e}"
            )
            self.grocery_list = []

    async def save_list(self):
        """Persist grocery list to file. Delete first since write_file appends."""
        try:
            await self.capability_worker.delete_file(STORAGE_FILE, False)
            await self.capability_worker.write_file(
                STORAGE_FILE, json.dumps(self.grocery_list), False
            )
            self.worker.editor_logging_handler.info(
                f"[GroceryList] Saved {len(self.grocery_list)} items to storage"
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[GroceryList] Failed to save list: {e}"
            )

    def format_list_response(self) -> str:
        """Format the grocery list for voice output. Count first, then items."""
        if not self.grocery_list:
            return "Your grocery list is empty."

        count = len(self.grocery_list)

        if count == 1:
            return f"You have one item: {self.grocery_list[0]}."

        # Join items with commas and "and" before the last one
        items_str = ", ".join(self.grocery_list[:-1]) + f", and {self.grocery_list[-1]}"
        return f"You've got {count} items: {items_str}."

    def add_items(self, items: list) -> str:
        """Add items to the list, skip duplicates. Return a fast voice confirmation."""
        added = []
        skipped = []

        for item in items:
            item = item.strip().lower()
            if not item:
                continue
            if item in self.grocery_list:
                skipped.append(item)
            else:
                self.grocery_list.append(item)
                added.append(item)

        parts = []
        if added:
            if len(added) == 1:
                parts.append(f"Added {added[0]}.")
            else:
                items_str = ", ".join(added[:-1]) + f" and {added[-1]}"
                parts.append(f"Added {items_str}.")
        if skipped:
            if len(skipped) == 1:
                parts.append(f"{skipped[0].capitalize()} is already on your list.")
            else:
                items_str = ", ".join(skipped[:-1]) + f" and {skipped[-1]}"
                parts.append(f"{items_str} are already on your list.")

        return " ".join(parts) if parts else "I didn't catch any items to add."

    def remove_items(self, items: list) -> str:
        """Remove items from the list. Return a fast voice confirmation."""
        removed = []
        not_found = []

        for item in items:
            item = item.strip().lower()
            if not item:
                continue
            if item in self.grocery_list:
                self.grocery_list.remove(item)
                removed.append(item)
            else:
                not_found.append(item)

        parts = []
        if removed:
            if len(removed) == 1:
                parts.append(f"Removed {removed[0]}.")
            else:
                items_str = ", ".join(removed[:-1]) + f" and {removed[-1]}"
                parts.append(f"Removed {items_str}.")
        if not_found:
            if len(not_found) == 1:
                parts.append(f"{not_found[0].capitalize()} wasn't on the list.")
            else:
                items_str = ", ".join(not_found[:-1]) + f" and {not_found[-1]}"
                parts.append(f"{items_str} weren't on the list.")

        return " ".join(parts) if parts else "I didn't catch any items to remove."

    async def run(self):
        # Load saved list from persistent storage
        await self.load_list()

        # Greet based on whether we have a saved list
        if self.grocery_list:
            count = len(self.grocery_list)
            await self.capability_worker.speak(
                f"Welcome back. You have {count} items on your list. "
                "Add, remove, read, or clear items. Say done when you're finished."
            )
        else:
            await self.capability_worker.speak(
                "Grocery list is open. Add, remove, read, or clear items. "
                "Say done when you're finished."
            )

        idle_count = 0

        while True:
            try:
                user_input = await self.capability_worker.user_response()

                if not user_input:
                    idle_count += 1
                    if idle_count >= 2:
                        await self.capability_worker.speak(
                            "Still here if you need anything. Otherwise I'll close the list."
                        )
                        follow_up = await self.capability_worker.user_response()
                        if not follow_up or any(
                            w in (follow_up or "").lower() for w in EXIT_WORDS
                        ):
                            count = len(self.grocery_list)
                            if count > 0:
                                await self.capability_worker.speak(
                                    f"Got it. You have {count} items saved. See you next time."
                                )
                            else:
                                await self.capability_worker.speak(
                                    "Got it. See you next time."
                                )
                            break
                        else:
                            user_input = follow_up
                            idle_count = 0
                    else:
                        continue

                # Reset idle counter on valid input
                idle_count = 0

                # Quick exit check using substring matching (avoids LLM call)
                lower_input = user_input.lower().strip()
                if any(w in lower_input for w in EXIT_WORDS):
                    count = len(self.grocery_list)
                    if count > 0:
                        await self.capability_worker.speak(
                            f"Got it. You have {count} items saved. See you next time."
                        )
                    else:
                        await self.capability_worker.speak("Got it. See you next time.")
                    break

                # Use LLM to classify intent and extract items
                result = self.classify_intent(user_input)
                intent = result.get("intent", "unknown")
                items = result.get("items", [])

                self.worker.editor_logging_handler.info(
                    f"[GroceryList] Intent: {intent}, Items: {items}"
                )

                if intent == "add":
                    if not items:
                        await self.capability_worker.speak(
                            "What would you like to add?"
                        )
                        continue
                    response = self.add_items(items)
                    await self.save_list()
                    await self.capability_worker.speak(response)

                elif intent == "remove":
                    if not items:
                        await self.capability_worker.speak(
                            "What would you like to remove?"
                        )
                        continue
                    response = self.remove_items(items)
                    await self.save_list()
                    await self.capability_worker.speak(response)

                elif intent == "read":
                    response = self.format_list_response()
                    await self.capability_worker.speak(response)

                elif intent == "clear":
                    if not self.grocery_list:
                        await self.capability_worker.speak(
                            "The list is already empty."
                        )
                    else:
                        confirmed = await self.capability_worker.run_confirmation_loop(
                            f"Clear all {len(self.grocery_list)} items from your list?"
                        )
                        if confirmed:
                            self.grocery_list.clear()
                            await self.save_list()
                            await self.capability_worker.speak("List cleared.")
                        else:
                            await self.capability_worker.speak(
                                "Okay, keeping your list."
                            )

                elif intent == "exit":
                    count = len(self.grocery_list)
                    if count > 0:
                        await self.capability_worker.speak(
                            f"Got it. You have {count} items saved. See you next time."
                        )
                    else:
                        await self.capability_worker.speak("Got it. See you next time.")
                    break

                else:
                    await self.capability_worker.speak(
                        "I can add, remove, read, or clear your grocery list. "
                        "What would you like to do?"
                    )

            except Exception as e:
                self.worker.editor_logging_handler.error(
                    f"[GroceryList] Error: {e}"
                )
                await self.capability_worker.speak(
                    "Something went wrong. Let's try that again."
                )
                continue

        self.capability_worker.resume_normal_flow()
