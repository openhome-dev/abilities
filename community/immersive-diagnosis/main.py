import asyncio
import json
import re
from datetime import datetime, timezone
from time import time

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

from .playbook_registry import classify_issue_type, get_playbook
from .playbook_base import (
    OUTCOME_ESCALATE,
    OUTCOME_RESOLVED,
    OUTCOME_UNSAFE,
    URGENCY_EMERGENCY,
    URGENCY_ROUTINE,
    append_unique,
    empty_session,
    merge_observation,
    merge_troubleshoot,
)

# =============================================================================
# immersive-diagnosis — playbook-driven home diagnostic Ability
# =============================================================================

REQUESTS_FILE = "immersive_requests.json"
LEGACY_REQUESTS_FILE = "immersive_open_requests.json"
BACKEND_URL_KEY = "immersive_backend_url"          # Settings -> API Keys
API_KEY_NAME = "immersive_api_key"                 # optional
REQUEST_TIMEOUT = 10
HANDOFF_TRIGGER_LINE = (
    "Say find me a technician to see who's available now."
)

# Trigger phrases carry no diagnostic content — never treat them as the
# complaint, or the playbook skips its questions.
CONTENTLESS_TRIGGERS = {
    "home help",
    "diagnose my home",
    "diagnose this",
    "i have a problem",
    "something's broken",
    "somethings broken",
}

EXIT_WORDS = (
    "done",
    "stop",
    "quit",
    "exit",
    "goodbye",
    "bye",
    "cancel",
    "that's all",
    "thats all",
    "i'm good",
    "im good",
    "nothing else",
    "never mind",
    "nevermind",
)

EXTRACT_PROMPT = """Extract home-maintenance details from speech for a diagnostic assistant.
Return ONLY valid JSON:
{"category":"hvac|plumbing|electrical|appliance|other|null",
 "issue_type":"ac_not_cooling|null",
 "asset_type":"split_ac|window_ac|central|null",
 "location":"string|null",
 "symptoms":["..."],
 "safety_clear":true|false|null,
 "safety_flag_detail":"string|null",
 "power_on":true|false|null,
 "mode":"cool|heat|fan|null",
 "set_temperature":"string|null",
 "airflow_strength":"weak|strong|null",
 "filter_condition":"dirty|clean|null",
 "filter_cleaned":true|false|null,
 "airflow_after_cleaning":"improved|same|null",
 "cooling_after_cleaning":true|false|null,
 "outdoor_unit_running":true|false|null,
 "ice_present":true|false|null,
 "duration":"string|null",
 "already_tried":"string|null",
 "description":"string|null",
 "affirmative":true|false|null,
 "negative":true|false|null,
 "done":true|false|null,
 "is_exit":false,
 "wants_pro":false,
 "is_clarification":false}

Rules:
- Only fill fields you are confident about from the text.
- is_clarification true if they ask to repeat or did not answer the question.
- Never invent facts. Use null when unknown.
- No markdown.
"""

REPLY_EXTRACT_PROMPT = """You map a user's spoken reply to structured diagnostic fields.
Context: the assistant is waiting for "{awaiting}".
Return ONLY valid JSON with any relevant keys from:
safety_clear, safety_flag_detail, power_on, mode, set_temperature, airflow_strength,
filter_condition, filter_cleaned, airflow_after_cleaning, cooling_after_cleaning,
outdoor_unit_running, ice_present, duration, already_tried, description, location,
affirmative, negative, done, is_clarification, wants_pro.

Use null for unknown. is_clarification=true if they did not answer (e.g. "sorry, repeat").
No markdown.
"""


class ImmersiveDiagnosisCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    session: dict = None
    playbook: object = None

    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.session = empty_session()
        self.playbook = None  # active playbook module
        self.worker.session_tasks.create(self.run())

    # ── logging ─────────────────────────────────────────────────────────

    def _log(self, level: str, msg: str) -> None:
        text = f"[immersive-diagnosis] {msg}"
        handler = self.worker.editor_logging_handler
        if level == "error":
            handler.error(text)
        elif level == "warning":
            handler.warning(text)
        else:
            handler.info(text)

    def _is_exit(self, text: str) -> bool:
        # Short ambiguous words ("stop", "done") only match as a whole word
        # (so "yeah, stop" still exits but "my AC stopped cooling" — the
        # core diagnosis use case — does not false-trigger on "stopped").
        # Distinctive multi-word phrases ("that's all", "i'm good") still
        # match anywhere in the reply.
        lower = (text or "").lower().strip().rstrip(".!?")
        if not lower:
            return False
        tokens = set(lower.split())
        return any((word in lower if " " in word else word in tokens) for word in EXIT_WORDS)

    def _strip_fences(self, text: str) -> str:
        raw = (text or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        return raw.strip()

    def _llm_json(self, prompt: str, system_prompt: str) -> dict | None:
        try:
            raw = self.capability_worker.text_to_text_response(
                prompt,
                system_prompt=system_prompt,
            )
            parsed = json.loads(self._strip_fences(raw))
            if isinstance(parsed, dict):
                return parsed
            self._log("error", f"LLM JSON was not an object: {raw!r}")
            return None
        except Exception as exc:
            self._log("error", f"LLM JSON parse failed: {exc!r}")
            return None

    # ── persistence (shared with immersive-provider / feedback) ─────────

    def _normalize_request(self, item: dict) -> dict:
        summary = item.get("diagnostic_summary") or item.get("description") or ""
        symptoms = item.get("symptoms") or []
        if isinstance(symptoms, str):
            symptoms = [symptoms]
        return {
            "id": item.get("id"),
            "created_at": item.get("created_at"),
            "category": item.get("category") or "other",
            "description": summary
            or (symptoms[0] if symptoms else "Home maintenance issue"),
            "issue_type": item.get("issue_type"),
            "asset_type": item.get("asset_type"),
            "location": item.get("location"),
            "symptoms": symptoms,
            "safety_flags": item.get("safety_flags") or [],
            "observations": item.get("observations") or [],
            "troubleshooting_attempted": item.get("troubleshooting_attempted") or [],
            "urgency": item.get("urgency"),
            "diagnostic_summary": summary or None,
            "possible_causes_for_technician": item.get(
                "possible_causes_for_technician"
            )
            or item.get("possible_causes")
            or [],
            "status": item.get("status") or "open",
            "duration": item.get("duration"),
            "safety": item.get("safety"),
            "already_tried": item.get("already_tried"),
            "booked_provider": item.get("booked_provider"),
        }

    async def _read_raw_requests_file(self, filename: str) -> list:
        if not await self.capability_worker.check_if_file_exists(filename, False):
            return []
        try:
            raw = await self.capability_worker.read_file(filename, False)
            if not (raw or "").strip():
                return []
            data = json.loads(raw)
            if isinstance(data, dict) and isinstance(data.get("requests"), list):
                items = data["requests"]
            elif isinstance(data, list):
                items = data
            else:
                return []
            return [
                self._normalize_request(item)
                for item in items
                if isinstance(item, dict)
            ]
        except Exception as exc:
            self._log("error", f"Failed to read {filename}: {exc!r}")
            return []

    async def _load_requests(self) -> list:
        """Load open+all requests from shared file; migrate legacy file if needed."""
        requests = await self._read_raw_requests_file(REQUESTS_FILE)
        if requests:
            return requests
        legacy = await self._read_raw_requests_file(LEGACY_REQUESTS_FILE)
        if legacy:
            self._log("info", f"Migrating {len(legacy)} request(s) from legacy file")
            await self._save_requests(legacy)
            return legacy
        return []

    async def _save_requests(self, requests: list) -> bool:
        """Write provider-compatible envelope: {\"requests\": [...]}."""
        payload = json.dumps({"requests": requests}, ensure_ascii=False, indent=2)
        try:
            if await self.capability_worker.check_if_file_exists(REQUESTS_FILE, False):
                await self.capability_worker.delete_file(REQUESTS_FILE, False)
            await self.capability_worker.write_file(REQUESTS_FILE, payload, False)
            return True
        except Exception as exc:
            self._log("error", f"Failed to write {REQUESTS_FILE}: {exc!r}")
            return False

    # ── listen ──────────────────────────────────────────────────────────

    async def _listen(self) -> str | None:
        user_input = await self.capability_worker.user_response()
        if not user_input or not str(user_input).strip():
            self.session["idle_empty"] += 1
            if self.session["idle_empty"] >= 2:
                leave = await self.capability_worker.run_confirmation_loop(
                    "Still there? Say yes to keep going, or no to stop."
                )
                self.session["idle_empty"] = 0
                if not leave:
                    return "__exit__"
            return None
        self.session["idle_empty"] = 0
        text = str(user_input).strip()
        if self._is_exit(text):
            return "__exit__"
        return text

    # ── extract / classify ──────────────────────────────────────────────

    def _history_text(self) -> str:
        try:
            history = self.capability_worker.get_full_message_history() or []
        except Exception as exc:
            self._log("warning", f"Could not read history: {exc!r}")
            return ""
        parts = []
        for msg in history[-12:]:
            if isinstance(msg, dict):
                role = msg.get("role", "")
                content = msg.get("content", "")
                parts.append(f"{role}: {content}")
            else:
                parts.append(str(msg))
        return "\n".join(parts)

    def _seed_from_complaint(self, complaint: str, extract: dict | None) -> None:
        self.session["initial_complaint"] = complaint
        self._log("info", f"Initial user complaint: {complaint}")

        cat, issue = classify_issue_type(complaint)
        if extract:
            if extract.get("category"):
                cat = extract["category"] or cat
            if extract.get("issue_type"):
                issue = extract["issue_type"] or issue
            if extract.get("asset_type"):
                self.session["asset_type"] = extract["asset_type"]
            if extract.get("location"):
                self.session["location"] = extract["location"]
            for s in extract.get("symptoms") or []:
                append_unique(self.session["symptoms"], s)
            if extract.get("description") and not self.session["symptoms"]:
                append_unique(self.session["symptoms"], extract["description"])
            if extract.get("safety_clear") is False:
                append_unique(
                    self.session["safety_flags"],
                    extract.get("safety_flag_detail") or "Safety concern in opening complaint",
                )

        if not self.session["symptoms"] and complaint:
            append_unique(self.session["symptoms"], complaint)

        self.session["category"] = cat or (extract or {}).get("category")
        self.session["issue_type"] = issue or (extract or {}).get("issue_type") or "generic"
        if self.session["issue_type"] != "ac_not_cooling" and not issue:
            self.session["issue_type"] = "generic"

        self._log("info", f"Detected category: {self.session['category']}")
        self._log("info", f"Detected issue type: {self.session['issue_type']}")

        self.playbook = get_playbook(self.session["issue_type"])
        try:
            playbook_name = self.playbook.ISSUE_TYPE
        except Exception:
            playbook_name = self.session["issue_type"]
        self.session["active_playbook"] = playbook_name
        self.session["playbook_state"] = self.playbook.initial_state()
        self._log("info", f"Selected diagnostic playbook: {self.session['active_playbook']}")

        # Seed AC playbook fields from extract
        if extract and playbook_name == "ac_not_cooling":
            self.playbook.seed_from_extract(self.session["playbook_state"], extract)

        # Seed generic description/location/duration
        state = self.session["playbook_state"]
        if self.session["active_playbook"] == "generic":
            if self.session.get("location"):
                state["location"] = self.session["location"]
            if extract and extract.get("description"):
                state["description"] = extract["description"]
            elif complaint:
                state["description"] = complaint
            if extract and extract.get("duration"):
                state["duration"] = extract["duration"]
            if extract and extract.get("already_tried"):
                state["already_tried"] = extract["already_tried"]

    def _merge_obs(self, base: dict, extra: dict | None) -> dict:
        if not extra:
            return base
        out = dict(base)
        for key, val in extra.items():
            if val is None:
                continue
            if out.get(key) is None:
                out[key] = val
        return out

    def _interpret(self, text: str) -> dict:
        """LLM-first observation extract; keywords fill gaps and catch clarifications."""
        state = self.session["playbook_state"]
        awaiting = state.get("awaiting") or state.get("phase") or ""

        kw = self.playbook.interpret_reply_keywords(text, awaiting)
        if kw.get("is_clarification"):
            self._log("info", "User observation extracted: clarification (re-ask)")
            return kw

        llm = self._llm_json(
            f"Awaiting: {awaiting}\nUser said: {text}",
            REPLY_EXTRACT_PROMPT.replace("{awaiting}", str(awaiting)),
        )
        if llm and llm.get("is_clarification"):
            self._log("info", "User observation extracted: clarification via LLM")
            return {"is_clarification": True}

        # Keywords first for crisp yes/no, then LLM fills the rest
        obs = self._merge_obs(kw, llm)

        if llm:
            if llm.get("mode") == "cool":
                obs["mode_cool"] = True
            if llm.get("safety_clear") is False:
                obs["safety_flag"] = True
                if llm.get("safety_flag_detail"):
                    obs["safety_flag_detail"] = llm["safety_flag_detail"]
            if llm.get("filter_cleaned") is True:
                obs["done"] = True
                obs["affirmative"] = True
            if llm.get("cooling_after_cleaning") is False:
                obs["still_not_cooling"] = True
            if llm.get("cooling_after_cleaning") is True:
                obs["cooling_fixed"] = True
            if llm.get("airflow_after_cleaning") in ("improved", "strong"):
                obs["airflow_improved"] = True

        # Continuous safety scan
        lower = text.lower()
        if any(
            p in lower
            for p in ("burning", "smoke", "sparking", "sparks", "gas smell", "shock")
        ):
            if not any(p in lower for p in ("no burning", "no smoke", "no spark")):
                if awaiting != "safety" or obs.get("safety_clear") is not True:
                    obs["safety_flag"] = True
                    obs["safety_flag_detail"] = "Safety signal in user reply"
                    obs["safety_clear"] = False

        self._log(
            "info",
            f"User observation extracted: {json.dumps(obs, ensure_ascii=False)}",
        )
        return obs

    def _apply_step_result(self, result) -> None:
        for note in result.observations_added:
            merge_observation(self.session, note)
        for step in result.troubleshooting_added:
            merge_troubleshoot(self.session, step)
        if result.possible_causes:
            self.session["possible_causes"] = list(result.possible_causes)
        if result.diagnostic_summary:
            self.session["diagnostic_summary"] = result.diagnostic_summary
        if result.urgency:
            self.session["urgency"] = result.urgency
        self._log(
            "info",
            f"Current diagnostic state: phase={self.session['playbook_state'].get('phase')} "
            f"awaiting={self.session['playbook_state'].get('awaiting')} "
            f"outcome={result.outcome}",
        )
        if self.session.get("safety_flags") or self.session["playbook_state"].get(
            "safety_clear"
        ) is False:
            self._log("info", f"Safety state: flags={self.session['safety_flags']}")

    # ── service request ─────────────────────────────────────────────────

    def _emergency_category(self) -> str:
        """Prefer electrical when sparking/burning; else keep session category."""
        blob = " ".join(
            [
                " ".join(self.session.get("safety_flags") or []),
                " ".join(self.session.get("observations") or []),
                self.session.get("initial_complaint") or "",
            ]
        ).lower()
        if any(
            p in blob
            for p in ("spark", "burning", "smoke", "wire", "electrical", "shock")
        ):
            return "electrical"
        return self.session.get("category") or "hvac"

    def _build_request(self, urgency: str) -> dict:
        summary = self.session.get("diagnostic_summary") or (
            self.session.get("initial_complaint") or "Home maintenance issue"
        )
        symptoms = list(self.session.get("symptoms") or [])
        pb_state = self.session.get("playbook_state") or {}
        request = {
            "id": f"req_{int(time())}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "category": (
                self._emergency_category()
                if urgency == URGENCY_EMERGENCY
                else (self.session.get("category") or "other")
            ),
            "description": summary,
            "issue_type": self.session.get("issue_type"),
            "asset_type": self.session.get("asset_type"),
            "location": self.session.get("location") or pb_state.get("location"),
            "symptoms": symptoms,
            "safety_flags": list(self.session.get("safety_flags") or []),
            "observations": list(self.session.get("observations") or []),
            "troubleshooting_attempted": list(
                self.session.get("troubleshooting_attempted") or []
            ),
            "urgency": urgency,
            "diagnostic_summary": summary,
            "possible_causes_for_technician": list(
                self.session.get("possible_causes") or []
            ),
            "status": "open",
        }
        if pb_state.get("duration"):
            request["duration"] = pb_state["duration"]
        if pb_state.get("already_tried"):
            request["already_tried"] = pb_state["already_tried"]
        return request

    def _post_request_to_backend(self, request: dict) -> dict | None:
        """Blocking POST to the marketplace backend (run via asyncio.to_thread).
        Tries the configured base and base + /api. Returns the created request
        (with the backend's id) or None."""
        try:
            base = (self.capability_worker.get_api_keys(BACKEND_URL_KEY) or "").strip().rstrip("/")
        except Exception:
            base = ""
        if not base:
            return None
        candidates = [base] if base.endswith("/api") else [base, base + "/api"]
        try:
            api_key = self.capability_worker.get_api_keys(API_KEY_NAME)
        except Exception:
            api_key = None
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        for candidate in candidates:
            try:
                response = requests.post(
                    f"{candidate}/requests", json=request, headers=headers,
                    timeout=REQUEST_TIMEOUT,
                )
                if response.status_code not in (200, 201):
                    continue
                data = response.json()
            except ValueError:
                continue
            except Exception as exc:
                self._log("error", f"Backend POST via {candidate} failed: {exc!r}")
                continue
            return data.get("request") or request
        return None

    async def _persist_request(self, request: dict) -> bool:
        # Backend first: the live marketplace generates quotes, the daemon
        # announces them, and the provider skill reads from there.
        created = await asyncio.to_thread(self._post_request_to_backend, request)
        if created:
            request.update({k: v for k, v in created.items() if v is not None})
            self._log("info", f"Service request created on backend: {request['id']}")
            self._log("info", f"Escalation reason: {request.get('diagnostic_summary')}")
            return True

        # Fallback: shared local file (provider/feedback skills read it when
        # the backend is unreachable).
        stored = await self._load_requests()
        stored.append(request)
        ok = await self._save_requests(stored)
        if ok:
            self._log("info", f"Service request saved locally: {request['id']}")
            self._log("info", f"Escalation reason: {request.get('diagnostic_summary')}")
        return ok

    async def _create_request(self, *, skip_confirm: bool = False) -> bool:
        urgency = self.session.get("urgency") or URGENCY_ROUTINE
        if not skip_confirm:
            confirmed = await self.capability_worker.run_confirmation_loop(
                "Shall I create a service request with what we found?"
            )
            if not confirmed:
                await self.capability_worker.speak("Okay, I won't save a request.")
                return False

        request = self._build_request(urgency)
        ok = await self._persist_request(request)
        if ok:
            await self.capability_worker.speak(
                "Saved. You can say check my quotes later when providers reply."
            )
        else:
            await self.capability_worker.speak(
                "I couldn't save the request right now. Try again later."
            )
        return ok

    async def _offer_request_once(self) -> bool:
        """Speak nothing extra — one confirmation, then save."""
        return await self._create_request(skip_confirm=False)

    async def _handle_unsafe_handoff(self) -> None:
        """Emergency path: confirm technician search, save request, speak trigger."""
        self.session["urgency"] = URGENCY_EMERGENCY
        want_tech = await self.capability_worker.run_confirmation_loop(
            "Want me to find an emergency technician for you?"
        )
        if want_tech:
            request = self._build_request(URGENCY_EMERGENCY)
            ok = await self._persist_request(request)
            if ok:
                await self.capability_worker.speak(HANDOFF_TRIGGER_LINE)
                self._log("info", "Emergency handoff spoken: find me a technician")
            else:
                await self.capability_worker.speak(
                    "I couldn't save the request. Call emergency services if needed, "
                    "then say find me a technician when you're ready."
                )
            return

        # Declined technician search — still offer to save the request quietly
        save_anyway = await self.capability_worker.run_confirmation_loop(
            "Should I still save a service request for later?"
        )
        if save_anyway:
            request = self._build_request(URGENCY_EMERGENCY)
            if await self._persist_request(request):
                await self.capability_worker.speak(
                    "Saved. Say find me a technician anytime you want help booking."
                )
            else:
                await self.capability_worker.speak(
                    "Okay. Stay safe — call emergency services if anything worsens."
                )
        else:
            await self.capability_worker.speak(
                "Okay. Stay safe — call emergency services if anything worsens."
            )

    # ── playbook loop ───────────────────────────────────────────────────

    async def _run_playbook(self) -> str:
        """Run active playbook. Returns resolved|escalated|unsafe|exit."""
        result = self.playbook.prompt_for_state(self.session["playbook_state"])
        self._apply_step_result(result)

        if result.outcome == OUTCOME_UNSAFE:
            for flag in result.observations_added:
                append_unique(self.session["safety_flags"], flag)
            await self.capability_worker.speak(result.speak[:280])
            await self._handle_unsafe_handoff()
            return "unsafe"

        if result.outcome == OUTCOME_RESOLVED:
            await self.capability_worker.speak(result.speak[:280])
            return "resolved"

        if result.outcome == OUTCOME_ESCALATE:
            await self.capability_worker.speak(result.speak[:280])
            await self._offer_request_once()
            return "escalated"

        await self.capability_worker.speak(result.speak[:280])

        while True:
            text = await self._listen()
            if text is None:
                continue
            if text == "__exit__":
                return "exit"

            obs = self._interpret(text)
            if obs.get("is_clarification"):
                again = self.playbook.prompt_for_state(self.session["playbook_state"])
                await self.capability_worker.speak(again.speak[:280])
                continue

            if obs.get("safety_flag"):
                append_unique(
                    self.session["safety_flags"],
                    obs.get("safety_flag_detail") or "Safety concern mentioned",
                )
                self._log("info", "Safety state: red flag during playbook")

            result = self.playbook.apply_reply(self.session["playbook_state"], obs)
            self._apply_step_result(result)

            if result.outcome == OUTCOME_UNSAFE:
                await self.capability_worker.speak(result.speak[:280])
                await self._handle_unsafe_handoff()
                return "unsafe"

            if result.outcome == OUTCOME_RESOLVED:
                await self.capability_worker.speak(result.speak[:280])
                return "resolved"

            if result.outcome == OUTCOME_ESCALATE:
                await self.capability_worker.speak(result.speak[:280])
                await self._offer_request_once()
                return "escalated"

            await self.capability_worker.speak(result.speak[:280])

    # ── main ────────────────────────────────────────────────────────────

    async def run(self):
        try:
            self._log("info", "ABILITY STARTED")

            # Message history persists across sessions, so only trust the last
            # user line when it reads like a fresh, substantive complaint —
            # otherwise a stale reply ("yes", "stop") from an earlier session
            # would seed the playbook and skip every question.
            history = self._history_text()
            complaint = ""
            if history:
                for line in reversed(history.splitlines()):
                    if line.lower().startswith("user:"):
                        complaint = line.split(":", 1)[-1].strip()
                        break
            lowered = complaint.lower().strip(" .!?")
            if (
                not lowered
                or lowered in CONTENTLESS_TRIGGERS
                or len(lowered) < 15
                or self._is_exit(lowered)
            ):
                complaint = ""
            extract = None
            if complaint:
                # Extract from the complaint only — never from old history.
                extract = self._llm_json(
                    f"User said: {complaint}",
                    EXTRACT_PROMPT,
                )
            if not complaint:
                await self.capability_worker.speak(
                    "I'm here to help diagnose the home issue. What's going wrong?"
                )
                text = await self._listen()
                if text is None:
                    text = await self._listen()
                if not text or text == "__exit__":
                    await self.capability_worker.speak("Okay, we can pick this up anytime.")
                    return
                complaint = text
                extract = self._llm_json(
                    f"User said: {complaint}",
                    EXTRACT_PROMPT,
                )

            self._seed_from_complaint(complaint, extract)

            # Opening speak only if we didn't already classify AC (playbook has its own opener)
            if self.session["issue_type"] != "ac_not_cooling":
                await self.capability_worker.speak(
                    "I'm here to help diagnose the home issue — a few quick questions."
                )

            result = await self._run_playbook()
            if result == "exit":
                await self.capability_worker.speak("Okay, stopping here.")
            elif result == "resolved":
                pass  # already spoke
            elif result == "escalated":
                await self.capability_worker.speak("That's all for now.")
            elif result == "unsafe":
                await self.capability_worker.speak("Stay safe. I'm here if you need me.")

            self._log("info", "ABILITY ENDED")
        except Exception as exc:
            self._log("error", f"Unhandled error: {exc!r}")
            try:
                await self.capability_worker.speak(
                    "Something went wrong on my side. Let's try again later."
                )
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()
