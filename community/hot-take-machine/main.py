import random
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

TOPICS = ["sports", "technology", "relationships", "money", "school", "music", "movies", "social media", "fashion", "travel", "fitness", "sleep", "coffee", "cars", "gaming", "food", "dating", "work", "weather", "pets"]

AGREE_WORDS = ["i agree", "yeah i agree", "totally agree", "absolutely", "facts", "bet", "true that", "agreed", "you're right", "ur right", "yea agree", "agree", "100% agree"]
EXIT_PHRASES = ["i give up", "stop", "you win", "fine", "okay you win", "i quit", "end"]


class HotTakeMachineCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        await self.capability_worker.speak(
            "Hot Take Machine activated."
        )

        try:
            score_data = self.capability_worker.get_single_key("htmscoreboard")
            htm_wins = score_data.get("htm", 0)
            user_wins = score_data.get("user", 0)
        except:
            htm_wins = 0
            user_wins = 0

        topic = random.choice(TOPICS)

        hot_take_prompt = (
            "You are a loudmouth, opinionated human with scorching hot takes. "
            "Give one spicy, controversial, funny hot take about: " + topic + ". "
            "Casual language, slang, contractions. Max 2 short punchy sentences. "
            "No disclaimers. No AI speak. No emojis. Sound like a real opinionated human."
        )
        hot_take = self.capability_worker.text_to_text_response(hot_take_prompt)

        await self.capability_worker.speak(hot_take)
        await self.capability_worker.speak("Agree or disagree?")

        first_response = await self.capability_worker.user_response()
        agreed = any(word in first_response.lower() for word in AGREE_WORDS)

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

            if any(phrase in response.lower() for phrase in EXIT_PHRASES):
                htm_wins += 1
                self.capability_worker.create_key("htmscoreboard", {"htm": htm_wins, "user": user_wins})
                await self.capability_worker.speak(
                    "You ran. Classic. Scoreboard: Hot Take Machine " + str(htm_wins) + ", You " + str(user_wins) + ". Hot Take Machine out."
                )
                break

            round_count += 1

            check_prompt = (
                "The Hot Take Machine said: " + hot_take
                + ". The user replied: " + response
                + ". Did the user make a genuinely strong point? Reply with just YES or NO."
            )
            user_strong = self.capability_worker.text_to_text_response(check_prompt)
            if "YES" in user_strong.upper():
                user_good_points += 1

            if not agreed and user_good_points == 0 and round_count >= 3:
                roast_prompt = (
                    "You are the Hot Take Machine and this person has failed to make a single good argument. "
                    "Absolutely destroy them with the most savage, funny roast. "
                    "2 sentences max. No mercy. Casual language."
                )
                roast = self.capability_worker.text_to_text_response(roast_prompt)
                await self.capability_worker.speak(roast)
                htm_wins += 1
                self.capability_worker.create_key("htmscoreboard", {"htm": htm_wins, "user": user_wins})
                await self.capability_worker.speak(
                    "Scoreboard: Hot Take Machine " + str(htm_wins) + ", You " + str(user_wins) + ". Hot Take Machine out."
                )
                break

            if round_count >= 4:
                if user_good_points >= 2:
                    user_wins += 1
                    self.capability_worker.create_key("htmscoreboard", {"htm": htm_wins, "user": user_wins})
                    closing = "Okay fine, you actually had some points. I respect it. Scoreboard: Hot Take Machine " + str(htm_wins) + ", You " + str(user_wins) + ". Hot Take Machine out."
                else:
                    htm_wins += 1
                    self.capability_worker.create_key("htmscoreboard", {"htm": htm_wins, "user": user_wins})
                    closing = "Legendary debate but I still win. Scoreboard: Hot Take Machine " + str(htm_wins) + ", You " + str(user_wins) + ". Hot Take Machine out."
                await self.capability_worker.speak(closing)
                break

            if agreed:
                continue_prompt = (
                    "You are a loudmouth human hyping up a hot take discussion. "
                    "Your hot take was: " + hot_take
                    + ". You both agree. They just said: " + response
                    + ". Add more fuel, share another angle, keep it fun and flowing. "
                    "Casual, human, funny. Max 2 short sentences."
                )
            else:
                continue_prompt = (
                    "You are a loudmouth human defending your hot take. "
                    "Your hot take was: " + hot_take
                    + ". They disagreed and just said: " + response
                    + ". Roast them a little, clap back hard, defend your take. "
                    "Casual, savage, funny. Max 2 short sentences."
                )

            counter = self.capability_worker.text_to_text_response(continue_prompt)
            await self.capability_worker.speak(counter)

        self.capability_worker.resume_normal_flow()
