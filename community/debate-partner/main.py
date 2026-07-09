import json

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# DEBATE PARTNER — Interactive Skill
# A structured debate experience with multi-voice delivery, adaptive arguments,
# round-based scoring, and constructive feedback. The opponent always takes the
# opposing side so the user sharpens their reasoning skills.
# =============================================================================

# ── Voice IDs ────────────────────────────────────────────────────────────────
# Opponent uses a distinct British deep voice so the user can clearly
# distinguish the opponent from the moderator (default agent voice).
OPPONENT_VOICE_ID = "onwK4e9ZLuTAKqWW03F9"   # British Male, Deep (Daniel)

# ── Constants ────────────────────────────────────────────────────────────────
STATS_FILE = "debate_stats.json"

HOTWORDS = {
    "debate", "let's debate", "lets debate", "start a debate",
    "debate me", "debate with me", "i want to debate",
    "argue with me", "let's argue", "lets argue",
    "debate partner", "debate practice",
    "challenge me", "challenge my thinking",
}

EXIT_WORDS = {
    "stop", "exit", "quit", "cancel", "done", "bye", "goodbye",
    "never mind", "nevermind", "no thanks", "nah", "end debate",
    "i'm done", "im done", "that's all", "thats all", "end",
}

DIFFICULTY_KEYWORDS = {
    "easy": {"easy", "beginner", "casual", "gentle", "simple", "light"},
    "medium": {"medium", "normal", "moderate", "standard", "default", "balanced"},
    "hard": {"hard", "difficult", "expert", "tough", "advanced", "intense", "brutal"},
}

ROUND_NAMES = ["Opening Statements", "Rebuttals", "Closing Arguments"]

TOPIC_SUGGESTIONS = [
    "Should AI replace teachers in schools?",
    "Is social media doing more harm than good?",
    "Should space exploration be prioritized over fixing Earth's problems?",
    "Is remote work better than office work?",
    "Should voting be mandatory?",
    "Is privacy more important than security?",
    "Should college education be free for everyone?",
    "Is technology making us less creative?",
]

# ── Scoring rubric descriptions (shared with LLM) ───────────────────────────
SCORING_RUBRIC = (
    "Score each criterion from 1-10:\n"
    "  - Logic & Reasoning: Is the argument logically sound? Are conclusions supported?\n"
    "  - Evidence & Examples: Are concrete examples, data, or analogies used effectively?\n"
    "  - Persuasiveness: How compelling is the delivery? Would it sway an audience?\n"
    "  - Rebuttal Quality: How well did they address the opponent's points? (Round 2+ only, score 0 for Round 1)\n"
)


class DebatePartnerCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    # ------------------------------------------------------------------
    # Hotword matching
    # ------------------------------------------------------------------

    def does_match(self, text: str) -> bool:
        t = text.lower().strip()
        return any(hw in t for hw in HOTWORDS)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_exit(self, text: str) -> bool:
        if not text:
            return True
        return text.lower().strip() in EXIT_WORDS

    def _clean_json(self, raw: str) -> str:
        """Strip markdown code fences from LLM output."""
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            ).strip()
        return raw

    def _detect_difficulty(self, text: str) -> str:
        """Parse user input into easy/medium/hard."""
        t = text.lower().strip()
        for level, keywords in DIFFICULTY_KEYWORDS.items():
            if any(kw in t for kw in keywords):
                return level
        return "medium"

    # ------------------------------------------------------------------
    # Stats persistence
    # ------------------------------------------------------------------

    async def _load_stats(self) -> dict:
        try:
            exists = await self.capability_worker.check_if_file_exists(
                STATS_FILE, False
            )
            if not exists:
                return {"debates": 0, "wins": 0, "losses": 0, "draws": 0}
            raw = await self.capability_worker.read_file(STATS_FILE, False)
            return json.loads(raw) if raw.strip() else {"debates": 0, "wins": 0, "losses": 0, "draws": 0}
        except Exception:
            return {"debates": 0, "wins": 0, "losses": 0, "draws": 0}

    async def _save_stats(self, stats: dict):
        try:
            exists = await self.capability_worker.check_if_file_exists(
                STATS_FILE, False
            )
            if exists:
                await self.capability_worker.delete_file(STATS_FILE, False)
            await self.capability_worker.write_file(
                STATS_FILE, json.dumps(stats, indent=2), False
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # LLM calls
    # ------------------------------------------------------------------

    def _generate_opponent_argument(self, debate_state: dict, round_index: int,
                                    user_argument: str) -> dict:
        """
        Generate the opponent's argument for the current round.
        Returns {"argument": str, "user_score": dict, "opponent_score": dict}
        """
        topic = debate_state["topic"]
        user_side = debate_state["user_side"]
        opponent_side = debate_state["ai_side"]
        difficulty = debate_state["difficulty"]
        history_text = debate_state.get("history_text", "")
        round_name = ROUND_NAMES[round_index]

        difficulty_instructions = {
            "easy": (
                "You are a BEGINNER debater. Make decent but somewhat surface-level arguments. "
                "Occasionally miss obvious counterpoints. Use simple language. "
                "The user should feel they can win with solid reasoning."
            ),
            "medium": (
                "You are a COMPETENT debater. Make strong, well-structured arguments with "
                "good examples. Challenge the user's points fairly. Occasionally concede "
                "a good point the user makes. Be formidable but beatable."
            ),
            "hard": (
                "You are an EXPERT debater — a world-class rhetorician. Deploy advanced "
                "techniques: steel-manning, reductio ad absurdum, Socratic questioning, "
                "real-world data. Expose every logical weakness ruthlessly. Rarely concede. "
                "The user must bring their absolute best to compete."
            ),
        }

        system_prompt = (
            f"You are a debate opponent. {difficulty_instructions.get(difficulty, difficulty_instructions['medium'])}\n\n"
            f"DEBATE TOPIC: {topic}\n"
            f"YOUR POSITION: {opponent_side}\n"
            f"OPPONENT'S POSITION: {user_side}\n\n"
            "IMPORTANT RULES:\n"
            "- Keep your argument concise: 3-5 sentences MAX. This is a SPOKEN debate.\n"
            "- Be passionate but respectful — never personal attacks.\n"
            "- Use concrete examples and clear reasoning.\n"
            "- Write for speech, not text — no bullet points, no numbered lists.\n"
            "- Do NOT start with 'I believe' or 'I think' — jump straight into the argument.\n"
        )

        round_instructions = ""
        if round_index == 0:
            round_instructions = (
                "This is the OPENING STATEMENT. Present your strongest case clearly and "
                "compellingly. Set the foundation for your position."
            )
        elif round_index == 1:
            round_instructions = (
                "This is the REBUTTAL round. You MUST directly address and counter "
                "the opponent's previous arguments. Then reinforce your own position."
            )
        else:
            round_instructions = (
                "This is the CLOSING ARGUMENT. Summarize your strongest points. "
                "Address the key clash points of the debate. End with a powerful "
                "concluding statement."
            )

        prompt = (
            f"ROUND: {round_name}\n"
            f"{round_instructions}\n\n"
        )

        if history_text:
            prompt += f"DEBATE SO FAR:\n{history_text}\n\n"

        prompt += (
            f"The opponent (user) just said:\n\"{user_argument}\"\n\n"
            "Now deliver YOUR argument for this round (3-5 sentences, spoken style).\n\n"
            "ALSO score BOTH sides for this round.\n"
            f"{SCORING_RUBRIC}\n"
            "Return ONLY valid JSON — no markdown, no explanation:\n"
            "{\n"
            '  "argument": "Your spoken argument here",\n'
            '  "user_score": {"logic": 7, "evidence": 6, "persuasion": 7, "rebuttal": 0},\n'
            '  "opponent_score": {"logic": 8, "evidence": 7, "persuasion": 7, "rebuttal": 0}\n'
            "}"
        )

        try:
            raw = self.capability_worker.text_to_text_response(
                prompt,
                system_prompt=system_prompt,
            )
            cleaned = self._clean_json(raw)
            result = json.loads(cleaned)
            # Validate structure
            if "argument" not in result:
                result["argument"] = "I concede this point to you. Well argued."
            if "user_score" not in result:
                result["user_score"] = {"logic": 5, "evidence": 5, "persuasion": 5, "rebuttal": 0}
            if "opponent_score" not in result:
                result["opponent_score"] = {"logic": 5, "evidence": 5, "persuasion": 5, "rebuttal": 0}
            return result
        except Exception:
            return {
                "argument": "That's an interesting perspective. However, I'd argue the opposite is true when we consider the broader implications and real-world evidence.",
                "user_score": {"logic": 5, "evidence": 5, "persuasion": 5, "rebuttal": 0},
                "opponent_score": {"logic": 5, "evidence": 5, "persuasion": 5, "rebuttal": 0},
            }

    def _generate_topic_position(self, topic: str) -> dict:
        """
        Given a topic, determine the two debate sides.
        Returns {"side_a": str, "side_b": str}
        """
        prompt = (
            f"The debate topic is: '{topic}'\n\n"
            "Identify the two opposing positions for this debate.\n"
            "Make each position a clear, concise stance (one sentence each).\n"
            "side_a should be the 'FOR/PRO' position, side_b should be 'AGAINST/CON'.\n\n"
            "Return ONLY valid JSON — no markdown:\n"
            '{"side_a": "...", "side_b": "..."}'
        )
        try:
            raw = self.capability_worker.text_to_text_response(prompt)
            cleaned = self._clean_json(raw)
            return json.loads(cleaned)
        except Exception:
            return {
                "side_a": f"In favor of: {topic}",
                "side_b": f"Against: {topic}",
            }

    def _generate_final_verdict(self, debate_state: dict) -> dict:
        """
        Generate the final verdict with detailed feedback.
        Returns {"winner": "user"|"opponent"|"draw", "user_total": int, "opponent_total": int,
                 "feedback": str, "highlight": str}
        """
        topic = debate_state["topic"]
        user_side = debate_state["user_side"]
        opponent_side = debate_state["ai_side"]
        history_text = debate_state.get("history_text", "")
        user_scores = debate_state.get("user_scores", [])
        opponent_scores = debate_state.get("ai_scores", [])

        prompt = (
            f"DEBATE TOPIC: {topic}\n"
            f"USER'S POSITION: {user_side}\n"
            f"OPPONENT'S POSITION: {opponent_side}\n\n"
            f"FULL DEBATE TRANSCRIPT:\n{history_text}\n\n"
            f"ROUND SCORES (user): {json.dumps(user_scores)}\n"
            f"ROUND SCORES (opponent): {json.dumps(opponent_scores)}\n\n"
            "As an impartial debate judge, provide:\n"
            "1. The winner based on the scores and overall performance\n"
            "2. A brief, encouraging summary of how the user did (2-3 sentences, spoken style)\n"
            "3. One specific highlight — the user's strongest moment in the debate\n\n"
            "Be fair but SLIGHTLY generous to the user — this should be fun and encouraging.\n"
            "If scores are within 5 points total, call it a draw.\n\n"
            "Return ONLY valid JSON — no markdown:\n"
            "{\n"
            '  "winner": "user" or "opponent" or "draw",\n'
            '  "user_total": 85,\n'
            '  "opponent_total": 78,\n'
            '  "feedback": "spoken feedback here",\n'
            '  "highlight": "your strongest moment was..."\n'
            "}"
        )
        try:
            raw = self.capability_worker.text_to_text_response(prompt)
            cleaned = self._clean_json(raw)
            result = json.loads(cleaned)
            # Ensure required fields exist
            for key in ("winner", "user_total", "opponent_total", "feedback", "highlight"):
                if key not in result:
                    raise ValueError(f"Missing {key}")
            return result
        except Exception:
            # Calculate from raw scores
            u_total = sum(
                sum(s.values()) for s in user_scores
            ) if user_scores else 0
            o_total = sum(
                sum(s.values()) for s in opponent_scores
            ) if opponent_scores else 0
            diff = u_total - o_total
            if abs(diff) <= 5:
                winner = "draw"
            elif diff > 0:
                winner = "user"
            else:
                winner = "opponent"
            return {
                "winner": winner,
                "user_total": u_total,
                "opponent_total": o_total,
                "feedback": "That was a solid debate! You made some really strong points throughout.",
                "highlight": "You showed great reasoning in your arguments.",
            }

    # ------------------------------------------------------------------
    # Debate flow
    # ------------------------------------------------------------------

    async def _setup_debate(self) -> dict | None:
        """
        Walk the user through topic selection, side choice, and difficulty.
        Returns debate_state dict or None if user exits.
        """
        # ── Step 1: Topic ────────────────────────────────────────────
        suggestions = ". ".join(TOPIC_SUGGESTIONS[:4])
        await self.capability_worker.speak(
            "Welcome to Debate Partner! I'll take the opposing side on any "
            "topic you choose, and we'll go head to head in a 3-round debate. "
            f"Give me a topic, or pick from these: {suggestions}. "
            "Or say 'surprise me' for a random topic."
        )

        topic_reply = await self.capability_worker.user_response()
        if self._is_exit(topic_reply):
            return None

        # Handle "surprise me"
        t = topic_reply.lower().strip()
        if "surprise" in t or "random" in t or "pick" in t or "choose" in t:
            import random
            topic = random.choice(TOPIC_SUGGESTIONS)
            await self.capability_worker.speak(f"Great — let's debate: {topic}")
        else:
            topic = topic_reply.strip()
            await self.capability_worker.speak(f"Nice pick! The topic is: {topic}")

        # ── Step 2: Determine sides ──────────────────────────────────
        positions = self._generate_topic_position(topic)
        side_a = positions.get("side_a", f"In favor of {topic}")
        side_b = positions.get("side_b", f"Against {topic}")

        await self.capability_worker.speak(
            f"Here are the two sides. "
            f"Side A: {side_a}. "
            f"Side B: {side_b}. "
            "Which side do you want to argue? Say A or B."
        )

        side_reply = await self.capability_worker.user_response()
        if self._is_exit(side_reply):
            return None

        sr = side_reply.lower().strip()
        if "b" in sr and "a" not in sr:
            user_side = side_b
            opponent_side = side_a
        elif "a" in sr:
            user_side = side_a
            opponent_side = side_b
        else:
            # Try to infer — if they said something closer to side_a or side_b
            # Default to A for user (most common: user picks the "for" side)
            user_side = side_a
            opponent_side = side_b

        await self.capability_worker.speak(
            f"Got it. You'll argue: {user_side}. "
            f"Your opponent will argue: {opponent_side}."
        )

        # ── Step 3: Difficulty ───────────────────────────────────────
        await self.capability_worker.speak(
            "How tough do you want me to be? Easy, medium, or hard? "
            "Say skip to default to medium."
        )

        diff_reply = await self.capability_worker.user_response()
        if self._is_exit(diff_reply):
            return None

        if "skip" in diff_reply.lower():
            difficulty = "medium"
        else:
            difficulty = self._detect_difficulty(diff_reply)

        difficulty_labels = {"easy": "Easy — I'll go gentle", "medium": "Medium — a fair challenge", "hard": "Hard — no mercy"}
        await self.capability_worker.speak(
            f"Difficulty set to {difficulty_labels.get(difficulty, difficulty)}. "
            "The debate has 3 rounds: Opening Statements, Rebuttals, and Closing Arguments. "
            "You go first each round. Let's begin!"
        )

        return {
            "topic": topic,
            "user_side": user_side,
            "ai_side": opponent_side,
            "difficulty": difficulty,
            "history_text": "",
            "user_scores": [],
            "ai_scores": [],
        }

    async def _run_debate(self, state: dict) -> dict | None:
        """
        Execute the 3-round debate loop.
        Returns updated state with scores, or None if user exits.
        """
        for round_index in range(3):
            round_name = ROUND_NAMES[round_index]
            round_num = round_index + 1

            # ── Announce round ───────────────────────────────────────
            if round_index == 0:
                await self.capability_worker.speak(
                    f"Round {round_num}: {round_name}. "
                    "Make your opening argument — I'm listening."
                )
            elif round_index == 1:
                await self.capability_worker.speak(
                    f"Round {round_num}: {round_name}. "
                    "Now counter my arguments and strengthen your case. Go ahead."
                )
            else:
                await self.capability_worker.speak(
                    f"Round {round_num}: {round_name}. "
                    "This is your final chance to make your case. Deliver your closing argument."
                )

            # ── User's turn ──────────────────────────────────────────
            user_argument = await self.capability_worker.user_response()
            if self._is_exit(user_argument):
                return None

            # Handle very short / empty responses
            if not user_argument or len(user_argument.strip()) < 10:
                await self.capability_worker.speak(
                    "I didn't quite catch a full argument there. "
                    "Take your time — give me your best shot."
                )
                user_argument = await self.capability_worker.user_response()
                if self._is_exit(user_argument):
                    return None
                if not user_argument or len(user_argument.strip()) < 5:
                    user_argument = "I pass on this round."

            # Update debate history
            state["history_text"] += (
                f"\n--- Round {round_num}: {round_name} ---\n"
                f"USER ({state['user_side']}): {user_argument}\n"
            )

            # ── Opponent's turn ──────────────────────────────────────
            await self.capability_worker.speak("Interesting point. Here's my response.")

            result = self._generate_opponent_argument(state, round_index, user_argument)

            opponent_argument = result["argument"]
            user_round_score = result["user_score"]
            opponent_round_score = result.get("opponent_score", result.get("ai_score", {"logic": 5, "evidence": 5, "persuasion": 5, "rebuttal": 0}))

            # Speak opponent argument in the OPPONENT voice
            await self.capability_worker.text_to_speech(opponent_argument, OPPONENT_VOICE_ID)

            # Update state
            state["history_text"] += f"OPPONENT ({state['ai_side']}): {opponent_argument}\n"
            state["user_scores"].append(user_round_score)
            state["ai_scores"].append(opponent_round_score)

            # ── Round score announcement (moderator voice) ───────────
            u_round = sum(user_round_score.values())
            o_round = sum(opponent_round_score.values())

            if round_index < 2:
                # Brief score update between rounds
                if u_round > o_round:
                    score_comment = f"You're leading this round {u_round} to {o_round}."
                elif o_round > u_round:
                    score_comment = f"Opponent takes this round {o_round} to {u_round}."
                else:
                    score_comment = f"This round is tied at {u_round} each."

                await self.capability_worker.speak(score_comment)

            # Small pause between rounds
            await self.worker.session_tasks.sleep(1.0)

        return state

    async def _deliver_verdict(self, state: dict):
        """Announce the final verdict with scores and feedback."""
        await self.capability_worker.speak(
            "The debate is over! Let me tally the scores and deliver the verdict."
        )
        await self.worker.session_tasks.sleep(1.5)

        verdict = self._generate_final_verdict(state)

        winner = verdict.get("winner", "draw")
        user_total = verdict.get("user_total", 0)
        opponent_total = verdict.get("opponent_total", verdict.get("ai_total", 0))
        feedback = verdict.get("feedback", "Great debate!")
        highlight = verdict.get("highlight", "")

        # Announce scores
        await self.capability_worker.speak(
            f"Final scores — You: {user_total} points. Opponent: {opponent_total} points."
        )
        await self.worker.session_tasks.sleep(1.0)

        # Announce winner
        if winner == "user":
            await self.capability_worker.speak(
                "And the winner is... you! Congratulations, you won this debate!"
            )
        elif winner == "opponent":
            await self.capability_worker.text_to_speech(
                "I'll take this one. But you put up a solid fight!",
                OPPONENT_VOICE_ID,
            )
        else:
            await self.capability_worker.speak(
                "It's a draw! We were evenly matched on this one."
            )

        await self.worker.session_tasks.sleep(0.5)

        # Feedback
        if feedback:
            await self.capability_worker.speak(feedback)
        if highlight:
            await self.capability_worker.speak(highlight)

        # Update persistent stats
        stats = await self._load_stats()
        stats["debates"] = stats.get("debates", 0) + 1
        if winner == "user":
            stats["wins"] = stats.get("wins", 0) + 1
        elif winner == "opponent":
            stats["losses"] = stats.get("losses", 0) + 1
        else:
            stats["draws"] = stats.get("draws", 0) + 1
        await self._save_stats(stats)

        # Share lifetime stats
        total = stats["debates"]
        wins = stats["wins"]
        losses = stats["losses"]
        draws = stats["draws"]
        await self.capability_worker.speak(
            f"Your all-time record: {wins} wins, {losses} losses, "
            f"{draws} draws out of {total} debates."
        )

    async def _post_debate(self) -> bool:
        """
        After a debate, offer to play again.
        Returns True if user wants another debate, False otherwise.
        """
        await self.capability_worker.speak(
            "Want to go again? Say 'new debate' for a fresh topic, "
            "'rematch' to debate the same topic again, or 'stop' to exit."
        )
        reply = await self.capability_worker.user_response()
        if not reply or self._is_exit(reply):
            return False
        r = reply.lower().strip()
        if "rematch" in r or "same" in r or "again" in r:
            return True  # Caller can handle rematch vs new
        if "new" in r or "debate" in r or "yes" in r or "sure" in r or "yeah" in r or "yep" in r:
            return True
        return False

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self._run())

    async def _run(self):
        try:
            # Wait for the full trigger utterance to finish
            await self.capability_worker.wait_for_complete_transcription()

            while True:
                # Setup phase: topic, sides, difficulty
                state = await self._setup_debate()
                if state is None:
                    await self.capability_worker.speak(
                        "No worries! Come back anytime you want to sharpen your debate skills."
                    )
                    return

                # Run the 3-round debate
                final_state = await self._run_debate(state)
                if final_state is None:
                    # User exited mid-debate
                    await self.capability_worker.speak(
                        "Debate ended early. Your progress wasn't saved this time, "
                        "but you can start a new debate anytime!"
                    )
                    return

                # Deliver verdict and feedback
                await self._deliver_verdict(final_state)

                # Post-debate: play again?
                play_again = await self._post_debate()
                if not play_again:
                    await self.capability_worker.speak(
                        "Great debating with you! Come back anytime you want to sharpen "
                        "your arguments. See you next time!"
                    )
                    return

                # Loop back to setup for a new debate

        except Exception as e:
            try:
                self.worker.editor_logging_handler.error(
                    f"[DebatePartner] Error: {e}"
                )
                await self.capability_worker.speak(
                    "Something went wrong during the debate. "
                    "Please try again by saying 'start a debate'."
                )
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()
