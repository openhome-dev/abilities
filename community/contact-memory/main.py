
import json
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker
from datetime import date, datetime, timedelta
import json
import re
from typing import ClassVar, Dict, List, Optional, Tuple
from pydantic import Field

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave", "that's all"}
CONTACT_FILE = "contacts.json"

CANONICAL_FIELDS = [
    "display_name",
    "name_variants",
    "company",
    "role",
    "email",
    "phone",
    "location",
    "first_met",
    "first_met_context",
    "last_contact",
    "tags",
    "notes",
]


class ContactMemoryCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    crm_detail: Dict[str, dict] = Field(default_factory=dict)
    mode: str = "quick"
    session_history: List[Dict[str, str]] = Field(default_factory=list)

    CLASSIFY_INTENT_PROMPT: ClassVar[str] = (
        "You are a personal CRM voice assistant. Classify user message. Return JSON only: "
        "{{\"intent\":\"store|retrieve|lookup|search|add_note|update|unknown\",\"mode\":\"quick|full\"}}. "
        "Use full for broad browsing/search. User: {user_input}"
    )
    EXTRACT_CONTACT_PROMPT: ClassVar[str] = (
        "Extract CRM contact JSON only with keys "
        "name,first_name,last_name,company,role,email,phone,location,context,tags,note. "
        "Normalize spoken email/phone if possible. User: {user_input}"
    )
    MATCH_CONTACT_PROMPT: ClassVar[str] = (
        "Match spoken name to known contacts. Return JSON only: "
        "{{\"matched_key\":null|\"key\",\"confidence\":0.0,\"is_new_contact\":true|false}}. "
        "Contacts: {contact_list}. Name: {spoken_name}. Context: {full_context}"
    )
    EXTRACT_NOTE_PROMPT: ClassVar[str] = (
        "Extract note command. Return JSON only: {{\"name\":null|\"person\",\"note\":\"text\"}}. "
        "If person is unclear, set name to null. User: {user_input}"
    )
    EXTRACT_UPDATE_PROMPT: ClassVar[str] = (
        "Extract CRM update command. Return JSON only with keys "
        "name,action,field,value,old_tag,new_tag,note_date,note_contains. "
        "Allowed actions: set_field,remove_contact,remove_note,replace_tag,add_tag,remove_tag,unknown. "
        "User: {user_input}"
    )
    EXTRACT_SEARCH_PROMPT: ClassVar[str] = (
        "Extract search criteria. Return JSON only: "
        "{{\"search_type\":\"company|tag|context|date|name|general\",\"search_term\":null|\"text\",\"days\":7}}. "
        "User: {user_input}"
    )
    LOOKUP_REQUEST_PROMPT: ClassVar[str] = (
        "Extract lookup request. Return JSON only: "
        "{{\"name\":null|\"text\",\"field\":\"email|phone|meeting|summary\"}}. "
        "Use meeting for schedule/check-meeting questions. "
        "Use summary for 'what do I know' style asks. User: {user_input}"
    )

    # Do not change following tag of register capability
    #{{register capability}}

    
    

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.crm_detail = {}
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    def _log_info(self, message: str):
        self.worker.editor_logging_handler.info(f"[CRMLog] {message}")

    def _log_error(self, message: str):
        self.worker.editor_logging_handler.error(f"[CRMLog] {message}")

    def _reset_session_history(self):
        self.session_history = []

    def _add_history(self, role: str, content: str):
        text = (content or "").strip()
        if not text:
            return
        self.session_history.append({"role": role, "content": text})
        if len(self.session_history) > 20:
            self.session_history = self.session_history[-20:]

    def _session_context_text(self, limit: int = 8) -> str:
        rows = []
        for item in self.session_history[-limit:]:
            rows.append(f"{item.get('role', 'user')}: {item.get('content', '')}")
        return "\n".join(rows)

    def _with_session_context(self, prompt: str) -> str:
        ctx = self._session_context_text()
        if not ctx:
            return prompt
        return f"{prompt}\n\nSession conversation context:\n{ctx}"

    def _today(self) -> str:
        return date.today().isoformat()

    def _clean_llm_json(self, response: str) -> str:
        match = re.search(r"```json\s*(.*?)\s*```", response or "", re.DOTALL)
        if match:
            return match.group(1).strip()
        return (response or "").strip().strip("`")

    def _safe_json(self, response: str, fallback: dict) -> dict:
        try:
            return json.loads(self._clean_llm_json(response))
        except Exception as e:
            self._log_error(f"Failed JSON parse: {e}; raw={(response or '')[:200]}")
            return fallback

    def _normalize_text(self, value: Optional[str]) -> str:
        return (value or "").strip().lower()

    def _normalize_email(self, email: Optional[str]) -> Optional[str]:
        if not email:
            return None
        e = self._normalize_text(email)
        e = re.sub(r"[,;:]", " ", e)
        # Spoken-email normalization.
        e = re.sub(r"\b(at|atsign)\b", "@", e)
        e = re.sub(r"\b(dot|period)\b", ".", e)
        e = re.sub(r"\b(underscore)\b", "_", e)
        e = re.sub(r"\b(dash|hyphen)\b", "-", e)
        e = e.replace("(at)", "@").replace("(dot)", ".")
        e = re.sub(r"\s+", "", e)
        e = e.strip(".,;:!?")
        if e.count("@") != 1:
            return None

        local, domain = e.split("@", 1)
        local = re.sub(r"[^a-z0-9._%+\-]", "", local).strip(".")
        domain = re.sub(r"[^a-z0-9.\-]", "", domain).strip(".-")
        if not local or not domain or "." not in domain:
            return None
        return f"{local}@{domain}"

    def _normalize_phone(self, phone: Optional[str]) -> Optional[str]:
        if not phone:
            return None
        digits = re.sub(r"[^\d+]", "", phone)
        if not digits:
            return None
        if digits.startswith("+"):
            return digits
        only_digits = re.sub(r"\D", "", digits)
        if len(only_digits) == 10:
            return f"+1{only_digits}"
        if len(only_digits) == 11 and only_digits.startswith("1"):
            return f"+{only_digits}"
        return only_digits

    def format_phone_for_speech(self, phone: str) -> str:
        digits = re.sub(r"[^\d]", "", phone or "")
        if not digits:
            return ""
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) == 10:
            area = " ".join(digits[0:3])
            prefix = " ".join(digits[3:6])
            line = " ".join(digits[6:10])
            return f"{area}. {prefix}. {line}"
        return ", ".join(list(digits))

    def format_email_for_speech(self, email: str) -> str:
        return (email or "").replace("@", " at ").replace(".", " dot ")

    def _speech_safe_text(self, text: str) -> str:
        raw = text or ""
        email_pattern = r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"

        def _replace_email(match: re.Match) -> str:
            return self.format_email_for_speech(match.group(0))

        return re.sub(email_pattern, _replace_email, raw)

    def format_date_for_speech(self, iso_date: str) -> str:
        try:
            dt = datetime.strptime(iso_date, "%Y-%m-%d")
            return dt.strftime("%B %d, %Y")
        except Exception:
            return iso_date

    def generate_contact_key(self, name: str) -> str:
        key = (name or "").lower().strip()
        key = re.sub(r"[^a-z0-9\s]", "", key)
        key = re.sub(r"\s+", "_", key)
        return key or "unknown_contact"

    def _looks_like_list_query(self, user_input: str) -> bool:
        low = self._normalize_text(user_input)
        cues = [
            "who do i know",
            "who do we know",
            "all contacts",
            "list contacts",
            "who did i meet",
            "my contacts",
            "my network",
        ]
        return any(c in low for c in cues)

    def _meeting_summary(self, contact: dict) -> str:
        name = contact.get("display_name", "This contact")
        notes = contact.get("notes", []) or []
        hits = []
        for n in notes:
            txt = self._normalize_text(n.get("text"))
            if any(x in txt for x in ["meeting", "scheduled", "rescheduled", "schedule", "call"]):
                hits.append(n)
        if not hits:
            return f"I don't see any meeting scheduled with {name} in your local CRM notes."
        last = hits[-1]
        d = last.get("date", "")
        t = last.get("text", "")
        if d:
            return f"Latest meeting note for {name} on {self.format_date_for_speech(d)}: {t}"
        return f"Latest meeting note for {name}: {t}"

    def _is_system_update_note(self, text: str) -> bool:
        t = self._normalize_text(text)
        return bool(re.match(r"^updated\s+(company|role|email|phone|location)\s*:", t))

    def _clean_first_met_context(self, context: Optional[str]) -> str:
        raw = (context or "").strip()
        if not raw:
            return ""
        low = raw.lower()
        if low.startswith("met at "):
            return raw[7:].strip()
        if low.startswith("met in "):
            return raw[7:].strip()
        if low.startswith("met on "):
            return raw[7:].strip()
        return raw

    def _build_contact_variants(self, data: dict) -> List[str]:
        variants = set()
        display = (data.get("display_name") or "").strip().lower()
        if display:
            variants.add(display)
            parts = display.split()
            variants.add(parts[0])
            if len(parts) > 1:
                variants.add(parts[-1])
        for item in data.get("name_variants", []) or []:
            v = self._normalize_text(str(item))
            if v:
                variants.add(v)
        return sorted(list(variants))

    def _contact_summary_for_match(self) -> List[dict]:
        rows = []
        for key, val in self.crm_detail.items():
            rows.append(
                {
                    "key": key,
                    "display_name": val.get("display_name"),
                    "name_variants": val.get("name_variants", []),
                    "company": val.get("company"),
                    "role": val.get("role"),
                }
            )
        return rows

    def _resolve_contact_from_utterance(self, user_input: str) -> Tuple[Optional[str], float]:
        """Fallback matcher when parsed name is missing/noisy."""
        utter = self._normalize_text(user_input)
        if not utter:
            return None, 0.0

        utter_tokens = set([t for t in re.split(r"\s+", utter) if t])
        best_key = None
        best_score = 0.0

        for key, c in self.crm_detail.items():
            names = [self._normalize_text(c.get("display_name"))]
            names += [self._normalize_text(v) for v in c.get("name_variants", [])]
            names += [key.replace("_", " ")]
            names = [n for n in names if n]

            local_best = 0.0
            for n in names:
                if n in utter:
                    local_best = max(local_best, 0.95)
                    continue
                nt = set([t for t in re.split(r"\s+", n) if t])
                if not nt:
                    continue
                inter = len(nt & utter_tokens)
                union = len(nt | utter_tokens)
                score = inter / union if union else 0.0
                if n and any(tok == n for tok in utter_tokens):
                    score = max(score, 0.85)
                local_best = max(local_best, score)

            if local_best > best_score:
                best_score = local_best
                best_key = key

        if best_score >= 0.25:
            return best_key, best_score
        return None, best_score

    def _canonicalize_contact(self, key: str, raw: dict) -> dict:
        c = dict(raw or {})
        out = {field: None for field in CANONICAL_FIELDS}

        display = c.get("display_name") or key.replace("_", " ").title()
        out["display_name"] = display
        out["name_variants"] = self._build_contact_variants(
            {"display_name": display, "name_variants": c.get("name_variants", [])}
        )
        out["company"] = c.get("company")
        out["role"] = c.get("role")
        out["email"] = self._normalize_email(c.get("email"))
        out["phone"] = self._normalize_phone(c.get("phone"))
        out["location"] = c.get("location")
        out["first_met"] = c.get("first_met") or self._today()
        out["first_met_context"] = c.get("first_met_context")
        out["last_contact"] = c.get("last_contact") or self._today()

        tags = [self._normalize_text(t) for t in c.get("tags", []) if self._normalize_text(t)]
        out["tags"] = sorted(list(set(tags)))

        notes = []
        for n in c.get("notes", []) or []:
            text = (n.get("text") or "").strip()
            if not text:
                continue
            notes.append({"date": n.get("date", self._today()), "text": text})
        out["notes"] = notes
        return out

    async def load_contact(self):
        self.crm_detail = {}
        exists = await self.capability_worker.check_if_file_exists(CONTACT_FILE, False)
        if not exists:
            return
        try:
            raw = await self.capability_worker.read_file(CONTACT_FILE, False)
            payload = json.loads(raw or "{}")
            if not isinstance(payload, dict):
                payload = {}
            self.crm_detail = {
                key: self._canonicalize_contact(key, val)
                for key, val in payload.items()
                if isinstance(val, dict)
            }
            self._log_info(f"Loaded contacts: {len(self.crm_detail)}")
        except json.JSONDecodeError:
            self._log_error("Corrupt contacts file. Resetting.")
            await self.capability_worker.delete_file(CONTACT_FILE, False)
            self.crm_detail = {}
        except Exception as e:
            self._log_error(f"load_contact error: {e}")
            self.crm_detail = {}

    async def save_contact(self):
        try:
            self.crm_detail = {
                key: self._canonicalize_contact(key, val)
                for key, val in self.crm_detail.items()
                if isinstance(val, dict)
            }
            if await self.capability_worker.check_if_file_exists(CONTACT_FILE, False):
                await self.capability_worker.delete_file(CONTACT_FILE, False)
            await self.capability_worker.write_file(
                CONTACT_FILE, json.dumps(self.crm_detail, ensure_ascii=True), False
            )
            self._log_info(f"Saved contacts: {len(self.crm_detail)}")
        except Exception as e:
            self._log_error(f"save_contact error: {e}")

    async def classify_intent(self, user_input: str) -> dict:
        try:
            prompt = self._with_session_context(self.CLASSIFY_INTENT_PROMPT.format(user_input=user_input))
            response = self.capability_worker.text_to_text_response(prompt)
            out = self._safe_json(response, {"intent": "unknown", "mode": "quick"})
            intent = out.get("intent", "unknown")
            mode = out.get("mode", "quick")
            if intent not in {"store", "retrieve", "lookup", "search", "add_note", "update", "unknown"}:
                intent = "unknown"
            if mode not in {"quick", "full"}:
                mode = "quick"
            if intent == "lookup" and self._looks_like_list_query(user_input):
                intent = "search"

            out["intent"] = intent
            out["mode"] = mode
            return out
        except Exception as e:
            self._log_error(f"classify_intent error: {e}")
            return {"intent": "unknown", "mode": "quick"}

    async def extract_contact_data(self, user_input: str) -> dict:
        prompt = self._with_session_context(self.EXTRACT_CONTACT_PROMPT.format(user_input=user_input))
        response = self.capability_worker.text_to_text_response(prompt)
        data = self._safe_json(
            response,
            {
                "name": None,
                "first_name": None,
                "last_name": None,
                "company": None,
                "role": None,
                "email": None,
                "phone": None,
                "location": None,
                "context": None,
                "tags": [],
                "note": None,
            },
        )
        data["email"] = self._normalize_email(data.get("email"))
        data["phone"] = self._normalize_phone(data.get("phone"))
        data["tags"] = [self._normalize_text(t) for t in data.get("tags", []) if self._normalize_text(t)]
        return data

    async def find_existing_contact(self, spoken_name: str, full_context: str = "") -> Tuple[Optional[str], float]:
        q = self._normalize_text(spoken_name)
        if not q:
            return None, 0.0

        exact = []
        partial = []
        for key, contact in self.crm_detail.items():
            pool = set([self._normalize_text(contact.get("display_name"))])
            pool.update([self._normalize_text(v) for v in contact.get("name_variants", [])])
            pool.add(key.replace("_", " "))
            if q in pool:
                exact.append(key)
            elif any(q in p or p in q for p in pool if p):
                partial.append(key)

        if len(exact) == 1:
            return exact[0], 0.95
        if len(partial) == 1:
            return partial[0], 0.8
        if len(exact) > 1:
            return None, 0.5

        prompt = self.MATCH_CONTACT_PROMPT.format(
            contact_list=json.dumps(self._contact_summary_for_match()),
            spoken_name=spoken_name,
            full_context=full_context,
        )
        response = self.capability_worker.text_to_text_response(self._with_session_context(prompt))
        match = self._safe_json(response, {"matched_key": None, "confidence": 0.0})
        mk = match.get("matched_key")
        conf = float(match.get("confidence", 0.0) or 0.0)
        if mk not in self.crm_detail:
            return None, conf
        return mk, conf

    def _create_new_contact(self, extracted: dict) -> dict:
        today = self._today()
        display = extracted.get("name") or extracted.get("first_name") or "Unknown"
        notes = []
        if extracted.get("context"):
            notes.append({"date": today, "text": str(extracted["context"]).strip()})
        if extracted.get("note") and extracted.get("note") != extracted.get("context"):
            notes.append({"date": today, "text": str(extracted["note"]).strip()})
        return {
            "display_name": display,
            "name_variants": [],
            "company": extracted.get("company"),
            "role": extracted.get("role"),
            "email": extracted.get("email"),
            "phone": extracted.get("phone"),
            "location": extracted.get("location"),
            "first_met": today,
            "first_met_context": extracted.get("context"),
            "last_contact": today,
            "tags": sorted(list(set(extracted.get("tags") or []))),
            "notes": notes,
        }

    def merge_contact_data(self, existing: dict, new_data: dict) -> dict:
        today_str = self._today()
        merged = dict(existing)
        merged.setdefault("notes", [])
        merged.setdefault("tags", [])

        for field in ["company", "role", "email", "phone", "location"]:
            new_val = new_data.get(field)
            if new_val and new_val != merged.get(field):
                old_val = merged.get(field)
                merged[field] = new_val
                if old_val:
                    merged["notes"].append({"date": today_str, "text": f"Updated {field}: {old_val} -> {new_val}"})

        merged["last_contact"] = today_str
        merged["tags"] = sorted(list(set(list(merged.get("tags", [])) + list(new_data.get("tags", [])))))

        note_text = new_data.get("note") or new_data.get("context")
        if note_text:
            merged["notes"].append({"date": today_str, "text": str(note_text).strip()})

        if new_data.get("name"):
            merged["display_name"] = new_data.get("name")
        merged["name_variants"] = self._build_contact_variants(merged)
        return merged

    async def create_crm(self, user_input: str) -> str:
        extracted = await self.extract_contact_data(user_input)
        if not extracted.get("name") and not extracted.get("first_name"):
            return "I couldn't catch the person's name. Please say it again."

        spoken_name = extracted.get("name") or extracted.get("first_name")
        matched_key, confidence = await self.find_existing_contact(spoken_name, user_input)
        if matched_key and confidence >= 0.7:
            self.crm_detail[matched_key] = self.merge_contact_data(self.crm_detail[matched_key], extracted)
            await self.save_contact()
            return f"Updated {self.crm_detail[matched_key].get('display_name')}."

        new_contact = self._create_new_contact(extracted)
        base_key = self.generate_contact_key(new_contact.get("display_name"))
        key = base_key
        idx = 2
        while key in self.crm_detail:
            key = f"{base_key}_{idx}"
            idx += 1

        new_contact["name_variants"] = self._build_contact_variants(new_contact)
        self.crm_detail[key] = self._canonicalize_contact(key, new_contact)
        await self.save_contact()

        role = new_contact.get("role")
        company = new_contact.get("company")
        context = new_contact.get("first_met_context")
        parts = [f"Saved {new_contact.get('display_name')}"]
        if role and company:
            parts.append(f"{role} at {company}")
        elif company:
            parts.append(f"at {company}")
        if context:
            parts.append(f"met at {context}")
        return ", ".join(parts) + "."

    def build_spoken_summary(self, contact: dict, include_all_notes: bool = False) -> str:
        name = contact.get("display_name", "Unknown")
        parts = [name + "."]

        role = contact.get("role")
        company = contact.get("company")
        if role and company:
            parts.append(f"{name} is {role} at {company}.")
        elif company:
            parts.append(f"Works at {company}.")
        elif role:
            parts.append(f"Role is {role}.")

        if contact.get("email"):
            parts.append(f"Email: {self.format_email_for_speech(contact.get('email'))}.")
        if contact.get("phone"):
            parts.append(f"Phone: {self.format_phone_for_speech(contact.get('phone'))}.")
        if contact.get("location"):
            parts.append(f"Based in {contact.get('location')}.")
        if contact.get("first_met") and contact.get("first_met_context"):
            clean_context = self._clean_first_met_context(contact.get("first_met_context"))
            parts.append(
                f"You first met on {self.format_date_for_speech(contact.get('first_met'))} at {clean_context}."
            )
        if contact.get("last_contact"):
            parts.append(f"Last contact was {self.format_date_for_speech(contact.get('last_contact'))}.")

        tags = contact.get("tags", [])
        if tags:
            parts.append("Tags: " + ", ".join(tags) + ".")

        notes = contact.get("notes", [])
        user_notes = [n for n in notes if not self._is_system_update_note(n.get("text", ""))]
        shown_notes = user_notes if user_notes else notes
        if shown_notes:
            selected = shown_notes if include_all_notes else shown_notes[-3:]
            parts.append(f"You have {len(shown_notes)} notes.")
            for n in selected:
                parts.append(f"{self.format_date_for_speech(n.get('date', ''))}: {n.get('text', '')}.")
            if len(shown_notes) > 3 and not include_all_notes:
                parts.append("I can read older notes too if you want.")
        return " ".join(parts)

    async def retrieve_contact(self, user_input: str) -> str:
        if not self.crm_detail:
            return "Your contact list is empty. You can start by telling me about someone you met."
        if self._looks_like_list_query(user_input):
            return await self.search_contacts(user_input)
        matched_key, confidence = await self.find_existing_contact(user_input, user_input)
        if not matched_key or confidence < 0.6:
            return "I don't have anyone by that name in your local CRM."
        return self.build_spoken_summary(self.crm_detail[matched_key], include_all_notes=True)

    async def lookup_contact_detail(self, user_input: str) -> str:
        if not self.crm_detail:
            return "Your contact list is empty."

        parsed = self._safe_json(
            self.capability_worker.text_to_text_response(
                self._with_session_context(self.LOOKUP_REQUEST_PROMPT.format(user_input=user_input))
            ),
            {"name": None, "field": None},
        )
        requested_field = parsed.get("field")
        if requested_field not in {"phone", "email", "meeting", "summary"}:
            low = self._normalize_text(user_input)
            if any(x in low for x in ["meeting", "schedule", "scheduled", "rescheduled", "call"]):
                requested_field = "meeting"
            elif any(x in low for x in ["what do i know", "tell me about", "summary"]):
                requested_field = "summary"
            else:
                requested_field = "phone" if any(x in low for x in ["phone", "number", "mobile"]) else "email"

        name_hint = parsed.get("name") or user_input
        matched_key, confidence = await self.find_existing_contact(name_hint, user_input)
        if not matched_key or confidence < 0.6:
            return "I couldn't match that person in your local CRM."

        contact = self.crm_detail[matched_key]
        if requested_field == "meeting":
            return self._meeting_summary(contact)
        if requested_field == "summary":
            return self.build_spoken_summary(contact, include_all_notes=True)
        val = contact.get(requested_field)
        name = contact.get("display_name", "This contact")
        if not val:
            return f"I don't have {name}'s {requested_field} in local CRM yet."
        if requested_field == "phone":
            return f"{name}'s number is {self.format_phone_for_speech(val)}."
        return f"{name}'s email is {self.format_email_for_speech(val)}."

    async def add_note_to_contact(self, user_input: str) -> str:
        if not self.crm_detail:
            return "Your contact list is empty."

        extract = self._safe_json(
            self.capability_worker.text_to_text_response(
                self._with_session_context(self.EXTRACT_NOTE_PROMPT.format(user_input=user_input))
            ),
            {"name": None, "note": None},
        )
        note = (extract.get("note") or "").strip()
        if not note:
            return "I couldn't find the note text. Please say it again."

        name = extract.get("name") or user_input
        matched_key, confidence = await self.find_existing_contact(name, user_input)
        if not matched_key or confidence < 0.6:
            return "I couldn't find that contact to add the note."

        today = self._today()
        contact = self.crm_detail[matched_key]
        contact.setdefault("notes", []).append({"date": today, "text": note})
        contact["last_contact"] = today
        self.crm_detail[matched_key] = contact
        await self.save_contact()
        return f"Added a note to {contact.get('display_name')}."

    async def update_contact(self, user_input: str) -> str:
        if not self.crm_detail:
            return "Your contact list is empty."

        parsed = self._safe_json(
            self.capability_worker.text_to_text_response(
                self._with_session_context(self.EXTRACT_UPDATE_PROMPT.format(user_input=user_input))
            ),
            {
                "name": None,
                "action": "unknown",
                "field": None,
                "value": None,
                "old_tag": None,
                "new_tag": None,
                "note_date": None,
                "note_contains": None,
            },
        )

        name = parsed.get("name") or user_input
        action = parsed.get("action") or "unknown"
        matched_key, confidence = await self.find_existing_contact(name, user_input)
        if (not matched_key or confidence < 0.6) and not parsed.get("name"):
            matched_key, confidence = self._resolve_contact_from_utterance(user_input)
        if not matched_key or confidence < 0.6:
            return "I couldn't find that contact to update."

        contact = self.crm_detail[matched_key]
        today = self._today()

        if action == "remove_contact":
            display = contact.get("display_name", "that contact")
            del self.crm_detail[matched_key]
            await self.save_contact()
            return f"Removed {display} from your contacts."

        if action == "set_field":
            field = parsed.get("field")
            value = parsed.get("value")
            if field not in {"company", "role", "email", "phone", "location"}:
                return "I can update company, role, email, phone, or location."
            if field == "email":
                value = self._normalize_email(value)
            if field == "phone":
                value = self._normalize_phone(value)
            if not value:
                return f"I couldn't extract a valid value for {field}."
            old = contact.get(field)
            contact[field] = value
            contact["last_contact"] = today
            contact.setdefault("notes", []).append({"date": today, "text": f"Updated {field}: {old or 'empty'} -> {value}"})
            self.crm_detail[matched_key] = contact
            await self.save_contact()
            return f"Updated {contact.get('display_name')}'s {field}."

        if action in {"add_tag", "remove_tag", "replace_tag"}:
            tags = set([self._normalize_text(t) for t in contact.get("tags", []) if self._normalize_text(t)])
            if action == "add_tag":
                new_tag = self._normalize_text(parsed.get("new_tag") or parsed.get("value"))
                if not new_tag:
                    return "I couldn't detect the tag to add."
                tags.add(new_tag)
                msg = f"Added tag {new_tag} to {contact.get('display_name')}."
            elif action == "remove_tag":
                old_tag = self._normalize_text(parsed.get("old_tag") or parsed.get("value"))
                if not old_tag:
                    return "I couldn't detect which tag to remove."
                tags = set([t for t in tags if t != old_tag])
                msg = f"Removed tag {old_tag} from {contact.get('display_name')}."
            else:
                old_tag = self._normalize_text(parsed.get("old_tag"))
                new_tag = self._normalize_text(parsed.get("new_tag"))
                if not old_tag or not new_tag:
                    return "I need both old and new tags for that change."
                tags = set([new_tag if t == old_tag else t for t in tags])
                msg = f"Replaced tag {old_tag} with {new_tag} for {contact.get('display_name')}."
            contact["tags"] = sorted(list(tags))
            contact["last_contact"] = today
            self.crm_detail[matched_key] = contact
            await self.save_contact()
            return msg

        if action == "remove_note":
            note_date = parsed.get("note_date")
            note_contains = self._normalize_text(parsed.get("note_contains"))
            notes = contact.get("notes", [])
            keep = []
            removed = 0
            for n in notes:
                n_date = n.get("date")
                n_text = self._normalize_text(n.get("text"))
                match_date = bool(note_date and n_date == note_date)
                match_text = bool(note_contains and note_contains in n_text)
                if match_date or match_text:
                    removed += 1
                else:
                    keep.append(n)
            if removed == 0:
                return "I couldn't find a matching note to remove."
            contact["notes"] = keep
            contact["last_contact"] = today
            self.crm_detail[matched_key] = contact
            await self.save_contact()
            return f"Removed {removed} note(s) from {contact.get('display_name')}."

        return "I couldn't determine the update action."

    def _recent_within_days(self, contact: dict, days: int) -> bool:
        try:
            last = datetime.strptime(contact.get("last_contact", ""), "%Y-%m-%d").date()
            return last >= (date.today() - timedelta(days=days))
        except Exception:
            return False

    async def search_contacts(self, user_input: str) -> str:
        if not self.crm_detail:
            return "Your contact list is empty."

        result = self._safe_json(
            self.capability_worker.text_to_text_response(
                self._with_session_context(self.EXTRACT_SEARCH_PROMPT.format(user_input=user_input))
            ),
            {"search_type": "general", "search_term": None, "days": 7},
        )
        stype = result.get("search_type", "general")
        term = self._normalize_text(result.get("search_term"))
        days = int(result.get("days", 7) or 7)

        matches = []
        for key, c in self.crm_detail.items():
            company = self._normalize_text(c.get("company"))
            role = self._normalize_text(c.get("role"))
            context = self._normalize_text(c.get("first_met_context"))
            tags = [self._normalize_text(t) for t in c.get("tags", [])]
            dname = self._normalize_text(c.get("display_name"))
            blob = " ".join([company, role, context, dname, " ".join(tags)])

            ok = False
            if self._looks_like_list_query(user_input):
                ok = True
            elif stype == "company":
                ok = bool(term and term in company)
            elif stype == "tag":
                ok = bool(term and any(term in t for t in tags))
            elif stype == "context":
                ok = bool(term and term in context)
            elif stype == "name":
                ok = bool(term and term in dname)
            elif stype == "date":
                ok = self._recent_within_days(c, days)
            else:
                ok = bool(term and term in blob) if term else True

            if ok:
                matches.append((key, c))

        if not matches:
            return "I couldn't find any matching contacts."

        if len(matches) <= 4:
            spoken = []
            for _, c in matches:
                nm = c.get("display_name", "Unknown")
                rl = c.get("role")
                cp = c.get("company")
                if rl and cp:
                    spoken.append(f"{nm}, {rl} at {cp}")
                elif cp:
                    spoken.append(f"{nm}, at {cp}")
                else:
                    spoken.append(nm)
            return "I found " + "; ".join(spoken) + "."

        names = [c.get("display_name", "Unknown") for _, c in matches[:6]]
        more = "" if len(matches) <= 6 else " and more"
        return f"I found {len(matches)} contacts: {', '.join(names)}{more}. Want details on any of them?"

    async def _handle_single_turn(self, user_input: str) -> Tuple[str, str]:
        intent_data = await self.classify_intent(user_input)
        intent = intent_data.get("intent", "unknown")
        mode = intent_data.get("mode", "quick")
        self.mode = mode

        if intent == "store":
            return await self.create_crm(user_input), mode
        if intent == "retrieve":
            return await self.retrieve_contact(user_input), mode
        if intent == "lookup":
            return await self.lookup_contact_detail(user_input), mode
        if intent == "search":
            return await self.search_contacts(user_input), mode
        if intent == "add_note":
            return await self.add_note_to_contact(user_input), mode
        if intent == "update":
            return await self.update_contact(user_input), mode
        return "I'm not sure what you'd like to do with contacts.", mode

    async def run(self):
        await self.capability_worker.speak(
            "Contact memory ready. Tell me about someone, ask for a contact, or say stop."
        )
        try:
            self._reset_session_history()
            await self.load_contact()

            #  loaded cntent
            self._log_info(f"Current contacts: {len(self.crm_detail)}")

            # Seed context from recent main-flow history for this activation.
            try:
                prev = self.capability_worker.get_full_message_history() or []
                for item in prev[-4:]:
                    if isinstance(item, dict):
                        self._add_history(item.get("role", "user"), item.get("content", ""))
            except Exception:
                pass

            while True:
                # hitory
                self._log_info(f"Recent session history: {self._session_context_text(limit=10)}")

                user_input = await self.capability_worker.user_response()
                self._log_info(f"user_input={user_input}")
                if not user_input:
                    continue
                self._add_history("user", user_input)
                if any(word in user_input.lower() for word in EXIT_WORDS):
                    await self.capability_worker.speak("Goodbye.")
                    break
                response, mode = await self._handle_single_turn(user_input)
                self._add_history("assistant", response)
                await self.capability_worker.speak(self._speech_safe_text(response))
                if mode == "quick":
                    break
        except Exception as e:
            self._log_error(f"run error: {e}")
            await self.capability_worker.speak("I hit an error while managing contacts.")
        finally:
            self._reset_session_history()
            self.capability_worker.resume_normal_flow()
