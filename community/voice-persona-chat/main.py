import json
import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

STORAGE_KEY = "voice_persona_chat_prefs"
VENICE_BASE = "https://api.venice.ai/api/v1"
CHAT_MODEL = "llama-3.3-70b"

EXIT_WORDS = {"stop", "quit", "exit", "end", "bye", "goodbye", "done", "cancel"}
EXIT_PHRASES = {"that's all", "all done", "never mind", "i'm done", "no thanks"}

HOTWORDS = {
    "chat with", "talk to", "speak with", "persona chat",
    "character chat", "voice persona", "connect me to",
    "let me talk to", "conversation with",
}


class VoicePersonaChat(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    _venice_key: str = ""

    def does_match(self, text: str) -> bool:
        t = text.lower()
        return any(hw in t for hw in HOTWORDS)

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self._run())

    async def _run(self):
        try:
            trigger = (await self.capability_worker.wait_for_complete_transcription() or "").strip()

            self._venice_key = self.capability_worker.get_api_keys("venice_api_key") or ""
            if not self._venice_key:
                await self.capability_worker.speak(
                    "I need a Venice A P I key to work. "
                    "Please add it in OpenHome settings under the key name venice underscore api underscore key."
                )
                return

            personas = self._fetch_personas()
            if not personas:
                await self.capability_worker.speak(
                    "I couldn't reach the Venice character service right now. Please try again in a moment."
                )
                return

            name, slug = "", ""

            # Path 1: name found directly in the trigger utterance — fastest path
            inline_name, inline_slug = self._match_inline(trigger, personas)
            if inline_name and inline_slug:
                confirmed = await self.capability_worker.run_confirmation_loop(
                    f"Connecting you to {inline_name}. Ready?"
                )
                if confirmed:
                    name, slug = inline_name, inline_slug

            # Path 2: returning user — offer last persona
            if not slug:
                prefs = self._load_prefs()
                last_name = prefs.get("last_persona_name", "")
                last_slug = prefs.get("last_persona_slug", "")
                if last_name and last_slug and last_slug in personas.values():
                    want_last = await self.capability_worker.run_confirmation_loop(
                        f"Want to talk to {last_name} again?"
                    )
                    if want_last:
                        name, slug = last_name, last_slug

            # Path 3: full roster selection
            if not slug:
                roster_names = list(personas.keys())[:6]
                roster_spoken = ", ".join(roster_names[:-1]) + f", and {roster_names[-1]}"
                await self.capability_worker.speak(
                    f"I can connect you to {roster_spoken}. Who would you like to talk to?"
                )
                result = await self._select_persona(personas)
                if result is None:
                    await self.capability_worker.speak("No problem, see you next time!")
                    return
                name, slug = result

            self._save_prefs(slug, name)

            # Open with the character greeting the user
            opening = self._venice_chat(
                [{"role": "user", "content": "Hello! Introduce yourself in one sentence."}],
                slug,
            )
            history: list = []
            if opening:
                history = [
                    {"role": "user", "content": "Hello! Introduce yourself in one sentence."},
                    {"role": "assistant", "content": opening},
                ]
                await self.capability_worker.speak(opening)
            else:
                await self.capability_worker.speak(
                    f"Connected to {name}. Say goodbye or stop whenever you're done."
                )

            await self._chat_loop(history, slug)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[VoicePersonaChat] Error: {e}")
        finally:
            self.capability_worker.resume_normal_flow()

    # ------------------------------------------------------------------
    # Venice character roster
    # ------------------------------------------------------------------

    def _fetch_personas(self) -> dict:
        """Returns {name: slug} for the top featured non-adult characters."""
        try:
            resp = requests.get(
                f"{VENICE_BASE}/characters",
                headers={"Authorization": f"Bearer {self._venice_key}"},
                params={"sortBy": "featured", "limit": 10, "isAdult": "false"},
                timeout=10,
            )
            if resp.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"[VoicePersonaChat] Character fetch failed: {resp.status_code}"
                )
                return {}
            data = resp.json().get("data", [])
            return {
                entry["name"]: entry["slug"]
                for entry in data
                if entry.get("name") and entry.get("slug")
            }
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[VoicePersonaChat] Fetch personas error: {e}")
            return {}

    # ------------------------------------------------------------------
    # Persona selection
    # ------------------------------------------------------------------

    def _match_inline(self, trigger: str, personas: dict) -> tuple:
        """Scans trigger utterance for a known persona name. Returns (name, slug) or ('', '')."""
        t = trigger.lower()
        for name, slug in personas.items():
            if name.lower() in t:
                return name, slug
        return "", ""

    async def _select_persona(self, personas: dict) -> tuple | None:
        """Retry loop: user speaks a name, LLM fuzzy-matches it. Returns (name, slug) or None on exit."""
        for attempt in range(4):
            raw = (await self.capability_worker.user_response() or "").strip()

            if self._is_exit(raw):
                return None

            slug = self._match_persona_name(raw, personas)

            if slug == "list_roster":
                roster_names = list(personas.keys())[:6]
                roster_spoken = ", ".join(roster_names[:-1]) + f", and {roster_names[-1]}"
                await self.capability_worker.speak(f"Available: {roster_spoken}.")
                continue

            if slug:
                matched_name = next((n for n, s in personas.items() if s == slug), "")
                confirmed = await self.capability_worker.run_confirmation_loop(
                    f"You want to talk to {matched_name}?"
                )
                if confirmed:
                    return matched_name, slug

            if attempt < 3:
                await self.capability_worker.speak(
                    "I didn't catch that. Say a character name, or ask me to list them."
                )

        return None

    def _match_persona_name(self, user_input: str, personas: dict) -> str:
        """LLM fuzzy-match: returns a slug, 'list_roster', or empty string."""
        names_list = list(personas.keys())
        raw = (self.capability_worker.text_to_text_response(
            f"User said: '{user_input}'. Available characters: {json.dumps(names_list)}. "
            "If the user is asking to list or hear the characters, return: {\"match\": \"list_roster\"}. "
            "Otherwise return the closest matching character name: {\"match\": \"<name or empty string>\"}. "
            "Return ONLY valid JSON, no other text."
        ) or "").strip()

        if "```" in raw:
            parts = raw.split("```")
            raw = parts[1].lstrip("json").strip() if len(parts) > 1 else ""

        try:
            match = (json.loads(raw).get("match") or "").strip()
            if match == "list_roster":
                return "list_roster"
            return personas.get(match, "")
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Chat loop
    # ------------------------------------------------------------------

    async def _chat_loop(self, history: list, slug: str):
        while True:
            user_input = (await self.capability_worker.user_response() or "").strip()

            if not user_input:
                await self.capability_worker.speak("I didn't catch that.")
                continue

            if self._is_exit(user_input):
                farewell = self._venice_chat(
                    history + [{"role": "user", "content": "Say goodbye in character in one sentence."}],
                    slug,
                )
                if farewell:
                    await self.capability_worker.speak(farewell)
                return

            history.append({"role": "user", "content": user_input})
            reply = self._venice_chat(history, slug)

            if not reply:
                await self.capability_worker.speak("I didn't get a response. Please try again.")
                history.pop()
                continue

            history.append({"role": "assistant", "content": reply})
            await self.capability_worker.speak(reply)

    def _venice_chat(self, messages: list, slug: str) -> str:
        try:
            resp = requests.post(
                f"{VENICE_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._venice_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": CHAT_MODEL,
                    "messages": messages,
                    "venice_parameters": {"character_slug": slug},
                },
                timeout=30,
            )
            if resp.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"[VoicePersonaChat] Chat API error: {resp.status_code}"
                )
                return ""
            return (resp.json()["choices"][0]["message"]["content"] or "").strip()
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[VoicePersonaChat] Venice chat error: {e}")
            return ""

    # ------------------------------------------------------------------
    # Storage — Uzair create-first pattern
    # ------------------------------------------------------------------

    def _load_prefs(self) -> dict:
        try:
            raw = self.capability_worker.get_single_key(STORAGE_KEY)
            return raw.get("value", raw) if raw else {}
        except Exception:
            return {}

    def _save_prefs(self, slug: str, name: str):
        data = {"last_persona_slug": slug, "last_persona_name": name}
        try:
            result = self.capability_worker.create_key(STORAGE_KEY, data)
            if not (result or {}).get("success"):
                self.capability_worker.update_key(STORAGE_KEY, data)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[VoicePersonaChat] Save prefs error: {e!r}")

    # ------------------------------------------------------------------
    # Exit detection — two-tier (token match + phrase match)
    # ------------------------------------------------------------------

    def _is_exit(self, text: str) -> bool:
        if not text:
            return False
        t = text.lower().strip()
        tokens = set(t.split())
        if tokens & EXIT_WORDS:
            return True
        return any(phrase in t for phrase in EXIT_PHRASES)
