import random

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


class CoinFlipperCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register capability}}

    async def run_coin_logic(self):
        """
        Logic with 'Repeat Last Action' feature:
        1. Remember last action (flip or decide).
        2. Remember last options for decision.
        3. Handle 'Again' commands naturally.
        """

        # Greeting
        await self.capability_worker.speak("I am ready. I can help you pick an option, or just toss a coin.")

        # --- MEMORY VARIABLES ---
        last_mode = None  # Can be 'flip' or 'decide'
        saved_opt1 = None  # To remember option 1
        saved_opt2 = None  # To remember option 2

        while True:
            user_input = ""

            # --- LISTENING BLOCK ---
            try:
                user_input = await self.capability_worker.run_io_loop("What would you like to do?")
            except Exception:
                await self.capability_worker.speak("I did not hear anything. Are you still there?")
                continue

            if not user_input:
                await self.capability_worker.speak("I heard silence. Please say flip, decide, or stop.")
                continue

            text = user_input.lower()

            # --- PHRASE LISTS ---
            exit_phrases = ["stop", "exit", "quit", "bye", "goodbye", "done", "finish", "no thanks"]
            decide_phrases = ["decide", "choice", "choose", "pick", "select", "option"]
            flip_phrases = ["flip", "coin", "toss", "throw", "heads", "tails", "play"]
            repeat_phrases = ["again", "one more time", "repeat", "once more", "another one", "do it again"]

            # --- LOGIC ---

            # 1. EXIT
            if any(word in text for word in exit_phrases):
                await self.capability_worker.speak("Okay. See you later!")
                break

            # 2. REPEAT LOGIC
            elif any(word in text for word in repeat_phrases):
                if last_mode == "flip":
                    text = "flip"
                elif last_mode == "decide":
                    if saved_opt1 and saved_opt2:
                        winner = random.choice([saved_opt1, saved_opt2])
                        await self.capability_worker.speak(f"Choosing again between {saved_opt1} and {saved_opt2}... The winner is {winner}!")
                        continue
                    else:
                        text = "decide"
                else:
                    await self.capability_worker.speak("I haven't done anything yet to repeat.")
                    continue

            # 3. DECISION MODE
            if any(word in text for word in decide_phrases):
                try:
                    prompt1 = "Okay, I will help you decide. Tell me the choices. What is the first option?"
                    opt1 = await self.capability_worker.run_io_loop(prompt1)
                    if not opt1:
                        opt1 = "Option A"

                    opt2 = await self.capability_worker.run_io_loop("And what is the second option?")
                    if not opt2:
                        opt2 = "Option B"

                    saved_opt1 = opt1
                    saved_opt2 = opt2
                    last_mode = "decide"

                    winner = random.choice([opt1, opt2])
                    await self.capability_worker.speak(f"That is hard... But I choose... {winner}!")
                except Exception:
                    await self.capability_worker.speak("Sorry, I had trouble hearing the options. Let's try again.")

            # 4. COIN FLIP MODE
            elif any(word in text for word in flip_phrases):
                last_mode = "flip"
                chance = random.randint(1, 100)
                if chance == 1:
                    await self.capability_worker.speak("Tossing... Oh my god! It landed on its SIDE! That is impossible!")
                else:
                    result = random.choice(["Heads", "Tails"])
                    await self.capability_worker.speak(f"Tossing the coin high in the air... It is {result}!")

            # 5. UNKNOWN PHRASE
            elif not any(word in text for word in repeat_phrases):
                await self.capability_worker.speak("I did not understand. Please say 'flip', 'decide' or 'stop'.")

        self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run_coin_logic())
