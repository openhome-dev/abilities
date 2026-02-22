import json
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# RECIPE COACH
# A voice-guided cooking assistant. User names a dish or ingredient,
# the Ability generates a recipe and walks them through it step by step.
#
# Commands during cooking:
#   "next"   → advance to the next step
#   "repeat" → hear the current step again
#   "stop"   → exit at any time
#
# No API keys required — uses the Personality's built-in LLM.
# =============================================================================

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "nevermind", "never mind"}
NEXT_WORDS = {"next", "continue", "go on", "next step", "keep going", "go ahead"}
REPEAT_WORDS = {"repeat", "again", "say that again", "what was that", "one more time"}


class RecipeCoachCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    #{{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    def _user_wants_exit(self, text: str) -> bool:
        lower = text.lower().strip()
        return any(w in lower for w in EXIT_WORDS)

    def _user_wants_next(self, text: str) -> bool:
        lower = text.lower().strip()
        return any(w in lower for w in NEXT_WORDS)

    def _user_wants_repeat(self, text: str) -> bool:
        lower = text.lower().strip()
        return any(w in lower for w in REPEAT_WORDS)

    def _generate_recipe(self, dish: str) -> dict:
        """Use the LLM to generate a structured recipe."""
        prompt = (
            f"Generate a recipe for: {dish}\n\n"
            "Return ONLY valid JSON with this exact structure:\n"
            "{\n"
            '  "title": "Recipe Name",\n'
            '  "servings": "number of servings",\n'
            '  "ingredients": ["ingredient 1", "ingredient 2"],\n'
            '  "steps": ["Step 1 instruction", "Step 2 instruction"]\n'
            "}\n\n"
            "Keep each step to one or two sentences. "
            "Use simple, clear language suitable for reading aloud. "
            "Include quantities in the ingredients list."
        )
        raw = self.capability_worker.text_to_text_response(prompt)
        # Strip markdown fences if present
        clean = raw.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(clean)
        except (json.JSONDecodeError, TypeError):
            return None

    async def run(self):
        try:
            # --- Ask what they want to cook ---
            await self.capability_worker.speak(
                "Hey! I'm your recipe coach. What would you like to cook today?"
            )
            dish_input = await self.capability_worker.user_response()

            if not dish_input or self._user_wants_exit(dish_input):
                await self.capability_worker.speak("No worries. Come back when you're hungry!")
                self.capability_worker.resume_normal_flow()
                return

            # --- Generate the recipe ---
            await self.capability_worker.speak(
                f"Great choice. Let me put together a recipe for {dish_input}."
            )

            recipe = self._generate_recipe(dish_input)

            if not recipe or "steps" not in recipe or "ingredients" not in recipe:
                self.worker.editor_logging_handler.error(
                    f"[RecipeCoach] Failed to parse recipe for: {dish_input}"
                )
                await self.capability_worker.speak(
                    "Sorry, I couldn't put that recipe together. Try asking for a different dish."
                )
                self.capability_worker.resume_normal_flow()
                return

            title = recipe.get("title", dish_input)
            servings = recipe.get("servings", "a few")
            ingredients = recipe["ingredients"]
            steps = recipe["steps"]

            # --- Read ingredients ---
            await self.capability_worker.speak(
                f"Here's what you'll need for {title}, serving {servings}."
            )
            # Group ingredients into chunks of 3-4 for natural voice delivery
            for i in range(0, len(ingredients), 3):
                chunk = ingredients[i:i + 3]
                ingredient_text = ". ".join(chunk) + "."
                await self.capability_worker.speak(ingredient_text)

            # --- Confirm ready to cook ---
            ready = await self.capability_worker.run_confirmation_loop(
                "Got everything? Say yes when you're ready to start cooking."
            )

            if not ready:
                await self.capability_worker.speak(
                    "No problem. The recipe will be here when you're ready. Goodbye!"
                )
                self.capability_worker.resume_normal_flow()
                return

            # --- Walk through steps ---
            await self.capability_worker.speak(
                f"Let's go. {len(steps)} steps total. Say next to move on, "
                "repeat to hear a step again, or stop to exit."
            )

            step_index = 0
            while step_index < len(steps):
                step_num = step_index + 1
                step_text = f"Step {step_num}. {steps[step_index]}"
                await self.capability_worker.speak(step_text)

                # Wait for user command (unless it's the last step)
                if step_index < len(steps) - 1:
                    user_input = await self.capability_worker.user_response()

                    if not user_input:
                        continue

                    if self._user_wants_exit(user_input):
                        await self.capability_worker.speak(
                            f"Stopping at step {step_num}. Good luck with the rest!"
                        )
                        self.capability_worker.resume_normal_flow()
                        return

                    if self._user_wants_repeat(user_input):
                        continue  # Don't increment — repeat same step

                    # "next" or anything else advances
                    step_index += 1
                else:
                    step_index += 1

            # --- Done ---
            await self.capability_worker.speak(
                f"That's it! {title} is done. Enjoy your meal!"
            )

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[RecipeCoach] Error: {e}")
            await self.capability_worker.speak(
                "Something went wrong. Let's try again later."
            )

        self.capability_worker.resume_normal_flow()
