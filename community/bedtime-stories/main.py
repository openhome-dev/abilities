import json
from datetime import datetime

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

STORAGE_KEY = "bedtime_story_data"

HOTWORDS = [
    "bedtime story", "tell me a story", "story time", "read me a story",
    "continue my story", "another story", "new story", "resume my story",
    "tell a story", "story please", "story for me", "storytime",
]

EXIT_WORDS = {"stop", "done", "goodnight", "bye", "no more", "that's enough", "end", "finish"}
CONTINUE_WORDS = {"continue", "resume", "last night", "where we left", "same story", "keep going"}
NEW_WORDS = {"new story", "new adventure", "different", "another story", "something else", "something new"}

HERO_SETUP_PROMPT = (
    "Create a bedtime story hero for a {age}-year-old child named {child_name} who loves {favorites}. "
    "Return only valid JSON with no markdown: "
    '{"hero_name": "...", "hero_description": "... (max 12 words, warm and imaginative)", '
    '"universe": "... (max 15 words, cozy and magical)"}. '
    "Make hero_name a gentle, magical variation or nickname of {child_name}."
)

SEGMENT_PROMPT = (
    "You are a calm, soothing bedtime storyteller for a {age}-year-old child. "
    "Hero: {hero_name} — {hero_description}. "
    "World: {universe}. "
    "Past adventures (for reference): {history}. "
    "Story so far tonight: {story_so_far}. "
    "{choice_context}"
    "Write the next part of the story in 4-5 warm, calming sentences. "
    "Use simple language perfect for a {age}-year-old who is falling asleep. "
    "No scary content, no unresolved danger, nothing exciting or stimulating. "
    "{ending_instruction}"
    "Plain text only — no titles, no markdown, no quotes around the text."
)


class BedtimeStoriesCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    def does_match(self, text: str) -> bool:
        t = text.lower()
        return any(hw in t for hw in HOTWORDS)

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self._run())

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def _load_data(self) -> dict:
        try:
            result = self.capability_worker.get_single_key(STORAGE_KEY)
            if result and result.get("value"):
                return result["value"]
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[BedtimeStories] Load error: {e!r}")
        return {}

    def _save_data(self, data: dict):
        def ok(resp):
            return isinstance(resp, dict) and resp.get("success")
        try:
            if ok(self.capability_worker.create_key(STORAGE_KEY, data)):
                return
            if ok(self.capability_worker.update_key(STORAGE_KEY, data)):
                return
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[BedtimeStories] Save error: {e!r}")
            return
        self.worker.editor_logging_handler.error("[BedtimeStories] Save failed")

    # ------------------------------------------------------------------
    # Intent classification
    # ------------------------------------------------------------------

    @staticmethod
    def _is_exit(text: str) -> bool:
        # Short ambiguous words ("stop", "done", "end", "finish") only count
        # as an exit when they're the WHOLE reply — a child might genuinely
        # say things like "he should stop and think" or "at the end of the
        # story" where the word is real but not an exit request. Distinctive
        # multi-word phrases ("that's enough", "no more") still match
        # anywhere in the reply.
        lower = (text or "").lower().strip().rstrip(".!?")
        if not lower:
            return False
        if lower in EXIT_WORDS:
            return True
        return any(phrase in lower for phrase in EXIT_WORDS if " " in phrase)

    def _classify_intent(self, text: str) -> str:
        t = text.lower()
        if self._is_exit(text):
            return "EXIT"
        if any(w in t for w in NEW_WORDS):
            return "NEW"
        if any(w in t for w in CONTINUE_WORDS):
            return "CONTINUE"
        return "CONTINUE"

    # ------------------------------------------------------------------
    # Hero generation
    # ------------------------------------------------------------------

    def _generate_hero(self, child_name: str, child_age: int, favorites: str) -> dict:
        raw = self.capability_worker.text_to_text_response(
            HERO_SETUP_PROMPT.format(
                age=child_age,
                child_name=child_name,
                favorites=favorites,
            )
        )
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            return json.loads(cleaned.strip())
        except Exception:
            return {
                "hero_name": child_name,
                "hero_description": f"a brave {child_age}-year-old who loves {favorites}",
                "universe": "a magical forest where animals can talk and stars come out to play",
            }

    def _extract_age(self, text: str) -> int:
        for token in text.split():
            cleaned = "".join(c for c in token if c.isdigit())
            if cleaned:
                age = int(cleaned)
                if 2 <= age <= 15:
                    return age
        return 7

    # ------------------------------------------------------------------
    # Story generation
    # ------------------------------------------------------------------

    def _build_history_text(self, data: dict) -> str:
        history = data.get("story_history", [])
        if not history:
            return "this is the very first adventure"
        summaries = [h["summary"] for h in history[-3:]]
        return "; ".join(summaries)

    def _build_story_so_far(self, data: dict) -> str:
        story = data.get("current_story")
        if not story or not story.get("checkpoint"):
            return "the story is just beginning"
        parts = [story["checkpoint"]]
        choices = story.get("choices_made", [])
        if choices:
            parts.append(f"choices made: {', '.join(choices)}")
        return "; ".join(parts)

    def _last_sentence(self, text: str) -> str:
        sentences = [s.strip() for s in text.replace("!", ".").replace("?", ".").split(".") if s.strip()]
        return sentences[-1] if sentences else text[:120]

    def _parse_segment(self, raw: str) -> tuple:
        if "CHOICE:" in raw:
            parts = raw.split("CHOICE:", 1)
            story_text = parts[0].strip()
            choice_question = parts[1].strip()
            return story_text, choice_question
        return raw.strip(), ""

    def _generate_segment(
        self, data: dict, is_final: bool, include_choice: bool, last_choice: str
    ) -> tuple:
        age = data.get("child_age", 7)
        hero_name = data.get("hero_name", "the hero")

        ending_instruction = (
            f"End peacefully — {hero_name} settles down to rest, arrives safely home, or drifts off to sleep. "
            if is_final
            else (
                f"After the story segment, add one line starting with 'CHOICE:' offering two simple, fun options. "
                f"Example: CHOICE: Should {hero_name} climb the hill or follow the stream? "
                if include_choice
                else ""
            )
        )

        choice_context = (
            f"The child chose: {last_choice}. Continue the story based on that choice. "
            if last_choice
            else ""
        )

        raw = self.capability_worker.text_to_text_response(
            SEGMENT_PROMPT.format(
                age=age,
                hero_name=hero_name,
                hero_description=data.get("hero_description", "a brave explorer"),
                universe=data.get("universe", "a magical forest"),
                history=self._build_history_text(data),
                story_so_far=self._build_story_so_far(data),
                choice_context=choice_context,
                ending_instruction=ending_instruction,
            )
        )

        return self._parse_segment(raw)

    def _save_checkpoint(self, data: dict, segment_text: str, choice_made: str):
        data.get("hero_name", "the hero")
        checkpoint = self._last_sentence(segment_text)
        if not data.get("current_story"):
            data["current_story"] = {
                "checkpoint": checkpoint,
                "segments_complete": 0,
                "choices_made": [],
                "complete": False,
                "date": datetime.now().strftime("%Y-%m-%d"),
            }
        else:
            data["current_story"]["checkpoint"] = checkpoint
            if choice_made:
                data["current_story"].setdefault("choices_made", []).append(choice_made)
        self._save_data(data)

    def _archive_story(self, data: dict):
        checkpoint = ""
        if data.get("current_story"):
            checkpoint = data["current_story"].get("checkpoint", "")
        hero_name = data.get("hero_name", "the hero")
        summary = checkpoint if checkpoint else f"{hero_name} had a wonderful adventure"
        data.setdefault("story_history", []).append({
            "summary": summary,
            "date": datetime.now().strftime("%Y-%m-%d"),
        })
        if len(data["story_history"]) > 10:
            data["story_history"] = data["story_history"][-10:]
        data["current_story"] = None
        self._save_data(data)

    # ------------------------------------------------------------------
    # Story telling
    # ------------------------------------------------------------------

    async def _tell_story(self, data: dict):
        child_name = data["child_name"]
        child_age = data.get("child_age", 7)
        hero_name = data["hero_name"]

        max_segments = 2 if child_age <= 5 else 3
        use_choice = child_age >= 6
        segments_done = 0
        last_choice = ""

        if data.get("current_story"):
            segments_done = data["current_story"].get("segments_complete", 0)

        # Segment 1 (or first segment of resume)
        if segments_done == 0:
            seg_text, _ = self._generate_segment(data, is_final=(max_segments == 1), include_choice=False, last_choice="")
            await self.capability_worker.speak(seg_text)
            segments_done = 1
            data.setdefault("current_story", {})["segments_complete"] = 1
            self._save_checkpoint(data, seg_text, "")

        # Segment 2 with optional choice (for ages 6+, 3-segment stories)
        if segments_done == 1 and max_segments >= 3:
            seg_text, choice_q = self._generate_segment(
                data, is_final=False, include_choice=use_choice, last_choice=""
            )
            await self.capability_worker.speak(seg_text)

            if choice_q:
                await self.capability_worker.speak(choice_q)
                reply = await self.capability_worker.user_response()

                if not reply or self._is_exit(reply):
                    await self.capability_worker.speak(
                        f"We'll pick up right here tomorrow night. Sweet dreams, {child_name}."
                    )
                    self._save_checkpoint(data, seg_text, "")
                    return

                last_choice = reply.strip()
                data["current_story"]["choices_made"] = data["current_story"].get("choices_made", []) + [last_choice]

            segments_done = 2
            data["current_story"]["segments_complete"] = 2
            self._save_checkpoint(data, seg_text, last_choice)

        # Final segment
        final_text, _ = self._generate_segment(
            data, is_final=True, include_choice=False, last_choice=last_choice
        )
        await self.capability_worker.speak(final_text)
        await self.capability_worker.speak(
            f"The end. Sweet dreams, {child_name}. "
            f"{hero_name}'s next adventure will be waiting for you tomorrow night."
        )

        self._archive_story(data)
        self.worker.editor_logging_handler.info(f"[BedtimeStories] Story complete for {child_name}")

    # ------------------------------------------------------------------
    # Setup flow
    # ------------------------------------------------------------------

    async def _handle_setup(self, data: dict):
        await self.capability_worker.speak(
            "Hi! I'm your personal storyteller. What's your name?"
        )
        name_reply = await self.capability_worker.user_response()
        if not name_reply:
            await self.capability_worker.speak("Come back when you're ready for a story. Goodnight!")
            return

        child_name = name_reply.strip().split()[0].capitalize()

        await self.capability_worker.speak(f"Hi {child_name}! How old are you?")
        age_reply = await self.capability_worker.user_response()
        child_age = self._extract_age(age_reply or "7")

        await self.capability_worker.speak(f"And {child_name}, what's your favourite animal or magical creature?")
        fav_reply = await self.capability_worker.user_response()
        favorites = (fav_reply or "dragon").strip()

        self.worker.editor_logging_handler.info(f"[BedtimeStories] Setup: {child_name}, age {child_age}, loves {favorites}")

        hero = self._generate_hero(child_name, child_age, favorites)

        data.update({
            "child_name": child_name,
            "child_age": child_age,
            "hero_name": hero["hero_name"],
            "hero_description": hero["hero_description"],
            "universe": hero["universe"],
            "current_story": None,
            "story_history": [],
        })
        self._save_data(data)

        await self.capability_worker.speak(
            f"Perfect! Your hero is {hero['hero_name']} — {hero['hero_description']}. "
            f"Get cozy, {child_name}. Your first adventure starts now."
        )

        await self._tell_story(data)

    # ------------------------------------------------------------------
    # Continue existing story
    # ------------------------------------------------------------------

    async def _handle_continue(self, data: dict):
        child_name = data["child_name"]
        hero_name = data["hero_name"]
        checkpoint = data["current_story"].get("checkpoint", f"{hero_name} was on an adventure")

        await self.capability_worker.speak(
            f"Welcome back, {child_name}! Last night, {checkpoint}. "
            f"Let's see what happens next."
        )
        await self._tell_story(data)

    # ------------------------------------------------------------------
    # Start new story
    # ------------------------------------------------------------------

    async def _handle_new_story(self, data: dict):
        child_name = data["child_name"]
        hero_name = data["hero_name"]
        history = data.get("story_history", [])

        if history:
            last_summary = history[-1]["summary"]
            await self.capability_worker.speak(
                f"A new adventure for {child_name}! Last time, {last_summary}. "
                f"Tonight, {hero_name} is heading somewhere completely new. Get cozy."
            )
        else:
            await self.capability_worker.speak(
                f"A brand new adventure, {child_name}! {hero_name} is ready. Get cozy."
            )

        data["current_story"] = {
            "checkpoint": "",
            "segments_complete": 0,
            "choices_made": [],
            "complete": False,
            "date": datetime.now().strftime("%Y-%m-%d"),
        }
        self._save_data(data)

        await self._tell_story(data)

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    async def _run(self):
        try:
            trigger = await self.capability_worker.wait_for_complete_transcription()
            self.worker.editor_logging_handler.info(f"[BedtimeStories] Trigger: {trigger!r}")

            data = self._load_data()

            if not data.get("hero_name"):
                await self._handle_setup(data)
                return

            intent = self._classify_intent(trigger or "")
            self.worker.editor_logging_handler.info(f"[BedtimeStories] Intent: {intent}")

            if intent == "EXIT":
                await self.capability_worker.speak(
                    f"Goodnight, {data['child_name']}. Sweet dreams."
                )
                return

            has_incomplete = (
                data.get("current_story")
                and not data["current_story"].get("complete")
            )

            if has_incomplete and intent != "NEW":
                await self._handle_continue(data)
            else:
                await self._handle_new_story(data)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[BedtimeStories] Error: {e!r}")
            await self.capability_worker.speak("Something went wrong. Try again in a moment.")
        finally:
            self.capability_worker.resume_normal_flow()
