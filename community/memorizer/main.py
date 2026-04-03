from typing import Optional

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


PREFERENCES_FILE = "user_preferences.md"


class PersonalityPreferencesCapability(MatchingCapability):
    worker: Optional[AgentWorker] = None
    capability_worker: Optional[CapabilityWorker] = None

    # {{register capability}}

    def _llm(self, prompt: str) -> str:
        return (self.capability_worker.text_to_text_response(prompt) or "").strip()

    def _load_preferences(self, raw: str) -> list[str]:
        prefs = []
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("- "):
                value = line[2:].strip()
                if value:
                    prefs.append(value)
        return prefs

    def _save_preferences(self, prefs: list[str]) -> str:
        if not prefs:
            return "# User Preferences\n"
        lines = ["# User Preferences", ""]
        for p in prefs:
            lines.append("- " + p)
        return "\n".join(lines) + "\n"

    async def _read_prefs(self, cw) -> list[str]:
        if await cw.check_if_file_exists(PREFERENCES_FILE, False):
            raw = await cw.read_file(PREFERENCES_FILE, False)
            return self._load_preferences(raw)
        return []

    async def _write_prefs(self, cw, prefs: list[str]):
        prefs = self._dedupe_preserve_order(prefs)
        if await cw.check_if_file_exists(PREFERENCES_FILE, False):
            await cw.delete_file(PREFERENCES_FILE, False)
        await cw.write_file(PREFERENCES_FILE, self._save_preferences(prefs), False)

    def _clean_pref(self, p: str) -> str:
        return " ".join((p or "").strip().split())

    def _dedupe_preserve_order(self, prefs: list[str]) -> list[str]:
        seen = set()
        out = []
        for p in prefs:
            cleaned = self._clean_pref(p)
            key = cleaned.lower()
            if cleaned and key not in seen:
                seen.add(key)
                out.append(cleaned)
        return out

    def _parse_bullet_list(self, raw: str) -> list[str]:
        items = []
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("- "):
                value = line[2:].strip()
                if value:
                    items.append(value)
        return items

    def _format_prefs_naturally(self, prefs: list[str]) -> str:
        cleaned = [self._clean_pref(p) for p in prefs if self._clean_pref(p)]
        if not cleaned:
            return "You haven't told me any preferences yet."

        if len(cleaned) == 1:
            return f"Here's what I know about you so far: {cleaned[0]}."

        if len(cleaned) == 2:
            return f"Here's what I know about you so far: {cleaned[0]}, and {cleaned[1]}."

        return (
            "Here's what I know about you so far: "
            + ", ".join(cleaned[:-1])
            + f", and {cleaned[-1]}."
        )

    def _split_basic_facts(self, text: str) -> list[str]:
        if not text:
            return []

        normalized = text.replace("\n", ", ")
        separators = [",", ";"]
        parts = [normalized]

        for sep in separators:
            next_parts = []
            for part in parts:
                next_parts.extend(part.split(sep))
            parts = next_parts

        final_parts = []
        for part in parts:
            subparts = part.split(" and ")
            for sub in subparts:
                cleaned = sub.strip()
                if cleaned:
                    final_parts.append(cleaned)

        return final_parts

    def _looks_like_compound_preference(self, value: str) -> bool:
        text = (value or "").lower()
        return "," in text or "; " in text or " and " in text

    def _infer_topic_key(self, entry: str) -> str:
        text = self._clean_pref(entry)
        if not text:
            return ""

        topic = self._llm(
            "Return the single best topic key for this saved user preference.\n"
            "The topic key should be short and generic, like:\n"
            "diet, age, politics, religion, favorite_color, communication_style, allergy, contact_preference, location\n"
            "Return ONLY the topic key, lowercase, with underscores if needed.\n"
            "If unsure, return general.\n\n"
            f"Preference: {text}"
        ).strip().lower()

        if not topic:
            topic = "general"

        topic = topic.replace(" ", "_")
        allowed = "abcdefghijklmnopqrstuvwxyz0123456789_"
        topic = "".join(ch for ch in topic if ch in allowed)

        return topic or "general"

    def _should_replace_existing(self, existing: str, new_entry: str) -> bool:
        existing_clean = self._clean_pref(existing)
        new_clean = self._clean_pref(new_entry)

        if not existing_clean or not new_clean:
            return False

        decision = self._llm(
            "Decide whether the new saved user preference should REPLACE the existing one.\n"
            "Reply with only YES or NO.\n\n"
            "Replace when they are about the same underlying attribute, topic, slot, or profile field, including fuzzy matches.\n"
            "Examples of same slot that should replace:\n"
            "- Liberal -> Conservative\n"
            "- Vegetarian -> Vegan\n"
            "- 19 years old -> 20 years old\n"
            "- Prefers short responses -> Prefers detailed responses\n"
            "- Favorite color is blue -> Favorite color is green\n\n"
            "Do NOT replace when both can reasonably coexist.\n"
            "Examples of coexist:\n"
            "- Vegetarian + 20 years old\n"
            "- Allergic to peanuts + Prefers short responses\n"
            "- Liberal + Vegetarian\n\n"
            f"Existing: {existing_clean}\n"
            f"New: {new_clean}"
        ).strip().upper()

        return decision.startswith("Y")

    def _merge_with_overwrite(
        self, existing_prefs: list[str], new_entries: list[str]
    ) -> tuple[list[str], list[str]]:
        prefs = self._dedupe_preserve_order(existing_prefs)
        replaced = []

        for new_entry in new_entries:
            new_clean = self._clean_pref(new_entry)
            if not new_clean:
                continue

            identical_index = None
            for i, existing in enumerate(prefs):
                if self._clean_pref(existing).lower() == new_clean.lower():
                    identical_index = i
                    break

            if identical_index is not None:
                continue

            new_topic = self._infer_topic_key(new_clean)
            replacement_index = None

            for i, existing in enumerate(prefs):
                existing_clean = self._clean_pref(existing)
                if not existing_clean:
                    continue

                existing_topic = self._infer_topic_key(existing_clean)
                same_topic = (
                    new_topic != "general"
                    and existing_topic != "general"
                    and existing_topic == new_topic
                )

                replace = same_topic or self._should_replace_existing(existing_clean, new_clean)

                if replace:
                    replacement_index = i
                    break

            if replacement_index is not None:
                old_value = prefs[replacement_index]
                if self._clean_pref(old_value).lower() != new_clean.lower():
                    replaced.append(old_value)
                    prefs[replacement_index] = new_clean
            else:
                prefs.append(new_clean)

            prefs = self._dedupe_preserve_order(prefs)

        return prefs, replaced

    async def _normalize_existing_prefs(self, cw):
        prefs = await self._read_prefs(cw)
        if not prefs:
            return

        normalized = []
        changed = False

        for pref in prefs:
            if self._looks_like_compound_preference(pref):
                split_items = self._fallback_extract_entries(pref)
                if split_items:
                    normalized.extend(split_items)
                    if len(split_items) != 1 or split_items[0].strip() != pref.strip():
                        changed = True
                else:
                    normalized.append(pref)
            else:
                normalized.append(pref)

        normalized = self._dedupe_preserve_order(normalized)

        collapsed = []
        for pref in normalized:
            collapsed, replaced = self._merge_with_overwrite(collapsed, [pref])
            if replaced:
                changed = True

        if collapsed != prefs or changed:
            await self._write_prefs(cw, collapsed)

    def _fallback_extract_entries(self, utterance: str) -> list[str]:
        text = utterance.strip()
        if not text:
            return []

        cleaned = self._llm(
            "Remove wrapper language and return only the core facts or preferences.\n"
            "Strip phrases like 'update my profile', 'add to my profile', 'remember that', "
            "'don't forget', 'keep in mind', 'save that', and similar wrappers.\n"
            "Return only the cleaned content.\n\n"
            "Examples:\n"
            "Update my profile to say that I'm vegetarian and 20 years old -> I'm vegetarian and 20 years old\n"
            "Remember that I prefer short responses -> I prefer short responses\n\n"
            "User said: " + text
        ).strip()

        if not cleaned:
            cleaned = text

        parts = self._split_basic_facts(cleaned)

        normalized = []
        for piece in parts:
            entry = self._llm(
                "Rewrite this as one short saved preference entry.\n"
                "Exactly one fact per line.\n"
                "No punctuation at the end. No extra text.\n\n"
                "Examples:\n"
                "I'm vegetarian -> Vegetarian\n"
                "I am 20 years old -> 20 years old\n"
                "I prefer short responses -> Prefers short responses\n"
                "I am liberal -> Liberal\n"
                "I am conservative -> Conservative\n\n"
                "User said: " + piece
            ).strip()
            if entry:
                normalized.append(entry)

        return self._dedupe_preserve_order(normalized)

    async def perform_action(self):
        cw = self.capability_worker

        utterance = await cw.wait_for_complete_transcription()

        await self._normalize_existing_prefs(cw)

        intent = self._llm(
            "Classify this as ADD, REVIEW, or DELETE. Reply with only that one word.\n"
            "ADD = saving a new preference or fact about the user.\n"
            "DELETE = removing or forgetting a specific preference.\n"
            "REVIEW = ONLY if the user is explicitly asking to list, enumerate, or hear everything you know about them. "
            "Phrases like 'remember that', 'don't forget', 'keep in mind', 'update my profile', or 'save that' are ADD not REVIEW. "
            "REVIEW requires clear intent like 'what do you know about me', 'list my preferences', 'what have I told you'.\n"
            "User said: " + utterance
        ).upper()

        if "REVIEW" in intent:
            prefs = await self._read_prefs(cw)
            await cw.speak(self._format_prefs_naturally(prefs))

        elif "DELETE" in intent:
            prefs = await self._read_prefs(cw)
            if not prefs:
                await cw.speak("You don't have any saved preferences to remove.")
            else:
                numbered = "\n".join(str(i + 1) + ". " + p for i, p in enumerate(prefs))
                indices_str = self._llm(
                    "The user wants to delete one or more saved preference bullets. "
                    "Each bullet is independent. "
                    "Return ONLY a comma separated list of numbers that match what they want to delete. "
                    "Use fuzzy matching by meaning. "
                    "If the user refers to one topic, remove only the matching bullet or bullets for that exact topic. "
                    "If nothing matches, return 0.\n\n"
                    "Preferences:\n" + numbered + "\n\n"
                    "User said: " + utterance
                )

                indices = []
                for part in indices_str.replace(",", " ").split():
                    if part.isdigit():
                        idx = int(part) - 1
                        if 0 <= idx < len(prefs) and idx not in indices:
                            indices.append(idx)

                if not indices:
                    await cw.speak("I couldn't find any matching preferences to remove.")
                else:
                    removed = [prefs[i] for i in indices]
                    prefs = [p for i, p in enumerate(prefs) if i not in indices]
                    prefs = self._dedupe_preserve_order(prefs)
                    await self._write_prefs(cw, prefs)

                    if len(removed) == 1:
                        await cw.speak(f"Removed {removed[0]}.")
                    elif len(removed) == 2:
                        await cw.speak(f"Removed {removed[0]} and {removed[1]}.")
                    else:
                        await cw.speak(
                            "Removed " + ", ".join(removed[:-1]) + f", and {removed[-1]}."
                        )

        else:  # ADD
            extracted = self._llm(
                "Extract all user preferences or profile facts from this message.\n"
                "Return them as a markdown bullet list.\n"
                "IMPORTANT RULES:\n"
                "- One fact or preference per bullet\n"
                "- Do not combine multiple facts into one bullet\n"
                "- Remove wrapper phrases like 'update my profile', 'remember that', 'save that', 'keep in mind'\n"
                "- Normalize wording into short saved entries\n"
                "- No duplicates inside the output\n"
                "- No commentary, only bullets\n\n"
                "Examples:\n"
                "User: Update my profile to say that I'm vegetarian\n"
                "Output:\n"
                "- Vegetarian\n\n"
                "User: Update my profile to say that I'm vegetarian, 20 years old, and I prefer short responses\n"
                "Output:\n"
                "- Vegetarian\n"
                "- 20 years old\n"
                "- Prefers short responses\n\n"
                "User: I am conservative\n"
                "Output:\n"
                "- Conservative\n\n"
                "User: Remember that I'm allergic to peanuts and prefer email over phone calls\n"
                "Output:\n"
                "- Allergic to peanuts\n"
                "- Prefers email over phone calls\n\n"
                "User said: " + utterance
            ).strip()

            new_entries = self._parse_bullet_list(extracted)

            if not new_entries:
                new_entries = self._fallback_extract_entries(utterance)

            flattened_entries = []
            for entry in new_entries:
                if self._looks_like_compound_preference(entry):
                    split_items = self._fallback_extract_entries(entry)
                    if split_items:
                        flattened_entries.extend(split_items)
                    else:
                        flattened_entries.append(entry)
                else:
                    flattened_entries.append(entry)

            new_entries = self._dedupe_preserve_order(flattened_entries)

            if not new_entries:
                await cw.speak("I couldn't figure out what preference to save.")
            else:
                prefs = await self._read_prefs(cw)
                merged_prefs, replaced = self._merge_with_overwrite(prefs, new_entries)
                await self._write_prefs(cw, merged_prefs)

                if replaced and len(new_entries) == 1:
                    await cw.speak("Got it, preference updated.")
                elif replaced:
                    await cw.speak("Got it, preferences updated.")
                elif len(new_entries) == 1:
                    await cw.speak("Got it, preference saved.")
                else:
                    await cw.speak("Got it, preferences saved.")

        cw.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.perform_action())
