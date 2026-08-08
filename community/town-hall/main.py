import json
import re
from datetime import datetime
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

from .sources.registry import discover_sources
from .sources.base import CivicSource

BRIEFING_FILE = "townhall_meetings.md"  # meetings only — never legislation
LEGACY_BRIEFING_FILE = "townhall_briefing.md"  # old shared cache; deleted on fetch
TOPICS_FILE = "topic_preferences.json"
TOWNHALL_BUILD = "2026-07-30n"


def _extract_section(content: str, name: str):
    """return the ### {name} section only.
    accepts optional ' (session label)' suffix, but not ' Legislation ...'."""
    if not content or not name:
        return None
    want = " ".join((name or "").split())
    lines = content.splitlines(keepends=True)
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("### "):
            continue
        title = " ".join(stripped[4:].split())
        # meetings sections only — skip legislation headings
        if "legislation" in title.lower():
            continue
        if title == want:
            start = i
            break
        if title.startswith(want + " ("):
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        stripped = lines[j].strip()
        if stripped == "---" or stripped.startswith("### "):
            end = j
            break
    return "".join(lines[start:end])


def _section_is_valid(content: str, name: str) -> bool:
    """true when the named section exists and has no error lines."""
    section = _extract_section(content, name)
    if not section:
        return False
    data_lines = [
        line.strip()
        for line in section.split("\n")
        if line.strip() and not line.strip().startswith("#")
    ]
    if not data_lines:
        return False
    for line in data_lines:
        lowered = line.lower()
        if lowered.startswith("- error") or lowered.startswith("error"):
            return False
    return True


def _briefing_has_explicit_error(text: str) -> bool:
    for line in (text or "").splitlines():
        lowered = line.strip().lower()
        if lowered.startswith("- error") or "error fetching" in lowered:
            return True
    return False


def _briefing_is_empty_calendar(text: str) -> bool:
    """true when the briefing is valid but lists no upcoming meetings."""
    if not (text or "").strip() or _briefing_has_explicit_error(text):
        return False
    return "no upcoming" in (text or "").lower()


class TownHallCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    sources: list = []

    # {{register capability}}

    def _resolve_api_key(self, key_name: str) -> str | None:
        # try exact name plus common casing variants
        names = [key_name]
        lower = key_name.lower()
        upper = key_name.upper()
        if lower not in names:
            names.append(lower)
        if upper not in names:
            names.append(upper)

        last_err = None
        for name in names:
            try:
                key = self.capability_worker.get_api_keys(name)
            except Exception as e:
                last_err = e
                continue
            if isinstance(key, dict):
                key = (
                    key.get(name)
                    or key.get(key_name)
                    or key.get("value")
                    or key.get("api_key")
                    or key.get("key")
                )
            if isinstance(key, str) and key.strip():
                cleaned = key.strip().strip('"').strip("'")
                self.worker.editor_logging_handler.info(
                    f"{key_name} resolved via '{name}' ({len(cleaned)} chars)"
                )
                return cleaned

        if last_err:
            self.worker.editor_logging_handler.warning(
                f"{key_name} lookup raised an error: {last_err}"
            )
        self.worker.editor_logging_handler.warning(
            f"{key_name} not found via get_api_keys({names}). "
            "Declare/link this key on the Ability under Behavior → API Keys, "
            "and set the value in Settings → Third-Party Keys."
        )
        return None

    async def _load_topic_preferences(self) -> list[str]:
        """load the user's topic preferences (shared across all sources)."""
        try:
            exists = await self.capability_worker.check_if_file_exists(
                TOPICS_FILE, in_ability_directory=True
            )
            if not exists:
                return []

            content = await self.capability_worker.read_file(
                TOPICS_FILE, in_ability_directory=True
            )
            if not content:
                return []

            data = json.loads(content)
        except Exception as e:
            self.worker.editor_logging_handler.warning(
                f"topic preferences load failed: {e}"
            )
            return []

        # current format: {"topics": ["housing", "zoning"]}
        if isinstance(data, dict) and isinstance(data.get("topics"), list):
            return [t for t in data["topics"] if isinstance(t, str)]

        # legacy per-source format: {"Richmond City Council": ["housing"], ...}
        if isinstance(data, dict):
            topics = []
            for value in data.values():
                if isinstance(value, list):
                    for topic in value:
                        if isinstance(topic, str) and topic not in topics:
                            topics.append(topic)
            return topics

        return []

    async def _save_topic_preferences(self, topics: list[str]) -> None:
        """save user-level topic preferences."""
        await self.capability_worker.write_file(
            TOPICS_FILE,
            json.dumps({"topics": topics}, indent=2),
            in_ability_directory=True,
        )

    async def _bind_sources(self):
        """inject api keys, worker, and topic preferences for each source."""
        topics = await self._load_topic_preferences()

        for source in self.sources:
            # bind worker for http requests
            source.bind_worker(self.worker)

            # inject api key if needed
            key_name = source.required_api_key_name()
            if key_name:
                source.set_api_key(self._resolve_api_key(key_name))

            # same user topics applied to every source that supports filtering
            if topics:
                source.set_topic_preferences(topics)

    def _match_sources(self, phrase: str) -> list[CivicSource]:
        """sources whose keywords appear in the phrase, plus any that declare none.
        returns an empty list when the phrase names no jurisdiction."""
        phrase_lower = phrase.lower()
        matched = [
            s for s in self.sources
            if s.trigger_keywords() and any(kw in phrase_lower for kw in s.trigger_keywords())
        ]
        always_on = [s for s in self.sources if not s.trigger_keywords()]
        return matched + always_on

    async def log_gap(self, query: str, reason: str):
        gap_data = {
            "query": query,
            "reason": reason,
            "timestamp": str(datetime.now()),
        }
        await self.capability_worker.write_file(
            "knowledge_gaps.json",
            json.dumps(gap_data) + "\n",
            in_ability_directory=True,
        )

    async def write_context_file(self, filename: str, content: str):
        try:
            exists = await self.capability_worker.check_if_file_exists(
                filename, in_ability_directory=False
            )
            if exists:
                await self.capability_worker.delete_file(
                    filename, in_ability_directory=False
                )
            await self.capability_worker.write_file(
                filename, content, in_ability_directory=False
            )
        except Exception as e:
            self.worker.editor_logging_handler.warning(
                f"context file write failed for {filename}: {e}"
            )

    async def _delete_context_file(self, filename: str) -> None:
        try:
            exists = await self.capability_worker.check_if_file_exists(
                filename, in_ability_directory=False
            )
            if exists:
                await self.capability_worker.delete_file(
                    filename, in_ability_directory=False
                )
        except Exception:
            pass

    async def read_cached_briefing(self, active_sources: list[CivicSource]) -> str | None:
        """return cached meetings sections for active sources only, if all validate."""
        try:
            exists = await self.capability_worker.check_if_file_exists(
                BRIEFING_FILE, in_ability_directory=False
            )
            if not exists:
                return None
            content = await self.capability_worker.read_file(
                BRIEFING_FILE, in_ability_directory=False
            )
        except Exception as e:
            self.worker.editor_logging_handler.warning(
                f"briefing cache read failed: {e}"
            )
            return None
        if not content:
            return None
        if not all(
            _section_is_valid(content, source.get_name()) for source in active_sources
        ):
            return None
        sections = []
        for source in active_sources:
            section = _extract_section(content, source.get_name())
            if section:
                sections.append(section.strip())
        if not sections:
            return None
        return "\n\n---\n\n".join(sections)

    async def _fetch_meetings_from_source(self, source: CivicSource) -> str:
        """fetch a meetings calendar for this source."""
        try:
            try:
                updates = await source.fetch_meetings()
            except AttributeError:
                updates = await source.fetch_updates()
        except Exception as e:
            return (
                f"### {source.get_name()}\n"
                f"- Error fetching meetings: {e}\n"
                f"- TownHall build: {TOWNHALL_BUILD}\n"
                f"- Source: {source.get_source_url()}"
            )
        return (updates or "").strip()

    async def collect_briefing(
        self, active_sources: list[CivicSource], announce: bool = False
    ) -> str:
        """live-fetch meetings for active sources (never legislation)."""
        await self._bind_sources()
        # drop any prior meetings/legislation ambient cache so poison cannot linger
        await self._delete_context_file(LEGACY_BRIEFING_FILE)
        await self._delete_context_file(BRIEFING_FILE)
        source_names = ", ".join(s.get_name() for s in active_sources)
        header = (
            f"# TownHall Meetings Briefing\n"
            f"Sources: {source_names}\n"
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Build: {TOWNHALL_BUILD}\n"
        )
        sections = []
        for source in active_sources:
            if announce:
                await self.capability_worker.speak(f"Checking {source.get_name()}.")
            self.worker.editor_logging_handler.info(f"Polling source: {source.get_name()}")
            try:
                updates = await self._fetch_meetings_from_source(source)
            except Exception as e:
                self.worker.editor_logging_handler.error(
                    f"Source {source.get_name()} fetch raised: {e}"
                )
                updates = (
                    f"### {source.get_name()}\n"
                    f"- Error fetching meetings: {e}\n"
                    f"- Source: {source.get_source_url()}"
                )
            updates = (updates or "").strip()
            # canonicalize heading to the source display name
            if updates.startswith("### "):
                first, _, rest = updates.partition("\n")
                title = first[4:].strip()
                if "legislation" in title.lower():
                    # never rename a legislation heading into a meetings section
                    updates = (
                        f"### {source.get_name()}\n"
                        f"- Error fetching meetings: got a legislation heading "
                        f"instead of a meetings calendar (build {TOWNHALL_BUILD}).\n"
                        f"- Source: {source.get_source_url()}"
                    )
                else:
                    updates = f"### {source.get_name()}" + (f"\n{rest}" if rest else "")
            else:
                updates = f"### {source.get_name()}\n{updates}"
            self.worker.editor_logging_handler.info(
                f"Source {source.get_name()} returned {len(updates)} chars"
            )
            sections.append(updates)

        final_context = header + "\n" + "\n\n---\n\n".join(sections)
        try:
            if active_sources and all(
                _section_is_valid(final_context, source.get_name())
                for source in active_sources
            ):
                await self.write_context_file(BRIEFING_FILE, final_context)
        except Exception as e:
            self.worker.editor_logging_handler.warning(
                f"briefing cache update skipped: {e}"
            )
        self.worker.editor_logging_handler.info(
            f"Briefing ready ({len(final_context)} chars): {final_context[:400]}"
        )
        return final_context

    async def collect_briefing_with_keepalive(
        self, active_sources: list[CivicSource]
    ) -> str:
        """fetch while speaking short keepalives so sleep mode does not trip."""
        stop = {"done": False}

        async def _keepalive():
            # first ping after 12s — avoid extra chat turns on fast fetches
            await self.worker.session_tasks.sleep(12.0)
            while not stop["done"]:
                await self.capability_worker.speak("Still pulling updates.")
                await self.worker.session_tasks.sleep(15.0)

        self.worker.session_tasks.create(_keepalive())
        try:
            return await self.collect_briefing(active_sources, announce=False)
        finally:
            stop["done"] = True

    def _active_briefing_text(
        self, text: str, active_sources: list[CivicSource]
    ) -> str:
        """limit error checks to the active source sections."""
        parts = []
        for source in active_sources:
            section = _extract_section(text, source.get_name())
            if section:
                parts.append(section)
        return "\n".join(parts) if parts else (text or "")

    def _briefing_fail_reason(
        self, text: str, active_sources: list[CivicSource] | None = None
    ) -> str:
        """human-readable reason when a briefing cannot be spoken."""
        snip = self._error_snip(text, active_sources)
        if snip:
            return snip
        if not (text or "").strip():
            return "Briefing was empty."
        if not active_sources:
            return "No civic source matched."
        found = [
            line.strip()
            for line in (text or "").splitlines()
            if line.strip().startswith("### ")
        ]
        missing = []
        for source in active_sources:
            name = source.get_name()
            if not _extract_section(text, name):
                missing.append(name)
        if missing:
            found_note = f" Found headings: {', '.join(found)}." if found else ""
            return f"Missing section for {', '.join(missing)}.{found_note}"
        scoped = self._active_briefing_text(text, active_sources)
        preview = " ".join(
            line.strip(" -")
            for line in (scoped or "").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )[:160]
        if preview:
            return f"Briefing section was empty or invalid. {preview}"
        return "Briefing section was empty or invalid."

    def _briefing_failed(
        self, text: str, active_sources: list[CivicSource] | None = None
    ) -> bool:
        """true when active source sections are empty or errored."""
        if not (text or "").strip():
            return True
        if _briefing_has_explicit_error(text):
            # if the error is outside the active source section, still fail safe
            if not active_sources:
                return True
            for source in active_sources:
                section = _extract_section(text, source.get_name())
                if section and _briefing_has_explicit_error(section):
                    return True
                if not section:
                    return True
            return False
        if not active_sources:
            return False
        return not all(
            _section_is_valid(text, source.get_name()) for source in active_sources
        )

    def _error_snip(
        self, text: str, active_sources: list[CivicSource] | None = None
    ) -> str:
        scoped = (
            self._active_briefing_text(text, active_sources)
            if active_sources
            else (text or "")
        )
        for candidate in (scoped, text or ""):
            for line in candidate.splitlines():
                lowered = line.strip().lower()
                if lowered.startswith("- error") or "error fetching" in lowered:
                    return line.strip(" -")[:160]
        return ""

    def _data_source_label(self, text: str) -> str:
        """pull the '- Data source: ...' line so we can speak it reliably."""
        for line in (text or "").splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("- data source:"):
                return stripped.split(":", 1)[1].strip()
        return ""

    def _with_data_source(self, spoken: str, raw: str) -> str:
        label = self._data_source_label(raw)
        if not label:
            return spoken
        self.worker.editor_logging_handler.info(f"TownHall data source: {label}")
        # spoken attribution — which virginia feed was used
        return f"{spoken.rstrip()} Data source: {label}."

    def _details_prompt(self, mode: str) -> str:
        if mode == "legislation":
            return (
                "Want details on a specific item? "
                "Say the bill or ordinance name, or say done."
            )
        return (
            "Would you like details on a meeting? "
            "Say the meeting number or name, or say done."
        )

    def _anything_else_prompt(self, mode: str) -> str:
        if mode == "legislation":
            return "Anything else? Say another bill or ordinance, or say done."
        return "Anything else? Say another meeting number or name, or say done."

    def _briefing_has_numbered_meetings(self, text: str) -> bool:
        """true when the briefing lists numbered meetings to ask about."""
        if _briefing_is_empty_calendar(text):
            return False
        return bool(
            re.search(r"(?m)^\d+\.\s+", text or "")
            or re.search(r"\d+\s+upcoming meetings", text or "", flags=re.I)
        )

    def _spoken_meetings_summary(self, text: str, source_names: str) -> str | None:
        """build a short spoken summary from numbered meeting lines — no llm."""
        rows = []
        for line in (text or "").splitlines():
            # accept em dash, en dash, or hyphen between title and when
            m = re.match(
                r"^\s*(\d+)\.\s+\*\*(.+?)\*\*\s*[—–-]\s*(.+?)\s*$",
                line,
            )
            if not m:
                m = re.match(
                    r"^\s*(\d+)\.\s+(.+?)\s*[—–-]\s*(.+?)\s*$",
                    line,
                )
            if not m:
                continue
            title = m.group(2).strip().strip("*")
            when = m.group(3).strip()
            rows.append(f"{title}, {when}")
            if len(rows) >= 5:
                break
        if not rows:
            return None
        if len(rows) == 1:
            body = rows[0]
        elif len(rows) == 2:
            body = f"{rows[0]}; and {rows[1]}"
        else:
            body = "; ".join(rows[:-1]) + f"; and {rows[-1]}"
        return f"Here are upcoming meetings for {source_names}. {body}."

    def _fetch_status_snip(self, text: str) -> str:
        for line in (text or "").splitlines():
            if line.strip().lower().startswith("- fetch status:"):
                return line.strip(" -")
        return ""

    def _briefing_preview(self, text: str, limit: int = 220) -> str:
        """compact non-heading lines for spoken diagnostics."""
        parts = []
        for line in (text or "").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts.append(stripped.lstrip("- ").strip())
            if sum(len(p) for p in parts) >= limit:
                break
        preview = " ".join(parts)
        if len(preview) > limit:
            return preview[: limit - 3].rstrip() + "..."
        return preview

    def _is_new_briefing_request(self, phrase: str) -> bool:
        """true when the user is asking for a jurisdiction briefing, not an item."""
        if not self._match_sources(phrase):
            return False
        text = (phrase or "").lower().strip()
        if re.fullmatch(r"\d+", text):
            return False
        if re.fullmatch(r"(meeting|number)\s*\d+", text):
            return False
        if re.search(r"\b(ord\.?|res\.?)\s*\d", text):
            return False
        if re.search(r"\b([hs]b)\s*\d+\b", text):
            return False
        return True

    async def _offer_details_once(
        self,
        active_sources: list[CivicSource],
        mode: str,
        preamble: str | None = None,
    ) -> None:
        """briefing + details offer, then keep the mic for a few follow-ups.

        staying inside townhall prevents live web search from hijacking
        agenda/follow-up questions after we resume_normal_flow.
        """
        prompt = self._details_prompt(mode)
        spoken = f"{preamble.strip()} {prompt}" if preamble else prompt
        await self.capability_worker.speak(spoken)

        max_turns = 3
        for turn in range(max_turns):
            answer = await self.capability_worker.user_response()
            answer = (answer or "").strip()

            if self._is_done_intent(answer):
                await self.capability_worker.speak("Okay.")
                self.capability_worker.resume_normal_flow()
                return

            # "richmond city council" during a virginia follow-up → new briefing
            if self._is_new_briefing_request(answer):
                await self._handle_user_phrase(answer.lower())
                return

            if self._is_affirmative(answer):
                if mode == "legislation":
                    await self.capability_worker.speak(
                        "Which bill or ordinance? Say the name or number."
                    )
                else:
                    await self.capability_worker.speak(
                        "Which meeting number or name should I look up?"
                    )
                answer = await self.capability_worker.user_response()
                answer = (answer or "").strip()
                if self._is_done_intent(answer):
                    await self.capability_worker.speak("Okay.")
                    self.capability_worker.resume_normal_flow()
                    return
                if self._is_new_briefing_request(answer):
                    await self._handle_user_phrase(answer.lower())
                    return

            await self._handle_meeting_details(
                answer, active_sources, end_session=False
            )
            if turn + 1 < max_turns:
                await self.capability_worker.speak(self._anything_else_prompt(mode))

        self.capability_worker.resume_normal_flow()

    async def watchdog_loop(self):
        """warm cache quickly, then refresh daily."""
        await self.worker.session_tasks.sleep(3.0)
        while True:
            try:
                await self.collect_briefing(self.sources, announce=False)
            except Exception as e:
                self.worker.editor_logging_handler.error(
                    f"TownHall watchdog error: {e}"
                )
            await self.worker.session_tasks.sleep(86400.0)

    async def _capture_trigger_phrase(self) -> str:
        """the utterance that activated this ability, used to pick sources."""
        try:
            spoken = await self.capability_worker.wait_for_complete_transcription()
            return (spoken or "").strip().lower()
        except Exception as e:
            self.worker.editor_logging_handler.warning(
                f"trigger capture unavailable: {e}"
            )
            return ""

    async def _choose_sources(self, phrase: str) -> list[CivicSource]:
        """route from the trigger phrase; ask only if it names no jurisdiction."""
        active = self._match_sources(phrase)
        if active:
            self.worker.editor_logging_handler.info(
                f"Routed '{phrase}' to {', '.join(s.get_name() for s in active)}"
            )
            return active

        # keep the prompt short — don't enumerate every source (the list grows over time)
        await self.capability_worker.speak("Which briefing would you like?")
        answer = await self.capability_worker.user_response()
        if self._is_done_intent(answer):
            await self.capability_worker.speak("Okay.")
            return []
        matched = self._match_sources(answer)
        if matched:
            return matched

        # user named something we don't have yet
        await self.log_gap(answer, "No matching civic source for requested jurisdiction.")
        await self.capability_worker.speak(
            "I don't have a briefing for that yet. "
            "Try naming a supported city, county, state, or federal source, "
            "or say town hall again later as new sources are added."
        )
        return []

    def _parse_topics_from_response(self, response: str) -> list[str]:
        """extract free-form topic phrases from spoken user input."""
        text = (response or "").lower().strip()
        if not text:
            return []

        # strip common lead-ins
        for prefix in (
            "i'm interested in",
            "i am interested in",
            "interested in",
            "i care about",
            "add",
            "also add",
            "my topics are",
            "topics are",
            "topics",
        ):
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
                break

        # split on and / also / plus / commas / semicolons
        parts = re.split(r"\s*(?:,|;|\band\b|\balso\b|\bplus\b)\s*", text)

        topics = []
        skip = {"please", "thanks", "thank you", "yes", "okay", "ok", "um", "uh"}
        for part in parts:
            part = part.strip(" .!?'\"")
            part = re.sub(r"^(the|a|an|some|my)\s+", "", part)
            if not part or len(part) < 2 or part in skip:
                continue
            if part not in topics:
                topics.append(part)
        return topics

    async def _configure_topics(self) -> None:
        """interactive flow to add user-level topic preferences (shared across sources)."""
        existing = await self._load_topic_preferences()
        if existing:
            current = ", ".join(existing)
            await self.capability_worker.speak(
                f"Your current topics are {current}. "
                "What would you like to add? You can name anything — for example housing, "
                "zoning, parks, or climate. Say multiple topics separated by 'and'."
            )
        else:
            await self.capability_worker.speak(
                "What topics are you interested in? "
                "You can name anything — for example housing, zoning, transportation, "
                "parks, or climate. Say multiple topics separated by 'and'."
            )

        response = await self.capability_worker.user_response()
        new_topics = self._parse_topics_from_response(response)

        if not new_topics:
            await self.capability_worker.speak(
                "I didn't catch any topics. Your existing preferences are unchanged."
            )
            return

        # append new topics; keep prior ones
        merged = list(existing)
        added = []
        for topic in new_topics:
            if topic not in merged:
                merged.append(topic)
                added.append(topic)

        if not added:
            await self.capability_worker.speak(
                "Those topics are already on your list. No changes made."
            )
            return

        await self._save_topic_preferences(merged)
        self._apply_topics_to_sources(merged)

        added_list = ", ".join(added)
        all_list = ", ".join(merged)
        await self.capability_worker.speak(
            f"Added {added_list}. I'll prioritize {all_list} across your civic briefings."
        )

    def _apply_topics_to_sources(self, topics: list[str]) -> None:
        """push the current user topic list into every registered source."""
        for source in self.sources:
            source.set_topic_preferences(topics)

    async def _remove_topics(self) -> None:
        """interactive flow to remove topics from the user's preference list."""
        existing = await self._load_topic_preferences()
        if not existing:
            await self.capability_worker.speak(
                "You don't have any topic preferences saved."
            )
            return

        current = ", ".join(existing)
        await self.capability_worker.speak(
            f"Your current topics are {current}. "
            "Which should I remove? Say the topic names, or say clear all."
        )

        response = await self.capability_worker.user_response()
        response_lower = (response or "").lower().strip()

        # wipe the whole list
        if any(
            phrase in response_lower
            for phrase in (
                "clear all",
                "clear everything",
                "remove all",
                "delete all",
                "all of them",
                "everything",
            )
        ):
            await self._save_topic_preferences([])
            self._apply_topics_to_sources([])
            await self.capability_worker.speak("Cleared all topic preferences.")
            return

        to_remove = self._parse_topics_from_response(response)
        if not to_remove:
            await self.capability_worker.speak(
                "I didn't catch which topics to remove. Your list is unchanged."
            )
            return

        removed = []
        remaining = []
        for topic in existing:
            if topic in to_remove:
                removed.append(topic)
            else:
                remaining.append(topic)

        if not removed:
            await self.capability_worker.speak(
                "None of those matched your saved topics. Your list is unchanged."
            )
            return

        await self._save_topic_preferences(remaining)
        self._apply_topics_to_sources(remaining)

        removed_list = ", ".join(removed)
        if remaining:
            await self.capability_worker.speak(
                f"Removed {removed_list}. I'll prioritize {', '.join(remaining)} across your civic briefings."
            )
        else:
            await self.capability_worker.speak(
                f"Removed {removed_list}. You have no topic preferences left."
            )

    def _is_done_intent(self, phrase: str) -> bool:
        """true when the user declines details or wants to end."""
        text = (phrase or "").lower().strip()
        if not text:
            return True
        # "no. thank you" / "i'm done." → "no thank you" / "i'm done"
        text = re.sub(r"[.!?,;:]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        done_phrases = (
            "done",
            "i'm done",
            "im done",
            "i am done",
            "that's all",
            "thats all",
            "that is all",
            "nothing",
            "no thanks",
            "no thank you",
            "no thankyou",
            "thank you",
            "thanks",
            "stop",
            "bye",
            "goodbye",
            "never mind",
            "nevermind",
            "no",
            "nope",
            "nah",
            "all good",
            "i'm good",
            "im good",
        )
        if text in done_phrases:
            return True
        if any(text.startswith(p + " ") for p in done_phrases):
            return True
        # "no thank you very much" / "thanks that's all"
        if text.startswith("no ") and ("thank" in text or "thanks" in text):
            return True
        if text.startswith("thanks") or text.startswith("thank you"):
            return True
        return False

    def _is_affirmative(self, phrase: str) -> bool:
        text = (phrase or "").lower().strip()
        if not text:
            return False
        yes_words = ("yes", "yeah", "yep", "sure", "please", "ok", "okay", "affirmative")
        return text in yes_words or any(text.startswith(w + " ") for w in yes_words)

    def _is_legislation_intent(self, phrase: str) -> bool:
        """true for a full legislation list request (not a specific item lookup)."""
        text = (phrase or "").lower().strip()
        # specific file numbers are details, not a full list
        if re.search(r'\b(ord\.?|res\.?)\s*\d', text):
            return False
        if re.search(r'\b([hs]b)\s*\d+\b', text):
            return False
        list_markers = (
            "legislation",
            "pending legislation",
            "new legislation",
            "any legislation",
            "recent legislation",
            "the legislation",
            "new bills",
            "pending bills",
            "any bills",
            "ordinances and resolutions",
        )
        if any(marker in text for marker in list_markers):
            return True
        return text in (
            "bills",
            "bill",
            "ordinances",
            "ordinance",
            "resolutions",
            "resolution",
        )

    def _is_details_intent(self, phrase: str) -> bool:
        text = (phrase or "").lower()
        if re.search(r'\b(ord\.?|res\.?)\s*\d', text):
            return True
        if re.search(r'\b([hs]b)\s*\d+\b', text):
            return True
        details_keywords = (
            'details', 'detail', 'tell me about', 'about meeting',
            'meeting', 'agenda', 'more about', 'what about',
            'ordinance', 'resolution',
        )
        return any(kw in text for kw in details_keywords)

    async def _speak_and_maybe_end(self, end_session: bool) -> None:
        if end_session:
            self.capability_worker.resume_normal_flow()

    async def _handle_legislation_request(
        self,
        active_sources: list[CivicSource],
    ) -> str | None:
        """fetch legislation and return a spoken summary, or speak an error and return None."""
        await self._bind_sources()
        for source in active_sources:
            try:
                leg_info = await source.fetch_legislation()
            except Exception as e:
                self.worker.editor_logging_handler.error(f"Legislation fetch error: {e}")
                await self.capability_worker.speak(
                    f"I couldn't fetch legislation for {source.get_name()} right now."
                )
                return None

            if self._briefing_failed(leg_info):
                snip = self._error_snip(leg_info)
                msg = (
                    f"I couldn't reach legislation data for {source.get_name()} right now."
                )
                if snip:
                    msg = f"{msg} {snip}."
                await self.capability_worker.speak(msg)
                await self.log_gap(source.get_name(), "Legislation fetch returned error.")
                return None

            return self._with_data_source(
                self.capability_worker.text_to_text_response(
                    "You are summarizing pending legislation from an official feed. "
                    "Using ONLY the info below, provide a clear spoken summary. "
                    "Mention the total count, lead with any items marked as matching "
                    "the user's topics, then highlight 3-5 interesting items. "
                    "If there are no items, say that clearly. "
                    "Do not invent access problems when the list is simply empty. "
                    "Do not mention the data source line — it is added separately. "
                    "Do not ask follow-up questions. Do not suggest searching the web. "
                    "Keep it conversational for a smart speaker.\n\n"
                    f"LEGISLATION INFO:\n{leg_info}"
                ),
                leg_info,
            )
        return None

    async def _handle_meeting_details(
        self,
        phrase: str,
        active_sources: list[CivicSource],
        end_session: bool = True,
    ) -> bool:
        """handle meeting / item detail requests. returns True if handled."""
        if self._is_done_intent(phrase):
            await self.capability_worker.speak("Okay.")
            await self._speak_and_maybe_end(end_session)
            return True

        meeting_ref = None

        number_match = re.search(r'(?:meeting|number)\s*(\d+)', phrase)
        if number_match:
            meeting_ref = number_match.group(1)

        if not meeting_ref:
            standalone_match = re.search(r'details?\s+(?:on|for|about)?\s*(\d+)', phrase)
            if standalone_match:
                meeting_ref = standalone_match.group(1)

        if not meeting_ref:
            cleaned = re.sub(
                r'(tell me about|details? (?:on|for|about)|is there an agenda|'
                r'agenda for|meeting|more about|what about|the)\s*',
                '',
                phrase,
                flags=re.IGNORECASE,
            )
            if cleaned.strip() and len(cleaned.strip()) > 2:
                meeting_ref = cleaned.strip()

        if not meeting_ref:
            await self.capability_worker.speak(
                "I didn't catch which meeting or item you want details for. "
                "Try saying the meeting number like 'details on meeting 1'."
            )
            await self._speak_and_maybe_end(end_session)
            return True

        await self._bind_sources()
        for source in active_sources:
            try:
                details = await source.get_details(meeting_ref)
                lowered = (details or "").lower()
                if "could not find" in lowered or "not yet implemented" in lowered:
                    # speak feed errors plainly — llm was inventing other states' agendas
                    plain = " ".join(
                        line.strip(" -")
                        for line in (details or "").splitlines()
                        if line.strip() and not line.strip().startswith("#")
                    )
                    await self.capability_worker.speak(plain or "I couldn't find that item.")
                else:
                    summary = self.capability_worker.text_to_text_response(
                        "You are summarizing a civic meeting agenda or legislation item "
                        "from an official government feed. "
                        "Using ONLY the details below, provide a clear spoken summary. "
                        "Mention the name, full date including year when present, time, "
                        "location, and any agenda or notes. "
                        "If agenda or notes are missing, say they are not in the official "
                        "feed yet — do not invent an agenda or borrow another state's info. "
                        "Do not ask follow-up questions. Do not suggest searching the web. "
                        "End after the facts.\n\n"
                        f"DETAILS:\n{details}"
                    )
                    await self.capability_worker.speak(summary)

            except Exception as e:
                self.worker.editor_logging_handler.error(f"Details fetch error: {e}")
                await self.capability_worker.speak(
                    f"I couldn't fetch those details right now. {str(e)[:100]}"
                )

            await self._speak_and_maybe_end(end_session)
            return True

        return True

    async def _handle_user_phrase(self, phrase: str) -> None:
        """route one user phrase to meetings, legislation, or details."""
        phrase = (phrase or "").strip().lower()

        if self._is_done_intent(phrase) and not self._match_sources(phrase):
            await self.capability_worker.speak("Okay.")
            self.capability_worker.resume_normal_flow()
            return

        if 'configure' in phrase or 'set topics' in phrase:
            await self._configure_topics()
            self.capability_worker.resume_normal_flow()
            return

        if (
            'remove topics' in phrase
            or 'delete topics' in phrase
            or 'clear topics' in phrase
            or (('remove' in phrase or 'delete' in phrase) and 'topic' in phrase)
        ):
            await self._remove_topics()
            self.capability_worker.resume_normal_flow()
            return

        active_sources = await self._choose_sources(phrase)
        if not active_sources:
            self.capability_worker.resume_normal_flow()
            return

        if self._is_legislation_intent(phrase):
            summary = await self._handle_legislation_request(active_sources)
            if summary:
                await self._offer_details_once(
                    active_sources, mode="legislation", preamble=summary
                )
            else:
                self.capability_worker.resume_normal_flow()
            return

        # only treat as item-details when not a fresh jurisdiction ask
        if self._is_details_intent(phrase) and not self._is_new_briefing_request(phrase):
            await self._handle_meeting_details(phrase, active_sources, end_session=True)
            return

        source_names = ", ".join(s.get_name() for s in active_sources)
        try:
            briefing = await self.collect_briefing_with_keepalive(active_sources)
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"TownHall briefing fetch error: {e}"
            )
            detail = str(e).strip().replace("\n", " ")[:120]
            msg = "I couldn't reach the civic sources right now."
            if detail:
                msg = f"{msg} {detail}."
            await self.capability_worker.speak(msg)
            self.capability_worker.resume_normal_flow()
            return

        if self._briefing_failed(briefing, active_sources):
            reason = self._briefing_fail_reason(briefing, active_sources)
            preview = self._briefing_preview(
                self._active_briefing_text(briefing, active_sources)
            )
            self.worker.editor_logging_handler.error(
                f"TownHall briefing failed: {reason} | preview={(briefing or '')[:400]}"
            )
            msg = (
                f"I couldn't reach the meetings calendar for {source_names} right now. "
                f"Build {TOWNHALL_BUILD}."
            )
            if reason:
                msg = f"{msg} {reason}"
            if preview and preview not in msg:
                msg = f"{msg} Preview: {preview}"
            await self.capability_worker.speak(msg)
            for source in active_sources:
                await self.log_gap(source.get_name(), "Source returned no usable data.")
            self.capability_worker.resume_normal_flow()
            return

        active_text = self._active_briefing_text(briefing, active_sources)
        if _briefing_is_empty_calendar(active_text):
            label = self._data_source_label(briefing)
            status = self._fetch_status_snip(active_text)
            msg = (
                f"There are no upcoming meetings on the calendar for "
                f"{source_names} right now."
            )
            if status:
                msg = f"{msg} {status}."
            if label:
                msg = f"{msg} Data source: {label}."
            await self.capability_worker.speak(msg)
            self.capability_worker.resume_normal_flow()
            return

        spoken = self._spoken_meetings_summary(active_text, source_names)
        if spoken:
            summary = self._with_data_source(spoken, briefing)
            await self._offer_details_once(
                active_sources, mode="meeting", preamble=summary
            )
            return

        status = self._fetch_status_snip(active_text) or self._error_snip(
            briefing, active_sources
        )
        preview = self._briefing_preview(active_text)
        msg = (
            f"I couldn't load upcoming meetings for {source_names} right now. "
            f"Build {TOWNHALL_BUILD}."
        )
        if status:
            msg = f"{msg} {status}."
        if preview:
            msg = f"{msg} Preview: {preview}"
        else:
            msg = f"{msg} Briefing had no usable meeting lines."
        self.worker.editor_logging_handler.error(
            f"TownHall no meetings to speak | preview={(active_text or '')[:500]}"
        )
        await self.capability_worker.speak(msg)
        self.capability_worker.resume_normal_flow()

    async def run(self):
        phrase = await self._capture_trigger_phrase()
        await self._handle_user_phrase(phrase)

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.sources = discover_sources()
        # note: _bind_sources is now async and called in collect_briefing
        self.worker.session_tasks.create(self.watchdog_loop())
        self.worker.session_tasks.create(self.run())
