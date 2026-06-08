import requests
from datetime import datetime, timezone

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

STORAGE_KEY = "clinical_trial_data"
CLINICALTRIALS_URL = "https://clinicaltrials.gov/api/v2/studies"
CT_HEADERS = {"User-Agent": "OpenHome-ClinicalTrialFinder/1.0"}

HOTWORDS = {
    "clinical trial", "clinical study", "medical trial", "medical study",
    "research trial", "research study", "find a trial", "find trials",
    "trial for", "trials for", "enroll in a study", "join a study",
    "join a trial", "trial near", "trials near", "participate in a study",
}

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "that's all"}

INTENT_PROMPT = """Classify the user's input into exactly one of these intents:
SEARCH      - searching for trials for a condition or disease
DETAILS     - asking for more information about a specific trial (by number or "this one")
ELIGIBILITY - asking about requirements, who can join, age limits, criteria
CONTACT     - asking how to contact a trial or get phone/email
SAVE        - wanting to save or bookmark a trial to their watchlist
MORE        - asking to see more results or next page
EXIT        - done, stop, quit, goodbye

Return ONLY the intent label. Input: {text}"""

EXTRACT_CONDITION_PROMPT = (
    "Extract ONLY the medical condition or disease name from this text: '{text}'. "
    "Reply with the condition name only — no extra words, no punctuation. "
    "If no condition is mentioned, reply NONE."
)

EXTRACT_LOCATION_PROMPT = (
    "Extract ONLY the city and/or state or country from this text: '{text}'. "
    "Reply in 'City, State' or 'City, Country' format. "
    "If no location is mentioned, reply NONE."
)

EXTRACT_TRIAL_NUMBER_PROMPT = (
    "The user said: '{text}'. They are referring to one of a numbered list of trials. "
    "Extract ONLY the number they mentioned (1, 2, 3, 4, or 5). "
    "Reply with just the digit. If unclear, reply 1."
)

TRIAL_SUMMARY_PROMPT = (
    "Summarise this clinical trial in exactly 2 spoken sentences for a voice assistant. "
    "Sentence 1: what the trial is studying. "
    "Sentence 2: who can join, including age range if available. "
    "No markdown. Plain spoken English. Trial data: {data}"
)

ELIGIBILITY_PROMPT = (
    "Summarise these eligibility criteria in 2 spoken sentences for a voice assistant. "
    "Include the age requirement and the 2 most important inclusion or exclusion criteria. "
    "No markdown. Plain spoken English. Criteria: {criteria}"
)


def _empty_data() -> dict:
    return {
        "watchlist": [],
        "saved_conditions": [],
        "preferred_location": "",
    }


class ClinicalTrialFinderCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    _last_results: list = []
    _active_trial: dict = {}
    _next_page_token: str = ""
    _last_condition: str = ""
    _last_location: str = ""

    # Do not change following tag of register capability
    # {{register capability}}

    def does_match(self, text: str) -> bool:
        t = text.lower().strip()
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
            return _empty_data()
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[ClinicalTrials] Load error: {e!r}")
            return _empty_data()

    def _save_data(self, data: dict):
        try:
            self.capability_worker.create_key(STORAGE_KEY, data)
        except Exception:
            try:
                self.capability_worker.update_key(STORAGE_KEY, data)
            except Exception as e:
                self.worker.editor_logging_handler.error(f"[ClinicalTrials] Save error: {e!r}")

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------

    def _search_trials(self, condition: str, location: str = "", page_token: str = "") -> dict:
        params = {
            "query.cond": condition,
            "filter.overallStatus": "RECRUITING",
            "pageSize": 5,
            "format": "json",
        }
        if location:
            params["query.locn"] = location
        if page_token:
            params["pageToken"] = page_token
        try:
            resp = requests.get(CLINICALTRIALS_URL, params=params, headers=CT_HEADERS, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[ClinicalTrials] Search error: {e!r}")
        return {}

    def _parse_trials(self, raw: dict) -> list:
        studies = []
        for s in raw.get("studies", []):
            ps = s.get("protocolSection", {})
            id_mod = ps.get("identificationModule", {})
            status_mod = ps.get("statusModule", {})
            design_mod = ps.get("designModule", {})
            cond_mod = ps.get("conditionsModule", {})
            elig_mod = ps.get("eligibilityModule", {})
            desc_mod = ps.get("descriptionModule", {})
            contacts_mod = ps.get("contactsLocationsModule", {})

            locations = contacts_mod.get("locations", [])
            loc_parts = []
            if locations:
                first = locations[0]
                city = first.get("city", "")
                state = first.get("state", "")
                country = first.get("country", "")
                loc_parts = [p for p in [city, state or country] if p]

            contacts = contacts_mod.get("centralContacts", [])
            contact = contacts[0] if contacts else {}

            studies.append({
                "nct_id": id_mod.get("nctId", ""),
                "title": id_mod.get("briefTitle", "Unknown trial"),
                "status": status_mod.get("overallStatus", ""),
                "phases": design_mod.get("phases", []),
                "conditions": cond_mod.get("conditions", []),
                "location_str": ", ".join(loc_parts) if loc_parts else "location not listed",
                "location_count": len(locations),
                "min_age": elig_mod.get("minimumAge", ""),
                "max_age": elig_mod.get("maximumAge", ""),
                "eligibility": elig_mod.get("eligibilityCriteria", ""),
                "summary": desc_mod.get("briefSummary", ""),
                "contact_name": contact.get("name", ""),
                "contact_phone": contact.get("phone", ""),
                "contact_email": contact.get("email", ""),
            })
        return studies

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------

    def _classify_intent(self, text: str) -> str:
        raw = self.capability_worker.text_to_text_response(INTENT_PROMPT.format(text=text))
        result = raw.strip().upper().split()[0]
        valid = {"SEARCH", "DETAILS", "ELIGIBILITY", "CONTACT", "SAVE", "MORE", "EXIT"}
        return result if result in valid else "SEARCH"

    def _extract_condition(self, text: str) -> str:
        raw = self.capability_worker.text_to_text_response(
            EXTRACT_CONDITION_PROMPT.format(text=text)
        ).strip()
        return "" if raw.upper() == "NONE" or not raw else raw

    def _extract_location(self, text: str) -> str:
        raw = self.capability_worker.text_to_text_response(
            EXTRACT_LOCATION_PROMPT.format(text=text)
        ).strip()
        return "" if raw.upper() == "NONE" or not raw else raw

    def _extract_trial_number(self, text: str) -> int:
        raw = self.capability_worker.text_to_text_response(
            EXTRACT_TRIAL_NUMBER_PROMPT.format(text=text)
        ).strip()
        try:
            n = int(raw)
            return n if 1 <= n <= 5 else 1
        except (ValueError, TypeError):
            return 1

    def _summarise_trial(self, trial: dict) -> str:
        data = {
            "title": trial["title"],
            "summary": trial["summary"][:600] if trial["summary"] else "No summary available.",
            "min_age": trial["min_age"],
            "max_age": trial["max_age"],
            "conditions": trial["conditions"],
        }
        return self.capability_worker.text_to_text_response(
            TRIAL_SUMMARY_PROMPT.format(data=data)
        )

    def _summarise_eligibility(self, trial: dict) -> str:
        criteria = trial.get("eligibility", "")
        if not criteria:
            age_str = ""
            if trial["min_age"]:
                age_str = f"Minimum age {trial['min_age']}"
            if trial["max_age"]:
                age_str += f", maximum age {trial['max_age']}"
            return age_str or "Eligibility details are not available for this trial."
        return self.capability_worker.text_to_text_response(
            ELIGIBILITY_PROMPT.format(criteria=criteria[:800])
        )

    # ------------------------------------------------------------------
    # Voice output helpers
    # ------------------------------------------------------------------

    def _speak_results(self, trials: list) -> str:
        if not trials:
            return "No recruiting trials found."
        lines = []
        for i, t in enumerate(trials, 1):
            loc = t["location_str"]
            extra = f" and {t['location_count'] - 1} other sites" if t["location_count"] > 1 else ""
            lines.append(f"Trial {i}: {t['title']}, located in {loc}{extra}.")
        return " ".join(lines)

    # ------------------------------------------------------------------
    # Main flow
    # ------------------------------------------------------------------

    async def _run(self):
        try:
            trigger = await self.capability_worker.wait_for_complete_transcription()
            self.worker.editor_logging_handler.info(f"[ClinicalTrials] Trigger: {trigger!r}")

            data = self._load_data()

            condition = self._extract_condition(trigger or "")
            location = self._extract_location(trigger or "")

            if not location and data.get("preferred_location"):
                location = data["preferred_location"]

            if not condition:
                reply = await self.capability_worker.run_io_loop(
                    "What condition or disease are you searching for?"
                )
                if not reply or any(w in reply.lower() for w in EXIT_WORDS):
                    return
                condition = self._extract_condition(reply)
                if not condition:
                    condition = reply.strip()


            self._last_condition = condition
            self._last_location = location

            await self.capability_worker.speak(
                f"Searching for recruiting trials for {condition}"
                + (f" near {location}" if location else "") + ". One moment."
            )

            raw = self._search_trials(condition, location)
            self._last_results = self._parse_trials(raw)
            self._next_page_token = raw.get("nextPageToken", "")

            if not self._last_results:
                await self.capability_worker.speak(
                    f"I couldn't find any recruiting trials for {condition}"
                    + (f" near {location}" if location else "")
                    + ". Try a broader condition name or a different location."
                )
                return

            self._active_trial = self._last_results[0]
            await self.capability_worker.speak(self._speak_results(self._last_results))
            await self.capability_worker.speak(
                "Say a number to hear details, 'requirements' for eligibility, "
                "'contact' for contact info, 'save' to add to your watchlist, "
                "'more' for next page, or 'done' to exit."
            )

            while True:
                reply = await self.capability_worker.user_response()
                if not reply or any(w in reply.lower() for w in EXIT_WORDS):
                    break

                intent = self._classify_intent(reply)
                self.worker.editor_logging_handler.info(f"[ClinicalTrials] Intent: {intent}")

                if intent == "EXIT":
                    break

                elif intent == "SEARCH":
                    new_cond = self._extract_condition(reply)
                    new_loc = self._extract_location(reply)
                    if new_cond:
                        condition = new_cond
                        self._last_condition = condition
                    if new_loc:
                        location = new_loc
                        self._last_location = location
                    await self.capability_worker.speak(
                        f"Searching for {condition}"
                        + (f" near {location}" if location else "") + "."
                    )
                    raw = self._search_trials(condition, location)
                    self._last_results = self._parse_trials(raw)
                    self._next_page_token = raw.get("nextPageToken", "")
                    if not self._last_results:
                        await self.capability_worker.speak("No recruiting trials found for that search.")
                        continue
                    self._active_trial = self._last_results[0]
                    await self.capability_worker.speak(self._speak_results(self._last_results))

                elif intent == "DETAILS":
                    n = self._extract_trial_number(reply)
                    if n <= len(self._last_results):
                        self._active_trial = self._last_results[n - 1]
                    summary = self._summarise_trial(self._active_trial)
                    await self.capability_worker.speak(summary)

                elif intent == "ELIGIBILITY":
                    elig = self._summarise_eligibility(self._active_trial)
                    await self.capability_worker.speak(elig)

                elif intent == "CONTACT":
                    t = self._active_trial
                    if t.get("contact_name") or t.get("contact_phone") or t.get("contact_email"):
                        parts = []
                        if t["contact_name"]:
                            parts.append(f"Contact {t['contact_name']}")
                        if t["contact_phone"]:
                            parts.append(f"phone {t['contact_phone']}")
                        if t["contact_email"]:
                            parts.append(f"email {t['contact_email']}")
                        await self.capability_worker.speak(". ".join(parts) + ".")
                    else:
                        await self.capability_worker.speak(
                            f"No direct contact listed. Visit clinicaltrials.gov and search "
                            f"{t.get('nct_id', 'the trial')} for details."
                        )

                elif intent == "SAVE":
                    t = self._active_trial
                    data = self._load_data()
                    watchlist = data.get("watchlist", [])
                    if any(w["nct_id"] == t["nct_id"] for w in watchlist):
                        await self.capability_worker.speak("That trial is already in your watchlist.")
                    else:
                        watchlist.append({
                            "nct_id": t["nct_id"],
                            "title": t["title"],
                            "condition": self._last_condition,
                            "status": t["status"],
                            "saved_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        })
                        data["watchlist"] = watchlist
                        saved_conds = data.get("saved_conditions", [])
                        if self._last_condition and self._last_condition not in saved_conds:
                            saved_conds.append(self._last_condition)
                            data["saved_conditions"] = saved_conds
                        if self._last_location and not data.get("preferred_location"):
                            data["preferred_location"] = self._last_location
                        self._save_data(data)
                        await self.capability_worker.speak(
                            f"Saved. I'll alert you weekly if the status of "
                            f"{t['title'][:60]} changes."
                        )

                elif intent == "MORE":
                    if not self._next_page_token:
                        await self.capability_worker.speak("No more results for this search.")
                        continue
                    raw = self._search_trials(
                        self._last_condition, self._last_location, self._next_page_token
                    )
                    self._last_results = self._parse_trials(raw)
                    self._next_page_token = raw.get("nextPageToken", "")
                    if not self._last_results:
                        await self.capability_worker.speak("No more results found.")
                        continue
                    self._active_trial = self._last_results[0]
                    await self.capability_worker.speak(self._speak_results(self._last_results))

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[ClinicalTrials] Error: {e!r}")
            await self.capability_worker.speak("Something went wrong. Please try again in a moment.")
        finally:
            self.capability_worker.resume_normal_flow()
