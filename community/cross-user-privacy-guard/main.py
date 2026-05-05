"""Cross User Privacy Guard — hotword-triggered Skill that intercepts
cross-user inquiry phrases ("tell me about Freddie", "what does Maya
like", "who is Bob", "the previous user") and refuses programmatically
via direct ``speak()``, bypassing the Personality LLM entirely.

This is the *deterministic* layer of the multi-user privacy contract.
The complementary BG daemon **Privacy And User Manager** owns the
*structural* layer — keeping all per-user data in non-auto-injected
JSON so other users' notes never reach the prompt files. But session
memory inside the Personality's conversation history is OUT of the
daemon's control, so a same-session cross-user query (Freddie speaks,
then Maya asks about Freddie) can still leak via that channel. This
Skill closes that hole: hotword match → Skill takes the turn → direct
TTS refusal → ``resume_normal_flow()``. The Personality never sees the
turn, so its session memory becomes irrelevant.

Hotwords are deliberately broad: many of them ("tell me about", "who
is") will fire on perfectly innocent queries like "tell me about the
weather" or "who is the president". The Skill handles that by trying
to extract a person-name from the trigger phrase. If none is found, or
if the extracted name matches the active user, it falls through to the
Personality. Refusal only fires when a name distinct from the active
user is detected, OR when an explicit "previous user" / "other user"
phrase appears.

Reads:
- ``active_user_context.md`` (written by Privacy And User Manager) —
  to find the current active user.
- ``recent_chat.md`` (written by Privacy And User Manager) — fallback
  message recovery when ``worker.current_transcript`` and
  ``agent_memory`` are empty (common on this OpenHome build).

Writes: nothing. Just speaks the refusal.
"""

import re

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

ACTIVE_USER_FILE = "active_user_context.md"
RECENT_CHAT_FILE = "recent_chat.md"

REFUSAL_SENTENCE = (
    "That's another user's private information — I can't share it with you."
)

# Tokens that *look like* names captured by the regex but obviously aren't.
# When the captured group is one of these, fall through to the Personality
# rather than refusing. "me/myself/i/us" mean self-reference; the rest are
# generic English filler that shouldn't trigger cross-user logic.
NAME_BLACKLIST = {
    "a", "an", "the", "my", "your", "his", "her", "their", "our",
    "i", "me", "you", "he", "she", "they", "we", "us",
    "myself", "yourself", "himself", "herself", "themselves", "ourselves",
    "yes", "no", "ok", "okay", "sure", "yeah", "nope",
    "user", "users", "person", "people", "someone", "anyone",
    "everybody", "nobody",
    # Domain words that often follow "tell me about ..." but aren't users.
    "weather", "news", "time", "date", "today", "tomorrow", "yesterday",
    "this", "that",
}

# Self-reference tokens. If the captured name normalizes into one of these,
# the user is asking about themselves — let the Personality handle naturally.
SELF_TOKENS = {"me", "myself", "i", "us", "ourselves"}

# Patterns to extract a queried-about name. Order matters: the more specific
# patterns come first so we don't fall through to the loose "about <Name>"
# match before trying the strong "tell me about <Name>" form.
QUERIED_NAME_PATTERNS = [
    re.compile(
        r"\b(?:tell me about|tell me what you know about|"
        r"what do you know about|info about|info on|"
        r"anything about|do you know about|any info on|"
        r"any news on|news on|who is)\s+([A-Za-z]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwhat does\s+([A-Za-z]+)\s+(?:like|prefer|want|do|need|say|think|know)",
        re.IGNORECASE,
    ),
    re.compile(r"\babout\s+([A-Za-z]+)", re.IGNORECASE),
]

# Catch-all phrases that imply a cross-user query without naming anyone.
# When any of these match the trigger text, we refuse directly — the user
# is asking about a different active-session participant by indirect
# reference, not by name.
PREV_USER_PATTERNS = [
    re.compile(
        r"\b(?:the previous user|the other user|the person before(?: me)?|"
        r"who was here before|anyone else (?:here|talking)|earlier user|"
        r"the last user)\b",
        re.IGNORECASE,
    ),
]


class CrossUserPrivacyGuardCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    #{{register capability}}

    def call(self, worker: AgentWorker):
        try:
            self.worker = worker
            # CapabilityWorker(self) — same shape used by Multi-User Speaker
            # ID and the Privacy And User Manager daemon.
            self.capability_worker = CapabilityWorker(self)
            self.worker.editor_logging_handler.info(
                "[CUPG] Cross-user privacy guard triggered"
            )
            self.worker.session_tasks.create(self._run())
        except Exception as e:
            try:
                self.worker.editor_logging_handler.error(
                    "[CUPG] call() error: %s" % e
                )
            except Exception:
                pass

    async def _run(self):
        try:
            await self._handle()
        except Exception as e:
            self.worker.editor_logging_handler.error(
                "[CUPG] handler error: %s" % e
            )
        finally:
            # Always release the turn back to the Personality so we don't
            # leave the agent stuck if anything went sideways above.
            self.capability_worker.resume_normal_flow()

    async def _handle(self):
        text = await self._get_trigger_text()
        if not text:
            # No recoverable trigger — speak a generic clarification so the
            # turn isn't stuck silently. resume_normal_flow() in the finally
            # of _run does NOT hand the turn back to the Personality once a
            # Skill has claimed it on this OpenHome build, so we always
            # speak SOMETHING.
            self.worker.editor_logging_handler.info(
                "[CUPG] no trigger text recoverable"
            )
            await self.capability_worker.speak(
                "Sorry, I missed that — could you say it again?"
            )
            return

        active = await self._read_active_user()
        active_key = self._normalize_name(active)

        # 1) Indirect cross-user phrasing — refuse without needing a name.
        for pat in PREV_USER_PATTERNS:
            if pat.search(text):
                self.worker.editor_logging_handler.info(
                    "[CUPG] previous-user phrase matched: %r — refusing"
                    % text[:120]
                )
                await self.capability_worker.speak(REFUSAL_SENTENCE)
                return

        # 2) Try to extract a queried name.
        queried = self._extract_name(text)
        queried_key = self._normalize_name(queried)
        is_self = bool(queried) and (queried_key in SELF_TOKENS)
        is_active = (
            bool(queried) and bool(active_key) and queried_key == active_key
        )

        # 3) Different name → cross-user query → refuse.
        if queried and not is_self and not is_active:
            self.worker.editor_logging_handler.info(
                "[CUPG] cross-user refusal: active=%r asked_about=%r"
                % (active, queried)
            )
            await self.capability_worker.speak(REFUSAL_SENTENCE)
            return

        # 4) Self-reference, or query about the active user, or hotword
        # matched a non-user query (e.g. "tell me about the weather"). The
        # Skill has claimed the turn, so we have to handle it ourselves
        # rather than waiting for the Personality. Use the LLM to compose
        # a natural reply that respects the active context (so self-queries
        # surface public notes, weather questions get weather answers, etc).
        if is_self or is_active:
            self.worker.editor_logging_handler.info(
                "[CUPG] self-query (queried=%r active=%r) — composing reply"
                % (queried, active)
            )
            await self._compose_and_speak_self_reply(text, active)
        else:
            self.worker.editor_logging_handler.info(
                "[CUPG] hotword fired without name — composing generic reply for %r"
                % text[:120]
            )
            await self._compose_and_speak_generic_reply(text, active)

    # ------------------------------------------------------------------
    # Self / generic fallthrough handlers
    # ------------------------------------------------------------------
    async def _compose_and_speak_self_reply(self, user_text: str, active: str) -> None:
        """When the user asks about themselves (or about the active user by
        name), surface their public notes naturally. Pulls
        active_user_context.md verbatim into the prompt so the LLM can use
        whatever public info is currently spliced in."""
        try:
            ctx = ""
            if await self.capability_worker.check_if_file_exists(ACTIVE_USER_FILE, False):
                ctx = await self.capability_worker.read_file(ACTIVE_USER_FILE, False)
            prompt = (
                "You are a helpful voice assistant. The active user just asked: "
                "\"%s\".\n\n"
                "Here is the current active-user context (from "
                "active_user_context.md):\n\n%s\n\n"
                "Reply naturally in 1-2 short sentences. Surface only PUBLIC "
                "info from the context (the 'Public info' section) — do NOT "
                "recite private bullets even if they appear. If the context "
                "shows 'Withheld — shared speaker mode.' for private info, "
                "honor that and don't speculate. Plain spoken English, no "
                "markdown."
            ) % (user_text, ctx)
            reply = self.capability_worker.text_to_text_response(prompt)
            reply = (reply or "").strip() or (
                "I'm not sure I have anything saved for you yet, %s. "
                "You can say 'remember' followed by a fact and I'll save it."
                % (active or "")
            ).strip()
        except Exception as e:
            self.worker.editor_logging_handler.error(
                "[CUPG] self-reply compose failed: %s" % e
            )
            reply = "I'm not sure what to share right now."
        await self.capability_worker.speak(reply)

    async def _compose_and_speak_generic_reply(self, user_text: str, active: str) -> None:
        """A hotword fired but no person-name was extracted (e.g. 'tell me
        about the weather'). The Skill has already claimed the turn, so we
        compose a normal LLM reply rather than refusing."""
        try:
            prompt = (
                "You are a helpful voice assistant. Reply naturally in 1-2 "
                "short sentences to: \"%s\". Plain spoken English, no markdown."
            ) % user_text
            reply = self.capability_worker.text_to_text_response(prompt)
            reply = (reply or "").strip() or "Could you rephrase that?"
        except Exception as e:
            self.worker.editor_logging_handler.error(
                "[CUPG] generic-reply compose failed: %s" % e
            )
            reply = "Could you rephrase that?"
        await self.capability_worker.speak(reply)

    # ------------------------------------------------------------------
    # I/O helpers
    # ------------------------------------------------------------------
    async def _get_trigger_text(self) -> str:
        """3-source fallback chain — same one Privacy And User Manager and
        Multi-User Speaker ID use, because ``worker.current_transcript`` is
        empty when a Skill is triggered on this OpenHome build."""
        try:
            t = self.worker.current_transcript or ""
            if t.strip():
                return t
        except Exception:
            pass
        try:
            history = self.worker.agent_memory.full_message_history or []
            for msg in reversed(history):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str) and content.strip():
                        return content
        except Exception:
            pass
        try:
            if await self.capability_worker.check_if_file_exists(RECENT_CHAT_FILE, False):
                content = await self.capability_worker.read_file(RECENT_CHAT_FILE, False)
                for line in reversed(content.splitlines()):
                    m = re.match(r"-\s*\*\*user:\*\*\s*(.+)", line)
                    if m:
                        return m.group(1).strip()
        except Exception:
            pass
        return ""

    async def _read_active_user(self) -> str:
        try:
            if not await self.capability_worker.check_if_file_exists(ACTIVE_USER_FILE, False):
                return ""
            content = await self.capability_worker.read_file(ACTIVE_USER_FILE, False)
            m = re.search(r"Current user:\s*\*?\*?([^*\n]+)", content)
            return m.group(1).strip() if m else ""
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Name extraction
    # ------------------------------------------------------------------
    def _extract_name(self, text: str) -> str:
        # Try every match for every pattern; return the first non-blacklisted
        # candidate. Iterating exhaustively means "tell me about my friend
        # Bob" can still surface "Bob" after "my" is rejected.
        for pat in QUERIED_NAME_PATTERNS:
            for m in pat.finditer(text):
                candidate = m.group(1).strip()
                if not candidate or len(candidate) < 2:
                    continue
                if candidate.lower() in NAME_BLACKLIST:
                    continue
                return candidate
        return ""

    @staticmethod
    def _normalize_name(s: str) -> str:
        return re.sub(r"[^a-z]", "", (s or "").lower().strip())
