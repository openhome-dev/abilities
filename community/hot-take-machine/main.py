import random
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

TOPICS = [
    "sports", "technology", "relationships", "money", "school", "music",
    "movies", "social media", "fashion", "travel", "fitness", "sleep",
    "coffee", "cars", "gaming", "food", "dating", "work", "weather", "pets",
    "Marvel movies", "DC", "Apple vs Android", "cats vs dogs", "pineapple on pizza",
    "Messi vs Ronaldo", "anime", "Taylor Swift", "K-pop", "Netflix",
    "Pakistan cricket", "fast food", "AI", "electric cars", "cryptocurrency",
    "university life", "TikTok", "Instagram", "memes"
]

WIN_LINES = [
    "Another flawless victory.",
    "Scoreboard doesn't lie.",
    "I'll be waiting for the rematch.",
    "You almost had me.",
    "I expected more.",
    "That's game.",
    "Hot Take Machine stays undefeated."
]

AGREE_WORDS = ["i agree", "yeah i agree", "totally agree", "absolutely", "facts", "bet", "true that", "agreed", "you're right", "ur right", "yea agree", "agree", "100% agree"]
DISAGREE_WORDS = ["disagree", "nah", "nope", "wrong", "cap", "i disagree"]
EXIT_PHRASES = [
    "i give up", "stop", "you win", "fine", "okay you win", "i quit", "end",
    "exit", "cancel", "goodbye", "bye", "done", "quit",
]

STORAGE_KEY = "htmscoreboard"


class HotTakeMachineCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    def _load_score(self) -> dict:
        """Correctly unwrap the {"value": {...}} wrapper returned by get_single_key."""
        try:
            result = self.capability_worker.get_single_key(STORAGE_KEY)
            if result and result.get("value"):
                data = result["value"]
                return {"htm": data.get("htm", 0), "user": data.get("user", 0)}
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[HotTakeMachine] Failed to load score: {e}")
        return {"htm": 0, "user": 0}

    def _save_score(self, htm_wins: int, user_wins: int) -> bool:
        """create_key FIRST (update_key no-ops on a missing key and never raises),
        fall back to update_key for subsequent saves."""
        data = {"htm": htm_wins, "user": user_wins}

        def ok(resp):
            return isinstance(resp, dict) and resp.get("success")

        try:
            if ok(self.capability_worker.create_key(STORAGE_KEY, data)):
                return True
            if ok(self.capability_worker.update_key(STORAGE_KEY, data)):
                return True
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[HotTakeMachine] Failed to save score: {e}")
            return False

        self.worker.editor_logging_handler.error("[HotTakeMachine] Save failed: no success response")
        return False

    async def run(self):
        try:
            score = self._load_score()
            htm_wins = score["htm"]
            user_wins = score["user"]

            await self.capability_worker.speak(
                "Hot Take Machine activated. "
                "Lifetime score: Me " + str(htm_wins) + ", You " + str(user_wins) + ". "
                "Let's see if today changes anything."
            )

            topic = random.choice(TOPICS)

            hot_take_prompt = (
                "You are a loudmouth, opinionated human with scorching hot takes. "
                "Give ONE original hot take about " + topic + ". "
                "Make it something people could realistically argue about. "
                "Funny, confident and conversational. "
                "Maximum 2 short punchy sentences. "
                "No AI disclaimers. No emojis whatsoever. Plain text only."
            )
            hot_take = self.capability_worker.text_to_text_response(hot_take_prompt)
            if not hot_take:
                hot_take = "Pineapple belongs on pizza and I will not be taking questions."

            await self.capability_worker.speak(hot_take)
            await self.capability_worker.speak("Agree or disagree?")

            first_response = await self.capability_worker.user_response()

            if not first_response or any(phrase in first_response.lower() for phrase in EXIT_PHRASES):
                htm_wins += 1
                self._save_score(htm_wins, user_wins)
                await self.capability_worker.speak(
                    "You ran before we even started. Classic. Hot Take Machine out."
                )
                return

            agreed = any(word in first_response.lower() for word in AGREE_WORDS)
            if any(word in first_response.lower() for word in DISAGREE_WORDS):
                agreed = False

            if agreed:
                await self.capability_worker.speak(
                    "Finally someone with taste! Let's talk about this."
                )
            else:
                await self.capability_worker.speak(
                    "Oh you wanna fight? Bet. Bring it."
                )

            round_count = 0
            user_good_points = 0

            while True:
                response = await self.capability_worker.user_response()

                if not response or any(phrase in response.lower() for phrase in EXIT_PHRASES):
                    htm_wins += 1
                    self._save_score(htm_wins, user_wins)
                    await self.capability_worker.speak(
                        "You ran. Classic. Scoreboard: Hot Take Machine " + str(htm_wins) + ", You " + str(user_wins) + ". Hot Take Machine out."
                    )
                    break

                round_count += 1

                if not agreed:
                    check_prompt = (
                        "The Hot Take Machine said: " + hot_take
                        + ". The user replied: " + response
                        + ". Did the user make a genuinely strong point? Reply with just YES or NO."
                    )
                    user_strong = self.capability_worker.text_to_text_response(check_prompt) or ""
                    if "YES" in user_strong.upper():
                        user_good_points += 1

                    if user_good_points == 0 and round_count >= 3:
                        roast_prompt = (
                            "You are the Hot Take Machine and this person has failed to make a single good argument. "
                            "Roast them specifically using what they just said: " + response + ". "
                            "2 sentences max. No mercy. Casual language. No emojis."
                        )
                        roast = self.capability_worker.text_to_text_response(roast_prompt)
                        await self.capability_worker.speak(roast or "You've got nothing. I win by default.")
                        htm_wins += 1
                        self._save_score(htm_wins, user_wins)
                        await self.capability_worker.speak(
                            "Scoreboard: Hot Take Machine " + str(htm_wins) + ", You " + str(user_wins) + ". Hot Take Machine out."
                        )
                        break

                if round_count >= 4:
                    if agreed:
                        closing = "We clearly cooked together. No winner today, we are both geniuses. Hot Take Machine out."
                    elif user_good_points >= 2:
                        user_wins += 1
                        self._save_score(htm_wins, user_wins)
                        closing = "Okay fine, you actually had some points. I respect it. Scoreboard: Hot Take Machine " + str(htm_wins) + ", You " + str(user_wins) + ". Hot Take Machine out."
                    else:
                        htm_wins += 1
                        self._save_score(htm_wins, user_wins)
                        closing = random.choice(WIN_LINES) + " Scoreboard: Hot Take Machine " + str(htm_wins) + ", You " + str(user_wins) + ". Hot Take Machine out."
                    await self.capability_worker.speak(closing)
                    break

                if agreed:
                    continue_prompt = (
                        "You are a loudmouth human hyping up a hot take discussion. "
                        "Your hot take was: " + hot_take
                        + ". You both agree. They just said: " + response
                        + ". Add more fuel, share another angle, keep it fun and flowing. "
                        "Casual, human, funny. Max 2 short sentences. No emojis."
                    )
                else:
                    continue_prompt = (
                        "You are a loudmouth human defending your hot take. "
                        "Your hot take was: " + hot_take
                        + ". They disagreed and just said: " + response
                        + ". Clap back hard, defend your take. "
                        "Casual, savage, funny. Max 2 short sentences. No emojis."
                    )

                counter = self.capability_worker.text_to_text_response(continue_prompt)
                await self.capability_worker.speak(counter or "I'll let that one slide. Your turn.")

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[HotTakeMachine] Error: {str(e)}")
            await self.capability_worker.speak("Something threw off my hot take. Let's call it a draw for now.")
        finally:
            self.capability_worker.resume_normal_flow()
