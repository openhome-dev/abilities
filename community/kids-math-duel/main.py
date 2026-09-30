import asyncio
import random
import re

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

STORAGE_KEY = "kids_math_duel_leaderboard"
TOTAL_QUESTIONS = 10
TIMER_SECONDS = 8

EXIT_WORDS = {"stop", "quit", "exit", "end", "bye", "goodbye", "cancel"}
EXIT_PHRASES = {"that's all", "all done", "never mind", "i'm done", "no thanks"}

DIFFICULTY_CONFIG = {
    "easy":   {"ops": ["+", "-"],                       "max_a": 20, "max_b": 20},
    "medium": {"ops": ["+", "-", "times"],              "max_a": 12, "max_b": 12},
    "hard":   {"ops": ["+", "-", "times", "divided"],   "max_a": 50, "max_b": 12},
}

DIFFICULTY_ALIASES = {
    "easy": "easy", "simple": "easy", "beginner": "easy",
    "medium": "medium", "normal": "medium", "middle": "medium",
    "hard": "hard", "difficult": "hard", "advanced": "hard", "expert": "hard",
}

HOTWORDS = {
    "math duel", "maths duel", "math game", "math challenge",
    "math battle", "times tables game", "let's play math",
    "math quiz", "maths quiz", "number duel",
}


class KidsMathDuel(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    _answered: bool = False
    _timed_out: bool = False
    _timer_epoch: int = 0
    _current_opponent: str = ""
    _exit_requested: bool = False

    def does_match(self, text: str) -> bool:
        t = text.lower()
        return any(hw in t for hw in HOTWORDS)

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self._run())

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    async def _run(self):
        try:
            trigger = (await self.capability_worker.wait_for_complete_transcription() or "").strip()
            if self._is_exit(trigger):
                await self.capability_worker.speak("No problem, see you next time!")
                return

            await self.capability_worker.speak(
                "Math Duel! Two players, ten questions, winner takes all. Let's set it up."
            )

            p1 = await self._collect_player_name(1)
            if p1 is None:
                return

            p2 = await self._collect_player_name(2)
            if p2 is None:
                return

            difficulty = await self._choose_difficulty()
            if difficulty is None:
                return

            await self.capability_worker.speak(
                f"Alright — {p1} versus {p2}, {difficulty} difficulty. "
                f"Ten questions, five each. You have {TIMER_SECONDS} seconds per question. Here we go!"
            )

            while True:
                scores, best_streaks = await self._run_game(p1, p2, difficulty)
                if self._exit_requested:
                    await self.capability_worker.speak("Okay, bye!")
                    return
                await self._announce_result(p1, p2, scores, best_streaks, difficulty)
                self._update_leaderboard(p1, scores[p1], best_streaks[p1])
                self._update_leaderboard(p2, scores[p2], best_streaks[p2])

                play_again = await self.capability_worker.run_confirmation_loop("Want to play again?")
                if not play_again:
                    await self.capability_worker.speak("Great game! See you next time.")
                    break

                difficulty = await self._choose_difficulty()
                if difficulty is None:
                    break

                await self.capability_worker.speak(
                    f"Round two — {p1} versus {p2}, {difficulty}. Let's go!"
                )

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[KidsMathDuel] Error: {e}")
        finally:
            self.capability_worker.resume_normal_flow()

    # ------------------------------------------------------------------
    # Setup — names and difficulty
    # ------------------------------------------------------------------

    async def _collect_player_name(self, player_num: int) -> str | None:
        label = "one" if player_num == 1 else "two"
        default = f"Player {player_num}"

        for _ in range(3):
            await self.capability_worker.speak(f"What's player {label}'s name?")
            raw = (await self.capability_worker.user_response() or "").strip()

            if self._is_exit(raw):
                await self.capability_worker.speak("Okay, bye!")
                return None

            name = raw.split()[0].capitalize() if raw else ""
            if not name:
                await self.capability_worker.speak("I didn't catch that. Try again.")
                continue

            confirmed = await self.capability_worker.run_confirmation_loop(
                f"Player {label} is {name}, right?"
            )
            if confirmed:
                return name

        return default

    async def _choose_difficulty(self) -> str | None:
        await self.capability_worker.speak("Easy, medium, or hard?")

        for attempt in range(3):
            raw = (await self.capability_worker.user_response() or "").lower().strip()

            if self._is_exit(raw):
                await self.capability_worker.speak("Okay, bye!")
                return None

            for word, level in DIFFICULTY_ALIASES.items():
                if word in raw:
                    return level

            if attempt < 2:
                await self.capability_worker.speak("Say easy, medium, or hard.")

        return "easy"

    # ------------------------------------------------------------------
    # Game loop
    # ------------------------------------------------------------------

    async def _run_game(self, p1: str, p2: str, difficulty: str) -> tuple:
        players = [p1, p2]
        scores = {p1: 0, p2: 0}
        streaks = {p1: 0, p2: 0}
        best_streaks = {p1: 0, p2: 0}

        for q_num in range(TOTAL_QUESTIONS):
            player = players[q_num % 2]
            opponent = players[(q_num + 1) % 2]
            question, correct = self._generate_question(difficulty)

            got_it = await self._ask_with_timer(player, question, correct, opponent)
            if self._exit_requested:
                break

            if got_it:
                scores[player] += 1
                streaks[player] += 1
                streaks[opponent] = 0
                best_streaks[player] = max(best_streaks[player], streaks[player])

                streak_msg = f" {streaks[player]} in a row!" if streaks[player] > 1 else ""
                await self.capability_worker.speak(
                    f"Correct!{streak_msg} Score: {p1} {scores[p1]}, {p2} {scores[p2]}."
                )
            else:
                streaks[player] = 0
                await self.capability_worker.speak(f"{opponent} — steal it! {question}")
                steal_input = (await self.capability_worker.user_response() or "").strip()
                if self._is_exit(steal_input):
                    self._exit_requested = True
                    break

                if self._check_answer(steal_input, correct):
                    scores[opponent] += 1
                    streaks[opponent] += 1
                    best_streaks[opponent] = max(best_streaks[opponent], streaks[opponent])
                    await self.capability_worker.speak(
                        f"Steal! {opponent} grabs the point. "
                        f"Score: {p1} {scores[p1]}, {p2} {scores[p2]}."
                    )
                else:
                    streaks[opponent] = 0
                    await self.capability_worker.speak(
                        f"No steal. The answer was {correct}. "
                        f"Score: {p1} {scores[p1]}, {p2} {scores[p2]}."
                    )

        return scores, best_streaks

    # ------------------------------------------------------------------
    # Per-question ask with soft countdown timer
    # ------------------------------------------------------------------

    async def _ask_with_timer(self, player: str, question: str, correct: int, opponent: str = "") -> bool:
        self._answered = False
        self._timed_out = False
        self._current_opponent = opponent
        self._timer_epoch += 1
        epoch = self._timer_epoch

        await self.capability_worker.speak(f"{player} — {question}")

        # Race the listen against the timer rather than awaiting it alone - a
        # silent player used to leave this call (and the whole ability) hanging
        # forever, since "Time's up!" spoke but nothing ever unblocked the
        # listen. Whichever finishes first wins; the other is cancelled.
        listen_task = self.worker.session_tasks.create(self.capability_worker.user_response())
        timer_task = self.worker.session_tasks.create(self._countdown(TIMER_SECONDS, epoch))
        done, _ = await asyncio.wait(
            {listen_task, timer_task}, return_when=asyncio.FIRST_COMPLETED
        )
        self._answered = True

        if listen_task in done:
            timer_task.cancel()
            user_input = (listen_task.result() or "").strip()
            if self._is_exit(user_input):
                self._exit_requested = True
                return False
            return self._check_answer(user_input, correct)

        # Timer fired first - let "Time's up!" finish, then hand off.
        await timer_task
        listen_task.cancel()
        return False

    async def _countdown(self, seconds: int, epoch: int):
        await self.worker.session_tasks.sleep(float(seconds))
        if epoch == self._timer_epoch and not self._answered:
            self._timed_out = True
            handoff = f"{self._current_opponent} — steal it!" if self._current_opponent else "Next player!"
            await self.capability_worker.speak(f"Time's up! {handoff}")

    # ------------------------------------------------------------------
    # End of game
    # ------------------------------------------------------------------

    async def _announce_result(
        self,
        p1: str,
        p2: str,
        scores: dict,
        best_streaks: dict,
        difficulty: str,
    ):
        s1, s2 = scores[p1], scores[p2]

        if s1 > s2:
            result_line = f"{p1} wins {s1} to {s2}"
        elif s2 > s1:
            result_line = f"{p2} wins {s2} to {s1}"
        else:
            result_line = f"It's a tie — {s1} all"

        await self.capability_worker.speak(f"Game over! {result_line}!")

        debrief = (self.capability_worker.text_to_text_response(
            f"Math Duel result: {p1} scored {s1}, {p2} scored {s2}. "
            f"{p1} best streak: {best_streaks[p1]}. {p2} best streak: {best_streaks[p2]}. "
            f"Difficulty: {difficulty}. "
            "Write a fun, energetic 2-sentence summary for kids. Celebrate the winner or the tie. "
            "Add one funny or encouraging observation. First names only. No markdown. Under 40 words."
        ) or "").strip()

        if debrief:
            await self.capability_worker.speak(debrief)

    # ------------------------------------------------------------------
    # Math question generator — pure Python, no LLM, no API
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_question(difficulty: str) -> tuple:
        cfg = DIFFICULTY_CONFIG[difficulty]
        op = random.choice(cfg["ops"])
        max_a, max_b = cfg["max_a"], cfg["max_b"]

        if op == "+":
            a = random.randint(1, max_a)
            b = random.randint(1, max_b)
            return f"What is {a} plus {b}?", a + b

        if op == "-":
            a = random.randint(2, max_a)
            b = random.randint(1, a)  # no negatives
            return f"What is {a} minus {b}?", a - b

        if op == "times":
            a = random.randint(2, min(12, max_a))
            b = random.randint(2, min(12, max_b))
            return f"What is {a} times {b}?", a * b

        # divided — guaranteed whole-number result
        b = random.randint(2, 10)
        ans = random.randint(2, 10)
        return f"What is {b * ans} divided by {b}?", ans

    # ------------------------------------------------------------------
    # Answer checker — regex first, LLM fallback for word numbers
    # ------------------------------------------------------------------

    def _check_answer(self, user_input: str, correct: int) -> bool:
        if not user_input:
            return False

        m = re.search(r'\b(\d+)\b', user_input)
        if m:
            return int(m.group(1)) == correct

        # LLM fallback for spoken word numbers ("fourteen", "forty two")
        extracted = (self.capability_worker.text_to_text_response(
            f"The user said: '{user_input}'. "
            "What number did they say? Reply with ONLY the digits. If no number, reply 0."
        ) or "0").strip()
        try:
            return int(re.sub(r'\D', '', extracted) or "0") == correct
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # Leaderboard — get_single_key / create_key / update_key (sync)
    # ------------------------------------------------------------------

    def _update_leaderboard(self, name: str, score: int, best_streak: int):
        try:
            raw = self.capability_worker.get_single_key(STORAGE_KEY)
            data = raw.get("value", raw) if raw else {}
        except Exception:
            data = {}

        if not isinstance(data, dict):
            data = {}

        entry = data.get(name, {"best_score": 0, "best_streak": 0, "games_played": 0})
        entry["games_played"] = entry.get("games_played", 0) + 1
        entry["best_score"] = max(entry.get("best_score", 0), score)
        entry["best_streak"] = max(entry.get("best_streak", 0), best_streak)
        data[name] = entry

        try:
            result = self.capability_worker.create_key(STORAGE_KEY, data)
            if not (result or {}).get("success"):
                self.capability_worker.update_key(STORAGE_KEY, data)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[KidsMathDuel] Leaderboard save error: {e!r}"
            )

    # ------------------------------------------------------------------
    # Exit detection — two-tier (exact match for short words, substring for phrases)
    # ------------------------------------------------------------------

    def _is_exit(self, text: str) -> bool:
        if not text:
            return False
        t = text.lower().strip()
        tokens = set(t.split())
        if tokens & EXIT_WORDS:
            return True
        return any(phrase in t for phrase in EXIT_PHRASES)
