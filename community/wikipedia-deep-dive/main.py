import re
from datetime import datetime, timedelta

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

WIKI_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/"
WIKI_FULL_URL = "https://en.wikipedia.org/w/api.php"
WIKI_HEADERS = {
    "User-Agent": "OpenHome-WikiDeepDive/1.0 (https://github.com/openhome-dev/abilities)"
}

# Phrases this ability recognizes as the start of a topic, e.g. "learn about black
# holes". Used only to strip the spoken phrase and isolate the topic in
# _extract_topic() below -- actual triggering is the dashboard's job (trigger words
# are configured there, not in code), so this list has no does_match() of its own to
# keep in sync with the dashboard.
HOTWORDS = {
    "learn about", "deep dive", "deep-dive",
    "teach me about", "wikipedia", "deep dive into",
    "explain in depth", "tell me about",
}

STORAGE_KEY = "wiki_deep_dive_sessions"

EXIT_WORDS = {"done", "bye", "goodbye", "stop", "exit"}
EXIT_PHRASES = ["that's all", "never mind", "all done", "close this"]

INTRO_SYSTEM_PROMPT = (
    "You are a knowledgeable teacher preparing a voice introduction. "
    "Summarize the text into exactly 2-3 natural spoken sentences. "
    "No lists, no markdown, no bullet points. Start with the most important fact."
)

DEEPER_SYSTEM_PROMPT = (
    "You are a knowledgeable teacher going deeper for a voice listener. "
    "3-4 sentences max. Build on what was already said — do not repeat the intro. "
    "Pick the most interesting, non-obvious section. No lists, no markdown."
)

INTENT_PROMPT = (
    "Classify the user's response into exactly one of these labels:\n"
    "DEEPER — they want more detail on the current topic\n"
    "RELATED — they want to hear related topics\n"
    "NEW_TOPIC:<topic> — they named a different topic to switch to (replace <topic> with it)\n"
    "SAVE — they want to save or bookmark this session\n"
    "EXIT — they want to stop\n"
    "OTHER — a question or comment about the current topic\n\n"
    "Return ONLY the label. Current topic: {topic}\n"
    "User said: {utterance}"
)


class WikiDeepDive(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self._run())

    async def _run(self):
        try:
            trigger = await self.capability_worker.wait_for_complete_transcription()
            topic = self._extract_topic(trigger)
            history = []
            depth = 0
            current_summary = ""

            if not topic:
                recent = self._get_recent_session()
                if recent:
                    confirmed = await self.capability_worker.run_confirmation_loop(
                        f"Want to continue where we left off on {recent['topic']}?"
                    )
                    if confirmed:
                        topic = recent["topic"]
                        await self.capability_worker.speak(f"Picking up on {topic}.")
                if not topic:
                    await self.capability_worker.speak("What would you like to learn about?")
                    utterance = await self.capability_worker.user_response()
                    if not utterance or self._is_exit(utterance):
                        await self.capability_worker.speak("No problem.")
                        return
                    topic = self._extract_topic(utterance) or utterance.strip()

            await self.capability_worker.speak("Looking that up.")
            summary, full_text = self._fetch_topic(topic)
            if not summary:
                await self._handle_not_found(topic)
                return

            await self.capability_worker.speak(summary)
            current_summary = summary
            history.append({"role": "assistant", "content": summary})
            depth = 1

            while True:
                await self.capability_worker.speak(
                    "Want to go deeper, explore something related, or say done?"
                )
                utterance = await self.capability_worker.user_response()
                if not utterance:
                    continue

                intent = self._classify_intent(utterance, topic)

                if intent == "EXIT":
                    self._save_session(topic, current_summary)
                    await self.capability_worker.speak("Happy learning.")
                    break

                elif intent == "DEEPER":
                    if depth >= 3:
                        await self.capability_worker.speak(
                            f"We've gone quite deep on {topic}. "
                            "Want to explore a related topic, or say done?"
                        )
                        continue
                    spoken = self._go_deeper(topic, full_text, depth, history)
                    await self.capability_worker.speak(spoken)
                    history.append({"role": "assistant", "content": spoken})
                    depth = min(depth + 1, 3)

                elif intent == "RELATED":
                    options_text = self._suggest_related(topic, history)
                    await self.capability_worker.speak(options_text)
                    choice = await self.capability_worker.user_response()
                    if choice and not self._is_exit(choice):
                        new_topic = self._extract_topic(choice) or choice.strip()
                        await self.capability_worker.speak("Looking that up.")
                        new_summary, new_full = self._fetch_topic(new_topic)
                        if new_summary:
                            topic, depth, full_text = new_topic, 1, new_full
                            current_summary = new_summary
                            await self.capability_worker.speak(new_summary)
                            history.append({"role": "assistant", "content": new_summary})
                        else:
                            await self._handle_not_found(new_topic)

                elif intent.startswith("NEW_TOPIC:"):
                    new_topic = intent[len("NEW_TOPIC:"):].strip()
                    await self.capability_worker.speak(f"Switching to {new_topic}.")
                    new_summary, new_full = self._fetch_topic(new_topic)
                    if new_summary:
                        topic, depth, full_text = new_topic, 1, new_full
                        current_summary = new_summary
                        await self.capability_worker.speak(new_summary)
                        history.append({"role": "assistant", "content": new_summary})
                    else:
                        await self._handle_not_found(new_topic)

                elif intent == "SAVE":
                    self._save_session(topic, current_summary)
                    await self.capability_worker.speak("Saved. I'll remember what we covered.")

                else:
                    answer = self.capability_worker.text_to_text_response(
                        utterance, history,
                        "Answer this question about the topic in 2-3 spoken sentences. No lists, no markdown."
                    )
                    await self.capability_worker.speak(answer)
                    history.append({"role": "assistant", "content": answer})

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[WikiDeepDive] {e}")
        finally:
            self.capability_worker.resume_normal_flow()

    # ── Wikipedia fetching ────────────────────────────────────────────────

    def _fetch_topic(self, topic: str) -> tuple:
        formatted = topic.strip().replace(" ", "_")
        try:
            resp = self.worker.session_tasks.get(
                WIKI_SUMMARY_URL + formatted,
                headers=WIKI_HEADERS,
                timeout=6,
            )
            self.worker.editor_logging_handler.info(
                f"[WikiDeepDive] summary status={resp.status_code} topic={topic}"
            )
            if resp.status_code == 200:
                data = resp.json()
                raw = data.get("extract", "").strip()
                if not raw:
                    return "", ""
                intro = self.capability_worker.text_to_text_response(
                    raw[:800], [], INTRO_SYSTEM_PROMPT
                )
                full_text = self._fetch_full_text(topic)
                return (intro or raw[:300]).strip(), full_text
            return "", ""
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[WikiDeepDive] fetch error: {e}")
            return "", ""

    def _fetch_full_text(self, topic: str) -> str:
        try:
            resp = self.worker.session_tasks.get(
                WIKI_FULL_URL,
                params={
                    "action": "query",
                    "prop": "extracts",
                    "explaintext": True,
                    "titles": topic,
                    "format": "json",
                    "exsectionformat": "plain",
                },
                headers=WIKI_HEADERS,
                timeout=8,
            )
            if resp.status_code == 200:
                pages = resp.json().get("query", {}).get("pages", {})
                for page in pages.values():
                    return page.get("extract", "")[:4000]
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[WikiDeepDive] full-text error: {e}")
        return ""

    def _search_suggestions(self, topic: str) -> list:
        try:
            resp = self.worker.session_tasks.get(
                WIKI_FULL_URL,
                params={
                    "action": "opensearch",
                    "search": topic,
                    "limit": 3,
                    "format": "json",
                },
                headers=WIKI_HEADERS,
                timeout=5,
            )
            if resp.status_code == 200:
                results = resp.json()
                return results[1] if len(results) > 1 else []
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[WikiDeepDive] search error: {e}")
        return []

    async def _handle_not_found(self, topic: str):
        suggestions = self._search_suggestions(topic)
        if suggestions:
            opts = ", ".join(suggestions[:3])
            await self.capability_worker.speak(
                f"I couldn't find that exactly. Did you mean {opts}?"
            )
        else:
            await self.capability_worker.speak(
                "I couldn't find anything on that topic. Try a different phrasing."
            )

    # ── Depth & related ──────────────────────────────────────────────────

    def _go_deeper(self, topic: str, full_text: str, depth: int, history: list) -> str:
        if depth == 1:
            source = full_text[500:2500] if len(full_text) > 500 else full_text
        else:
            source = full_text[2000:4000] if len(full_text) > 2000 else full_text

        prompt = (
            f"Topic: {topic}\n"
            f"What we've covered:\n{self._history_snippet(history)}\n\n"
            f"Wikipedia text:\n{source}"
        )
        result = self.capability_worker.text_to_text_response(prompt, history, DEEPER_SYSTEM_PROMPT)
        return (result or f"That's about as deep as I can go on {topic} right now.").strip()

    def _suggest_related(self, topic: str, history: list) -> str:
        prompt = (
            f"We've been learning about {topic}. "
            "Suggest exactly 3 closely related Wikipedia topics the user might enjoy next. "
            "Format: 'Related topics: X, Y, and Z. Which one?' — spoken English, no lists."
        )
        result = self.capability_worker.text_to_text_response(prompt, history)
        return (result or f"You might enjoy exploring topics connected to {topic}.").strip()

    # ── Intent & exit ────────────────────────────────────────────────────

    def _classify_intent(self, utterance: str, topic: str) -> str:
        prompt = INTENT_PROMPT.format(topic=topic, utterance=utterance)
        raw = self.capability_worker.text_to_text_response(prompt).strip()
        valid = {"DEEPER", "RELATED", "SAVE", "EXIT", "OTHER"}
        if raw in valid or raw.startswith("NEW_TOPIC:"):
            return raw
        t = utterance.lower()
        if self._is_exit(utterance):
            return "EXIT"
        if any(w in t for w in ("deeper", "more", "keep going", "continue", "tell me more")):
            return "DEEPER"
        if any(w in t for w in ("related", "similar", "else", "other")):
            return "RELATED"
        if "save" in t or "bookmark" in t or "remember" in t:
            return "SAVE"
        return "OTHER"

    def _is_exit(self, text: str) -> bool:
        t = text.lower().strip()
        if any(p in t for p in EXIT_PHRASES):
            return True
        words = t.split()
        return len(words) <= 2 and bool(set(words) & EXIT_WORDS)

    # ── Topic extraction ─────────────────────────────────────────────────

    def _extract_topic(self, text: str) -> str:
        cleaned = text.lower().strip()
        for hw in sorted(HOTWORDS, key=len, reverse=True):
            if hw in cleaned:
                cleaned = cleaned.replace(hw, "", 1).strip(" ,.-")
                break
        cleaned = re.sub(r"^(a|an|the)\s+", "", cleaned).strip()
        return cleaned if len(cleaned) > 2 else ""

    # ── Session storage ───────────────────────────────────────────────────

    def _save_session(self, topic: str, summary: str):
        entry = {
            "topic": topic,
            "snippet": summary[:120],
            "timestamp": datetime.now().strftime("%Y-%m-%d"),
        }
        try:
            result = self.capability_worker.create_key(STORAGE_KEY, {"sessions": [entry]})
            if not result.get("success"):
                existing = self.capability_worker.get_single_key(STORAGE_KEY) or {}
                sessions = existing.get("sessions", [])
                sessions = [s for s in sessions if s.get("topic") != topic]
                sessions.insert(0, entry)
                self.capability_worker.update_key(STORAGE_KEY, {"sessions": sessions[:5]})
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[WikiDeepDive] save error: {e!r}")

    def _get_recent_session(self) -> dict:
        try:
            stored = self.capability_worker.get_single_key(STORAGE_KEY)
            if not stored:
                return None
            sessions = stored.get("sessions", [])
            if not sessions:
                return None
            latest = sessions[0]
            ts = datetime.strptime(latest["timestamp"], "%Y-%m-%d")
            if datetime.now() - ts <= timedelta(days=7):
                return latest
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[WikiDeepDive] session read error: {e}")
        return None

    # ── Helpers ───────────────────────────────────────────────────────────

    def _history_snippet(self, history: list) -> str:
        recent = [h["content"] for h in history[-4:] if h.get("role") == "assistant"]
        return " ".join(recent)[:400]
