import json
import re
from typing import Optional

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# CONVERSATION INSIGHTS COACH — Interactive Skill
# Triggered by hotwords like "how am I communicating?" or "my filler words".
# Reads analysis from insights_stats.json (written by background.py) and
# delivers a natural spoken report with trends, milestones, and coaching tips.
# Also handles goal-setting and real-time nudge toggling.
# =============================================================================

STATS_FILE = "insights_stats.json"

HOTWORDS = {
    "how am i communicating", "how am i speaking",
    "communication insights", "my filler words",
    "speech insights", "conversation insights",
    "speaking report", "communication report",
    "how do i talk", "analyze my speech",
    "my speaking patterns", "coach my speech",
    "set filler goal", "watch my fillers",
    "stop watching my fillers", "speech coach",
    "how's my speech", "hows my speech",
}

EXIT_WORDS = {
    "stop", "exit", "quit", "cancel", "done", "bye",
    "goodbye", "never mind", "nevermind", "no thanks",
    "that's all", "thats all", "end", "nothing",
}

COACHING_TIPS = {
    "fillers": "Try replacing filler words with a brief, confident pause. Silence is powerful — it gives your listener time to absorb what you said.",
    "hedging": "Notice when you say 'I think' or 'maybe' unnecessarily. If you know something, state it directly. Confidence in your voice builds trust.",
    "vocabulary": "Challenge yourself to use one or two new words each conversation. It keeps your language fresh and engaging.",
    "questions": "You ask a lot of questions — great for curiosity! Try balancing with statements to share your own perspective more.",
    "pace": "Your average sentence length is on the shorter side. Try elaborating a bit more to give your ideas room to breathe.",
}


class ConversationInsightsCapability(MatchingCapability):
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
        return any(w in text.lower() for w in EXIT_WORDS)

    def _clean_json(self, raw: str) -> str:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            ).strip()
        return raw

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    async def _load_stats(self) -> Optional[dict]:
        try:
            exists = await self.capability_worker.check_if_file_exists(STATS_FILE, False)
            if not exists:
                return None
            raw = await self.capability_worker.read_file(STATS_FILE, False)
            if not raw or not raw.strip():
                return None
            return json.loads(raw)
        except Exception:
            return None

    async def _save_stats(self, data: dict):
        try:
            exists = await self.capability_worker.check_if_file_exists(STATS_FILE, False)
            if exists:
                await self.capability_worker.delete_file(STATS_FILE, False)
            await self.capability_worker.write_file(
                STATS_FILE, json.dumps(data, indent=2), False
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[InsightsCoach] Save error: {e}")

    # ------------------------------------------------------------------
    # Intent classification
    # ------------------------------------------------------------------

    def _classify_intent(self, text: str) -> str:
        t = text.lower()

        if any(w in t for w in ("set goal", "filler goal", "fewer than", "less than", "target", "limit")):
            return "SET_GOAL"

        nudge_on = any(w in t for w in ("watch my fillers", "real-time", "coach me", "nudge", "alert me", "heads up"))
        nudge_off = any(w in t for w in ("stop watching", "stop coaching", "no nudge", "stop alerts", "disable nudge"))
        if nudge_on and not nudge_off:
            return "TOGGLE_NUDGE_ON"
        if nudge_off:
            return "TOGGLE_NUDGE_OFF"

        detail_areas = {
            "filler": "DETAIL_FILLERS",
            "hedge": "DETAIL_ASSERTIVENESS",
            "assertive": "DETAIL_ASSERTIVENESS",
            "vocab": "DETAIL_VOCABULARY",
            "word": "DETAIL_VOCABULARY",
            "question": "DETAIL_QUESTIONS",
            "length": "DETAIL_PACE",
            "sentence": "DETAIL_PACE",
        }
        for kw, intent in detail_areas.items():
            if kw in t:
                return intent

        return "REPORT"

    # ------------------------------------------------------------------
    # Metrics helpers
    # ------------------------------------------------------------------

    def _total_fillers(self, session: dict) -> int:
        return sum(session.get("filler_counts", {}).values())

    def _vocab_diversity(self, session: dict) -> float:
        words = session.get("total_words", 0)
        unique = session.get("unique_word_count", 0)
        return round(unique / words, 2) if words > 0 else 0.0

    def _filler_rate(self, session: dict) -> float:
        words = session.get("total_words", 0)
        fillers = self._total_fillers(session)
        return round(fillers / words, 4) if words > 0 else 0.0

    def _question_ratio(self, session: dict) -> float:
        utterances = session.get("total_utterances", 0)
        questions = session.get("question_count", 0)
        return round(questions / utterances, 2) if utterances > 0 else 0.0

    def _calc_streak(self, history: list) -> int:
        """Count consecutive days of decreasing filler_rate."""
        if len(history) < 2:
            return 0
        streak = 0
        sorted_h = sorted(history, key=lambda x: x.get("date", ""), reverse=True)
        for i in range(len(sorted_h) - 1):
            if sorted_h[i].get("filler_rate", 0) < sorted_h[i + 1].get("filler_rate", 0):
                streak += 1
            else:
                break
        return streak

    def _detect_milestone(self, session: dict, history: list) -> str:
        """Return a milestone string if the user hit a personal best, else ''."""
        if not history:
            return ""
        total_fillers_today = self._total_fillers(session)
        filler_rate_today = self._filler_rate(session)
        vocab_today = self._vocab_diversity(session)

        historical_filler_rates = [h.get("filler_rate", 999) for h in history]
        historical_vocab = [h.get("vocabulary_diversity", 0) for h in history]

        if total_fillers_today == 0 and session.get("total_utterances", 0) >= 10:
            return "Flawless session — not a single filler word detected!"
        if filler_rate_today < min(historical_filler_rates):
            return "This is your cleanest session yet — lowest filler rate on record!"
        if vocab_today > max(historical_vocab, default=0):
            return "Your vocabulary diversity hit a new personal high today!"
        return ""

    # ------------------------------------------------------------------
    # Goal helpers
    # ------------------------------------------------------------------

    def _parse_goal_number(self, text: str) -> Optional[int]:
        """Extract a target number from text like 'fewer than 10 fillers'."""
        prompt = (
            f"The user said: '{text}'\n"
            "Extract the numeric filler word target they want to set. "
            "Return ONLY valid JSON — no markdown:\n"
            '{"target": 10}'
            "\nIf no number found, return: {\"target\": null}"
        )
        try:
            raw = self.capability_worker.text_to_text_response(prompt)
            result = json.loads(self._clean_json(raw))
            val = result.get("target")
            return int(val) if val is not None else None
        except Exception:
            # Fallback: regex
            m = re.search(r'\b(\d+)\b', text)
            return int(m.group(1)) if m else None

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def _generate_report(self, session: dict, history: list,
                         goal: Optional[int], streak: int, milestone: str) -> str:
        total_fillers = self._total_fillers(session)
        vocab_div = self._vocab_diversity(session)
        self._filler_rate(session)
        question_ratio = self._question_ratio(session)
        avg_len = session.get("avg_utterance_length", 0.0)
        total_utterances = session.get("total_utterances", 0)
        top_fillers = sorted(
            session.get("filler_counts", {}),
            key=lambda k: session["filler_counts"][k],
            reverse=True,
        )[:3]
        new_vocab = session.get("new_vocab_words", [])[:3]
        total_hedges = sum(session.get("hedging_counts", {}).values())

        # Historical averages
        hist_avg_fillers = (
            round(sum(h.get("total_fillers", 0) for h in history) / len(history), 1)
            if history else None
        )
        hist_avg_vocab = (
            round(sum(h.get("vocabulary_diversity", 0) for h in history) / len(history), 2)
            if history else None
        )

        # Goal progress text
        goal_text = ""
        if goal is not None:
            if total_fillers <= goal:
                goal_text = f"You crushed your filler goal of {goal} — only {total_fillers} fillers!"
            else:
                remaining = goal - total_fillers
                if remaining > 0:
                    goal_text = f"You're at {total_fillers} fillers, {remaining} away from your goal of {goal}."
                else:
                    goal_text = f"You went over your goal of {goal} — {total_fillers} fillers so far. Keep working on it!"

        # New vocab highlight
        vocab_text = ""
        if new_vocab:
            words = ", ".join(f"'{w}'" for w in new_vocab)
            vocab_text = f"New words today: {words}."

        system_prompt = (
            "You are a friendly, encouraging communication coach delivering a brief spoken report. "
            "Be warm and supportive — like a trusted friend who happens to be an expert. "
            "Lead with something genuinely positive. Add one specific improvement suggestion at the end. "
            "Be specific with numbers. Keep it to 4-6 sentences. "
            "No bullet points — this will be spoken aloud. No robotic or clinical tone. "
            "If there's a milestone or streak, celebrate it enthusiastically but naturally. "
            "Note: filler counts may be slightly conservative because speech-to-text sometimes "
            "removes fillers like 'um' and 'uh' from transcriptions."
        )

        prompt = (
            f"Today's communication stats:\n"
            f"- Total utterances: {total_utterances}\n"
            f"- Filler words: {total_fillers} total"
            + (f" (top: {', '.join(top_fillers)})" if top_fillers else "") + "\n"
            f"- Hedging phrases (maybe, I think, etc.): {total_hedges}\n"
            f"- Vocabulary diversity: {int(vocab_div * 100)}%\n"
            f"- Question ratio: {int(question_ratio * 100)}% of utterances are questions\n"
            f"- Average utterance length: {avg_len} words\n"
        )

        if hist_avg_fillers is not None:
            prompt += f"\nHistorical average: {hist_avg_fillers} fillers/session, {int((hist_avg_vocab or 0) * 100)}% vocabulary diversity\n"
        if streak > 0:
            prompt += f"\nStreak: {streak} consecutive days of improving filler rate!\n"
        if milestone:
            prompt += f"\nMilestone: {milestone}\n"
        if goal_text:
            prompt += f"\nGoal progress: {goal_text}\n"
        if vocab_text:
            prompt += f"\n{vocab_text}\n"

        prompt += "\nGenerate the spoken coaching report now."

        try:
            return self.capability_worker.text_to_text_response(
                prompt, system_prompt=system_prompt
            )
        except Exception:
            # Fallback template
            parts = [
                f"So far today you've spoken {total_utterances} times.",
                f"You used {total_fillers} filler words" + (
                    f" — your most common being '{top_fillers[0]}'" if top_fillers else ""
                ) + ".",
            ]
            if hist_avg_fillers is not None:
                direction = "down" if total_fillers < hist_avg_fillers else "up"
                parts.append(f"That's {direction} from your average of {hist_avg_fillers}.")
            if milestone:
                parts.append(milestone)
            parts.append(f"Your vocabulary diversity is {int(vocab_div * 100)}%.")
            return " ".join(parts)

    def _generate_detail_report(self, area: str, session: dict, history: list) -> str:
        """Generate a focused sub-report for a specific communication area."""
        area_data = {}

        if area == "fillers":
            filler_counts = session.get("filler_counts", {})
            total = sum(filler_counts.values())
            top = sorted(filler_counts, key=filler_counts.get, reverse=True)[:5]
            hist_rates = [h.get("filler_rate", 0) for h in history]
            area_data = {
                "total_fillers": total,
                "breakdown": {k: filler_counts[k] for k in top},
                "rate_percent": round(self._filler_rate(session) * 100, 1),
                "historical_avg_rate": round(sum(hist_rates) / len(hist_rates) * 100, 1) if hist_rates else None,
                "tip": COACHING_TIPS["fillers"],
            }
            prompt = f"Filler word detail report:\n{json.dumps(area_data, indent=2)}\nDeliver a 2-3 sentence spoken breakdown. Mention the top fillers by name, give the rate, compare with history if available, and end with the tip. Warm, encouraging tone."

        elif area == "assertiveness":
            hedge_counts = session.get("hedging_counts", {})
            total = sum(hedge_counts.values())
            top = sorted(hedge_counts, key=hedge_counts.get, reverse=True)[:3]
            utterances = session.get("total_utterances", 1)
            area_data = {
                "total_hedges": total,
                "hedge_rate": round(total / utterances, 2),
                "top_hedges": {k: hedge_counts[k] for k in top},
                "tip": COACHING_TIPS["hedging"],
            }
            prompt = f"Assertiveness / hedging detail report:\n{json.dumps(area_data, indent=2)}\nDeliver a 2-3 sentence spoken summary. Warm, encouraging tone."

        elif area == "vocabulary":
            new_vocab = session.get("new_vocab_words", [])[:5]
            diversity = int(self._vocab_diversity(session) * 100)
            hist_vocab = [int(h.get("vocabulary_diversity", 0) * 100) for h in history]
            area_data = {
                "diversity_percent": diversity,
                "historical_avg_percent": round(sum(hist_vocab) / len(hist_vocab)) if hist_vocab else None,
                "new_words_today": new_vocab,
                "tip": COACHING_TIPS["vocabulary"],
            }
            prompt = f"Vocabulary detail report:\n{json.dumps(area_data, indent=2)}\nDeliver a 2-3 sentence spoken summary. Mention new words if any. Warm, encouraging tone."

        elif area == "questions":
            ratio = int(self._question_ratio(session) * 100)
            hist_ratios = [int(h.get("question_ratio", 0) * 100) for h in history]
            area_data = {
                "question_percent": ratio,
                "question_count": session.get("question_count", 0),
                "statement_count": session.get("statement_count", 0),
                "historical_avg_percent": round(sum(hist_ratios) / len(hist_ratios)) if hist_ratios else None,
                "tip": COACHING_TIPS["questions"],
            }
            prompt = f"Question vs statement detail report:\n{json.dumps(area_data, indent=2)}\nDeliver a 2-3 sentence spoken summary. Warm, encouraging tone."

        elif area == "pace":
            avg_len = session.get("avg_utterance_length", 0.0)
            area_data = {
                "avg_utterance_length_words": avg_len,
                "tip": COACHING_TIPS["pace"],
            }
            prompt = f"Speaking pace / length detail report:\n{json.dumps(area_data, indent=2)}\nDeliver a 2-3 sentence spoken summary. Warm, encouraging tone."

        else:
            return "I don't have a detail breakdown for that area yet."

        system_prompt = (
            "You are a friendly communication coach. Keep it to 2-3 sentences, "
            "spoken aloud, no bullet points. Be specific with numbers. Warm and encouraging."
        )
        try:
            return self.capability_worker.text_to_text_response(
                prompt, system_prompt=system_prompt
            )
        except Exception:
            return f"Here's what I tracked: {json.dumps(area_data)}."

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    async def _run(self):
        try:
            await self.capability_worker.wait_for_complete_transcription()

            # Get the trigger utterance for intent classification
            trigger_text = ""
            try:
                history = self.capability_worker.get_full_message_history()
                history = history or []
                user_msgs = [m for m in history if m.get("role") == "user"]
                if user_msgs:
                    trigger_text = user_msgs[-1].get("content", "") or ""
                    if not isinstance(trigger_text, str):
                        trigger_text = ""
            except Exception:
                trigger_text = ""

            intent = self._classify_intent(trigger_text)

            # Load stats
            data = await self._load_stats()

            # ── TOGGLE NUDGE ────────────────────────────────────────
            if intent in ("TOGGLE_NUDGE_ON", "TOGGLE_NUDGE_OFF"):
                enable = intent == "TOGGLE_NUDGE_ON"
                if data:
                    data.setdefault("settings", {})["nudge_enabled"] = enable
                    await self._save_stats(data)
                if enable:
                    await self.capability_worker.speak(
                        "Real-time coaching is on. I'll give you a gentle heads-up "
                        "whenever I notice a cluster of filler words. You've got this!"
                    )
                else:
                    await self.capability_worker.speak(
                        "Got it — I'll stop the real-time nudges. "
                        "You can still ask for a full report anytime."
                    )
                return

            # ── SET GOAL ────────────────────────────────────────────
            if intent == "SET_GOAL":
                target = self._parse_goal_number(trigger_text)
                if target is None:
                    await self.capability_worker.speak(
                        "I didn't catch a number. Try saying something like "
                        "'set a goal of 10 fillers today'."
                    )
                    return
                if data:
                    data.setdefault("settings", {})["filler_goal"] = target
                    await self._save_stats(data)
                await self.capability_worker.speak(
                    f"Goal set! I'll track your progress toward fewer than {target} filler words today. "
                    "Ask for a report anytime to see how you're doing."
                )
                return

            # ── Check minimum data ──────────────────────────────────
            if not data:
                await self.capability_worker.speak(
                    "I haven't collected any data yet. "
                    "Keep chatting and ask me again in a few minutes!"
                )
                return

            session = data.get("current_session", {})
            utterances = session.get("total_utterances", 0)

            if utterances < 5:
                await self.capability_worker.speak(
                    f"I've only tracked {utterances} utterances so far — "
                    "not quite enough for a meaningful report. "
                    "Keep the conversation going and check back in a few minutes!"
                )
                return

            history = data.get("daily_history", [])
            settings = data.get("settings", {})
            goal = settings.get("filler_goal")

            # ── DETAIL REPORTS ──────────────────────────────────────
            detail_map = {
                "DETAIL_FILLERS": "fillers",
                "DETAIL_ASSERTIVENESS": "assertiveness",
                "DETAIL_VOCABULARY": "vocabulary",
                "DETAIL_QUESTIONS": "questions",
                "DETAIL_PACE": "pace",
            }
            if intent in detail_map:
                area = detail_map[intent]
                report = self._generate_detail_report(area, session, history)
                await self.capability_worker.speak(report)

                reply = await self.capability_worker.user_response()
                if not self._is_exit(reply) and reply:
                    # One follow-up: check if they want another area
                    follow_intent = self._classify_intent(reply)
                    if follow_intent in detail_map:
                        follow_report = self._generate_detail_report(
                            detail_map[follow_intent], session, history
                        )
                        await self.capability_worker.speak(follow_report)
                return

            # ── FULL REPORT ─────────────────────────────────────────
            streak = self._calc_streak(history)
            milestone = self._detect_milestone(session, history)
            report = self._generate_report(session, history, goal, streak, milestone)
            await self.capability_worker.speak(report)

            # Follow-up offer
            await self.capability_worker.speak(
                "Want more detail on any area? "
                "I can break down your fillers, vocabulary, assertiveness, or question ratio. "
                "Or just say stop."
            )

            follow_reply = await self.capability_worker.user_response()
            if self._is_exit(follow_reply) or not follow_reply:
                return

            follow_intent = self._classify_intent(follow_reply)

            # Handle goal/nudge toggle in follow-up
            if follow_intent == "SET_GOAL":
                target = self._parse_goal_number(follow_reply)
                if target:
                    data.setdefault("settings", {})["filler_goal"] = target
                    await self._save_stats(data)
                    await self.capability_worker.speak(
                        f"Done — filler goal set to {target}. I'll track your progress!"
                    )
                return

            if follow_intent in ("TOGGLE_NUDGE_ON", "TOGGLE_NUDGE_OFF"):
                enable = follow_intent == "TOGGLE_NUDGE_ON"
                data.setdefault("settings", {})["nudge_enabled"] = enable
                await self._save_stats(data)
                msg = (
                    "Real-time coaching enabled. I'll nudge you when I spot filler clusters."
                    if enable else
                    "Real-time nudges turned off. Ask for a report anytime!"
                )
                await self.capability_worker.speak(msg)
                return

            if follow_intent in detail_map:
                follow_report = self._generate_detail_report(
                    detail_map[follow_intent], session, history
                )
                await self.capability_worker.speak(follow_report)
                return

            # Fallback: they said something, but we couldn't classify it
            await self.capability_worker.speak(
                "No problem! Come back anytime you want to check in on your communication."
            )

        except Exception as e:
            try:
                self.worker.editor_logging_handler.error(f"[InsightsCoach] Skill error: {e}")
                await self.capability_worker.speak(
                    "Something went wrong. Try asking again in a moment."
                )
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self._run())
