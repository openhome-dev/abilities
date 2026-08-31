import json
import re
from datetime import datetime

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# propertypro — stage 1 showing tour guide
# visitor says hello → room tour + q&a from a markdown listing packet

PREFS_FILE = "propertypro_prefs.json"
QUESTIONS_FILE = "tour_questions.md"
GAPS_FILE = "knowledge_gaps.json"
FAIR_HOUSING_FILE = "fair_housing.md"
DEFAULT_LISTING_ID = "1420-maple-richmond"
LISTINGS_DIR = "fixtures/listings"

EXIT_PATTERN = re.compile(
    r"\b(stop|exit|quit|done|cancel|bye|goodbye|never\s*mind|"
    r"that'?s\s*all|we'?re\s*done|wrap\s*up|end\s*tour)\b",
    re.IGNORECASE,
)

# Room-navigation verbs. Word-boundary matched, not substring: a bare "back" in t
# matched inside "backyard" and "background", so "is there a backyard?" -- one of
# the most likely questions on any showing -- silently navigated the tour backward
# instead of answering. Same class of bug as RESTART_PATTERN below.
#
# "next" still has one residual ambiguity this can't resolve with a plain pattern:
# it's both the navigation command and an ordinary preposition ("next to the
# park", "next door"), so "is the yard next to a park" is still read as
# navigation. Narrowing further would need real intent understanding, not a
# regex; flagged here rather than silently left as a solved problem.
NEXT_ROOM_PATTERN = re.compile(r"\b(next|continue)\b", re.IGNORECASE)
BACK_ROOM_PATTERN = re.compile(r"\b(back|previous)\b", re.IGNORECASE)

# In-tour restart phrases only -- NOT used to invoke the ability. Invocation is the
# dashboard's job (trigger words are configured there, not in code); this is purely
# for _is_restart() below, deciding mid-conversation whether the visitor just said
# "start over" versus asking a real question. Word-boundary matched, same as
# EXIT_PATTERN above -- a plain substring check on "hi" previously matched "this",
# "which", and any other word containing it, so "is this room big?" mid-tour reset
# the showing back to the foyer instead of answering.
RESTART_PATTERN = re.compile(
    r"\b(hello|hi|start tour|begin tour|property pro|propertypro|showing tour)\b",
    re.IGNORECASE,
)

CLASSIFY_PROMPT = """Classify this showing-tour visitor utterance.
Return ONLY one label from this list:
room_nav, property_fact, crime_safety, school_quality, demographics, contact, advice, exit, other

Rules:
- room name, next room, go back, previous → room_nav
- beds, baths, price, sq ft, roof, hvac, appliances, hoa, inclusions, dimensions, flood → property_fact
- safe neighborhood, crime, crime rate → crime_safety
- are the schools good, school quality, ratings → school_quality
- who lives here, diverse, demographics, people like us, race, religion → demographics
- agent phone, text the agent, call the agent, email questions, contact agent → contact
- should i buy, is it overpriced, offer, negotiation, financing → advice
- stop, done, goodbye, end tour → exit
- anything else → other

Utterance: {text}
"""

ANSWER_PROMPT = """You are PropertyPro, a voice showing-tour guide. Answer ONLY from the listing packet.
Rules:
- one or two short spoken sentences. no bullet lists.
- if the listing packet does not contain the answer, reply exactly: UNKNOWN
- never invent facts, sizes, system ages, or neighborhood opinions.
- never discuss crime stats, school quality ratings, or demographics.
- do not ask the visitor what they want next.

Fair housing context:
{fair_housing}

Listing packet:
{listing}

Visitor asked: {question}
"""


def _bullet_value(text: str, key: str) -> str | None:
    """pull '- **key:** value' from markdown."""
    pattern = rf"^-\s+\*\*{re.escape(key)}:\*\*\s*(.+)\s*$"
    for line in text.splitlines():
        m = re.match(pattern, line.strip(), re.IGNORECASE)
        if m:
            val = m.group(1).strip().strip("`")
            if val.lower() in ("(none)", "(unknown)", "(not provided)", "none", ""):
                return None
            return val
    return None


def _section_body(text: str, heading: str) -> str:
    """return markdown under ## {heading} until the next ##."""
    lines = text.splitlines()
    start = None
    want = heading.strip().lower()
    for i, line in enumerate(lines):
        if line.strip().lower() == f"## {want}":
            start = i + 1
            break
    if start is None:
        return ""
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end]).strip()


def _parse_tour_order(text: str) -> list[str]:
    body = _section_body(text, "Tour order")
    order = []
    for line in body.splitlines():
        m = re.match(r"^\d+\.\s+(\S+)\s*$", line.strip())
        if m:
            order.append(m.group(1).strip().lower())
    return order


def _parse_rooms(text: str) -> dict[str, dict]:
    body = _section_body(text, "Rooms")
    rooms: dict[str, dict] = {}
    current = None
    for line in body.splitlines():
        heading = re.match(r"^###\s+(\S+)\s*$", line.strip())
        if heading:
            current = heading.group(1).strip().lower()
            rooms[current] = {"id": current, "dimensions": None, "note": None}
            continue
        if current is None:
            continue
        dim = re.match(r"^-\s+\*\*dimensions:\*\*\s*(.+)\s*$", line.strip(), re.I)
        if dim:
            raw = dim.group(1).strip()
            if raw.lower() not in ("(none)", "(unknown)", "none", ""):
                rooms[current]["dimensions"] = raw
            continue
        note = re.match(r"^-\s+\*\*note:\*\*\s*(.+)\s*$", line.strip(), re.I)
        if note:
            rooms[current]["note"] = note.group(1).strip()
    return rooms


def _parse_systems(text: str) -> dict[str, str]:
    body = _section_body(text, "Systems")
    if not body or "not provided" in body.lower():
        return {}
    systems = {}
    for line in body.splitlines():
        m = re.match(r"^-\s+\*\*([^:]+):\*\*\s*(.+)\s*$", line.strip())
        if not m:
            continue
        key = m.group(1).strip().lower()
        val = m.group(2).strip()
        if val.lower() in ("(unknown)", "(none)", "none", ""):
            continue
        systems[key] = val
    return systems


def _parse_list_section(text: str, heading: str) -> list[str] | None:
    body = _section_body(text, heading)
    if not body:
        return None
    if "not provided" in body.lower():
        return None
    items = []
    for line in body.splitlines():
        m = re.match(r"^-\s+(.+)\s*$", line.strip())
        if m:
            items.append(m.group(1).strip())
    return items


def _parse_agent(text: str) -> dict:
    body = _section_body(text, "Agent")
    return {
        "name": _bullet_value(body, "name"),
        "brokerage": _bullet_value(body, "brokerage"),
        "phone": _bullet_value(body, "phone"),
        "email": _bullet_value(body, "email"),
    }


def _parse_schools(text: str) -> dict | None:
    body = _section_body(text, "School assignment")
    if not body or "not provided" in body.lower():
        return None
    return {
        "elementary": _bullet_value(body, "elementary"),
        "middle": _bullet_value(body, "middle"),
        "high": _bullet_value(body, "high"),
        "verify": _bullet_value(body, "verify"),
    }


def _parse_redirects(text: str) -> dict:
    body = _section_body(text, "Redirect URLs")
    return {
        "crime": _bullet_value(body, "crime open data"),
        "schools": _bullet_value(body, "school district"),
        "flood": _bullet_value(body, "flood map"),
    }


def parse_listing(text: str) -> dict:
    """structured fields from a listing markdown packet."""
    title = "this home"
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    seller = _section_body(text, "Seller welcome")
    if seller.lower() in ("(none)", ""):
        seller = None
    return {
        "raw": text,
        "title": title,
        "id": _bullet_value(text, "id") or DEFAULT_LISTING_ID,
        "address": _bullet_value(text, "address"),
        "price": _bullet_value(text, "price"),
        "beds_baths": _bullet_value(text, "beds / baths"),
        "sq_ft": _bullet_value(text, "sq ft"),
        "lot": _bullet_value(text, "lot"),
        "year_built": _bullet_value(text, "year built"),
        "hoa": _bullet_value(text, "hoa"),
        "hoa_docs": _bullet_value(text, "hoa docs"),
        "agent": _parse_agent(text),
        "seller_welcome": seller,
        "tour_order": _parse_tour_order(text),
        "rooms": _parse_rooms(text),
        "systems": _parse_systems(text),
        "inclusions": _parse_list_section(text, "Inclusions"),
        "exclusions": _parse_list_section(text, "Exclusions"),
        "schools": _parse_schools(text),
        "redirects": _parse_redirects(text),
    }


def phone_for_speech(phone: str | None) -> str:
    if not phone:
        return "the number on the listing sheet"
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("1") and len(digits) == 11:
        digits = digits[1:]
    if len(digits) == 10:
        a, b, c = digits[:3], digits[3:6], digits[6:]
        return f"{' '.join(a)}, {' '.join(b)}, {' '.join(c)}"
    return " ".join(digits)


class PropertyProCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    listing: dict = None
    fair_housing: str = ""
    room_index: int = 0
    session_questions: list = None
    showing_started: bool = False

    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.session_questions = []
        self.room_index = 0
        self.showing_started = False
        self.worker.session_tasks.create(self.run())

    async def run(self):
        # showing-device mode: stay in propertypro. after a tour ends, wait for
        # hello again — do not hand visitors to the regular agent.
        try:
            await self._load_context()
            if not self.listing:
                await self.capability_worker.speak(
                    "I don't have an active listing packet loaded. "
                    "Please set active listing i d and try again."
                )
                return

            while True:
                self.session_questions = []
                self.room_index = 0
                await self._greet_and_start()
                await self._tour_loop()
                await self._wait_for_hello()
        except Exception as e:
            self.worker.editor_logging_handler.error(f"propertypro error: {e}")
            try:
                await self.capability_worker.speak(
                    "Something went wrong on the tour. Please try saying hello again."
                )
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()

    def _is_exit(self, text: str) -> bool:
        return bool(EXIT_PATTERN.search(text or ""))

    def _is_restart(self, text: str) -> bool:
        return bool(RESTART_PATTERN.search(text or ""))

    async def _tour_loop(self):
        """run one showing until idle, exit words, or classified exit."""
        idle = 0
        while True:
            user_input = await self.capability_worker.user_response()
            if not user_input or not user_input.strip():
                idle += 1
                if idle >= 2:
                    await self._close_tour()
                    return
                continue
            idle = 0
            if self._is_exit(user_input):
                await self._close_tour()
                return
            # saying hello mid-tour restarts from the first room
            if self._is_restart(user_input):
                self.session_questions = []
                self.room_index = 0
                await self._greet_and_start()
                continue
            should_end = await self._handle_turn(user_input)
            if should_end:
                return

    async def _wait_for_hello(self):
        """lobby after a closed tour — keep listening until hello."""
        while True:
            user_input = await self.capability_worker.user_response()
            if not user_input or not user_input.strip():
                # stay quiet; do not drop to the regular agent
                continue
            if self._is_restart(user_input):
                return
            await self.capability_worker.speak(
                "The tour is closed. Say hello to start again."
            )

    async def _load_context(self):
        prefs = await self._load_prefs()
        listing_id = prefs.get("active_listing_id") or DEFAULT_LISTING_ID
        path = f"{LISTINGS_DIR}/{listing_id}.md"
        listing_text = await self._read_ability_file(path)
        if not listing_text:
            # fall back to default fixture
            path = f"{LISTINGS_DIR}/{DEFAULT_LISTING_ID}.md"
            listing_text = await self._read_ability_file(path)
        if listing_text:
            self.listing = parse_listing(listing_text)
        self.fair_housing = await self._read_ability_file(FAIR_HOUSING_FILE) or ""
        self.worker.editor_logging_handler.info(
            f"propertypro loaded listing={self.listing.get('id') if self.listing else None}"
        )

    async def _load_prefs(self) -> dict:
        try:
            exists = await self.capability_worker.check_if_file_exists(
                PREFS_FILE, in_ability_directory=True
            )
            if not exists:
                prefs = {"active_listing_id": DEFAULT_LISTING_ID}
                await self.capability_worker.write_file(
                    PREFS_FILE,
                    json.dumps(prefs, indent=2),
                    in_ability_directory=True,
                    mode="w",
                )
                return prefs
            raw = await self.capability_worker.read_file(
                PREFS_FILE, in_ability_directory=True
            )
            return json.loads(raw) if raw else {"active_listing_id": DEFAULT_LISTING_ID}
        except Exception as e:
            self.worker.editor_logging_handler.error(f"propertypro prefs: {e}")
            return {"active_listing_id": DEFAULT_LISTING_ID}

    async def _read_ability_file(self, name: str) -> str | None:
        try:
            exists = await self.capability_worker.check_if_file_exists(
                name, in_ability_directory=True
            )
            if not exists:
                return None
            return await self.capability_worker.read_file(
                name, in_ability_directory=True
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"propertypro read {name}: {e}")
            return None

    async def _greet_and_start(self):
        title = self.listing.get("title") or "this home"
        first_id = self._room_id_at(0)
        first_label = first_id.replace("_", " ") if first_id else "the entry"
        await self.capability_worker.speak(
            f"Hi — welcome to {title}. I'll walk you through the main spaces, "
            "and you can ask me questions anytime. I'm here for facts about this "
            "property — for neighborhood topics like crime or demographics, I'll "
            "point you to official sources rather than give opinions. "
            f"We'll begin in the {first_label}."
        )
        self.showing_started = True
        self.room_index = 0
        await self._speak_room(self.room_index)

    def _room_id_at(self, index: int) -> str | None:
        order = self.listing.get("tour_order") or []
        if 0 <= index < len(order):
            return order[index]
        return None

    async def _speak_room(self, index: int):
        room_id = self._room_id_at(index)
        if not room_id:
            await self.capability_worker.speak(
                "That's the end of the listed rooms for this home."
            )
            return
        room = (self.listing.get("rooms") or {}).get(room_id) or {}
        label = room_id.replace("_", " ")
        parts = [f"You're in the {label}."]
        dims = room.get("dimensions")
        if dims:
            # packet already uses "11 by 8" style
            spoken_dims = dims.replace("x", " by ").replace("×", " by ")
            parts.append(f"Room dimensions {spoken_dims}.")
        note = room.get("note")
        if note:
            parts.append(note)
        await self.capability_worker.speak(" ".join(parts))

    async def _handle_turn(self, text: str) -> bool:
        """handle one visitor turn. return True when this tour session should end."""
        label = self._classify(text)
        if label == "exit":
            await self._close_tour()
            return True

        if label == "room_nav":
            await self._handle_room_nav(text)
            return False
        if label == "crime_safety":
            await self.capability_worker.speak(
                "I don't give crime opinions or stats. You can check the public "
                "safety open data and local police resources linked in my notes."
            )
            return False
        if label == "school_quality":
            await self._handle_schools()
            return False
        if label == "demographics":
            await self.capability_worker.speak(
                "I'm not able to discuss neighborhood demographics under fair "
                "housing guidelines. I can stick to facts about this property "
                "if you have another question."
            )
            return False
        if label == "contact":
            await self._handle_contact(text)
            return False
        if label == "advice":
            await self.capability_worker.speak(
                "I can't advise on offers or pricing. That's best handled with "
                "your agent or lender."
            )
            await self._log_question("Visitor asked for pricing or offer advice")
            return False
        # property_fact or other — try deterministic then grounded llm
        handled = await self._handle_property_fact(text)
        if not handled:
            await self._grounded_answer(text)
        return False

    def _classify(self, text: str) -> str:
        t = (text or "").lower()
        # fast paths before llm
        if self._is_exit(t):
            return "exit"
        if any(k in t for k in ("crime", "safe neighborhood", "safe area", "safety")):
            return "crime_safety"
        if "school" in t and any(k in t for k in ("good", "great", "bad", "rating", "quality")):
            return "school_quality"
        if any(
            k in t
            for k in (
                "who lives",
                "demographic",
                "diverse",
                "diversity",
                "people like us",
                "racial",
                "religion",
            )
        ):
            return "demographics"
        if any(
            k in t
            for k in (
                "text the agent",
                "call the agent",
                "email my questions",
                "email the agent",
                "agent's number",
                "agent number",
                "phone number",
                "contact the agent",
            )
        ):
            return "contact"
        if any(
            k in t
            for k in (
                "should i buy",
                "overpriced",
                "make an offer",
                "negotiate",
                "contingency",
            )
        ):
            return "advice"
        if self._match_room_nav(t) is not None:
            return "room_nav"
        try:
            raw = self.capability_worker.text_to_text_response(
                CLASSIFY_PROMPT.format(text=text)
            )
            label = (raw or "").strip().lower().split()[0].strip(".,")
            allowed = {
                "room_nav",
                "property_fact",
                "crime_safety",
                "school_quality",
                "demographics",
                "contact",
                "advice",
                "exit",
                "other",
            }
            if label in allowed:
                return label
        except Exception as e:
            self.worker.editor_logging_handler.error(f"propertypro classify: {e}")
        return "property_fact"

    def _match_room_nav(self, t: str) -> int | None:
        """return new room index or None if not navigation."""
        order = self.listing.get("tour_order") or []
        if NEXT_ROOM_PATTERN.search(t):
            return min(self.room_index + 1, max(len(order) - 1, 0))
        if BACK_ROOM_PATTERN.search(t):
            return max(self.room_index - 1, 0)
        for i, room_id in enumerate(order):
            label = room_id.replace("_", " ")
            if room_id in t or label in t:
                return i
            # common aliases
            if room_id == "living" and "living room" in t:
                return i
            if room_id == "primary" and ("primary" in t or "master" in t):
                return i
            if room_id == "living_kitchen" and ("living" in t or "kitchen" in t):
                return i
        return None

    async def _handle_room_nav(self, text: str):
        idx = self._match_room_nav((text or "").lower())
        if idx is None:
            await self.capability_worker.speak(
                "Name a room from the tour, or say next room."
            )
            return
        self.room_index = idx
        await self._speak_room(self.room_index)

    async def _handle_schools(self):
        schools = self.listing.get("schools")
        if not schools:
            await self.capability_worker.speak(
                "I don't rate schools. I also don't have a school assignment "
                "in my notes for this listing. I've added that to the agent's "
                "question list."
            )
            await self._log_question("School assignment for this address?")
            return
        parts = [
            s
            for s in (
                schools.get("elementary"),
                schools.get("middle"),
                schools.get("high"),
            )
            if s
        ]
        assignment = ", ".join(parts) if parts else "the district assignment on file"
        await self.capability_worker.speak(
            f"I don't rate schools. This address is listed under {assignment} — "
            "please verify on the district site. Public report cards are the "
            "place to judge fit."
        )

    async def _handle_contact(self, text: str):
        agent = self.listing.get("agent") or {}
        name = agent.get("name") or "the listing agent"
        phone = agent.get("phone")
        t = (text or "").lower()
        if any(k in t for k in ("text", "call", "email")):
            # stage 1: no twilio/smtp wiring yet — speak contact + keep file
            await self.capability_worker.speak(
                f"I can't send messages from this device yet. "
                f"{name}'s number is {phone_for_speech(phone)}. "
                "Your questions are saved on the agent's list."
            )
            return
        await self.capability_worker.speak(
            f"The listing agent is {name}. "
            f"You can reach them at {phone_for_speech(phone)}."
        )

    async def _handle_property_fact(self, text: str) -> bool:
        """deterministic answers for common facts. return True if handled."""
        t = (text or "").lower()
        L = self.listing

        if "square" in t or "sq ft" in t or "sqft" in t or "how big" in t:
            if L.get("sq_ft"):
                await self.capability_worker.speak(f"About {L['sq_ft']}.")
                return True
            await self._unknown("Whole-home square footage?")
            return True

        if "price" in t or "asking" in t or "list price" in t or "cost" in t:
            if L.get("price"):
                await self.capability_worker.speak(f"The list price is {L['price']}.")
                return True
            await self._unknown("List price?")
            return True

        if "bed" in t or "bath" in t:
            if L.get("beds_baths"):
                await self.capability_worker.speak(
                    f"This home is listed as {L['beds_baths']} beds and baths."
                )
                return True
            await self._unknown("Beds and baths?")
            return True

        if "year" in t and "built" in t:
            if L.get("year_built"):
                await self.capability_worker.speak(
                    f"It was built in {L['year_built']}."
                )
                return True
            await self._unknown("Year built?")
            return True

        if "hoa" in t:
            if L.get("hoa"):
                msg = f"H O A note: {L['hoa']}."
                if L.get("hoa_docs"):
                    msg += f" {L['hoa_docs']}."
                await self.capability_worker.speak(msg)
                return True
            await self._unknown("H O A fees or docs?")
            return True

        if "lot" in t:
            if L.get("lot"):
                await self.capability_worker.speak(f"Lot size: {L['lot']}.")
                return True
            await self._unknown("Lot size?")
            return True

        systems = L.get("systems") or {}
        for key, phrases in (
            ("roof", ("roof",)),
            ("hvac", ("hvac", "heating", "cooling", "air condition")),
            ("water heater", ("water heater", "hot water")),
            ("breaker box", ("breaker", "electrical panel")),
            ("water shutoff", ("water shutoff", "shut off", "shut-off")),
            ("in-unit laundry", ("laundry",)),
        ):
            if any(p in t for p in phrases):
                if systems.get(key):
                    await self.capability_worker.speak(
                        f"{key}: {systems[key]}."
                    )
                    return True
                await self._unknown(f"{key} details?")
                return True

        if any(k in t for k in ("appliance", "convey", "stay with", "included")):
            inclusions = L.get("inclusions")
            exclusions = L.get("exclusions")
            if inclusions is None and exclusions is None:
                await self._unknown("What appliances or items convey?")
                return True
            parts = []
            if inclusions:
                parts.append("Included: " + ", ".join(inclusions))
            if exclusions:
                parts.append("Not included: " + ", ".join(exclusions))
            await self.capability_worker.speak(". ".join(parts) + ".")
            return True

        if "school" in t and "assign" in t:
            await self._handle_schools()
            return True

        if "flood" in t:
            url = (L.get("redirects") or {}).get("flood")
            if url:
                await self.capability_worker.speak(
                    "I don't determine flood zones. Check the official flood map "
                    "linked in my notes for this listing."
                )
            else:
                await self._unknown("Flood zone for this address?")
            return True

        return False

    async def _grounded_answer(self, text: str):
        try:
            raw = self.capability_worker.text_to_text_response(
                ANSWER_PROMPT.format(
                    fair_housing=(self.fair_housing or "")[:2500],
                    listing=(self.listing.get("raw") or "")[:6000],
                    question=text,
                )
            )
            answer = (raw or "").strip()
            if not answer or answer.upper().startswith("UNKNOWN"):
                await self._unknown(text.strip())
                return
            await self.capability_worker.speak(answer)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"propertypro answer: {e}")
            await self._unknown(text.strip())

    async def _unknown(self, question: str):
        await self.capability_worker.speak(
            "I don't have that in my notes. I've added that to the agent's "
            "question list."
        )
        await self._log_question(question)

    async def _log_question(self, question: str):
        q = (question or "").strip()
        if not q:
            return
        self.session_questions.append(q)
        address = self.listing.get("address") or self.listing.get("title") or "listing"
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        # append under a session heading; create heading if file empty/new session
        try:
            exists = await self.capability_worker.check_if_file_exists(
                QUESTIONS_FILE, in_ability_directory=False
            )
            header_needed = True
            if exists:
                raw = await self.capability_worker.read_file(
                    QUESTIONS_FILE, in_ability_directory=False
                )
                if raw and f"## Showing — {address}" in raw and stamp[:10] in raw:
                    header_needed = False
            chunk = ""
            if header_needed:
                chunk += f"\n## Showing — {address} — {stamp}\n"
            chunk += f"- {q}\n"
            await self.capability_worker.write_file(
                QUESTIONS_FILE, chunk, in_ability_directory=False
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"propertypro log q: {e}")
            await self._log_gap(q, str(e))

    async def _log_gap(self, query: str, reason: str):
        try:
            gaps = []
            exists = await self.capability_worker.check_if_file_exists(
                GAPS_FILE, in_ability_directory=False
            )
            if exists:
                raw = await self.capability_worker.read_file(
                    GAPS_FILE, in_ability_directory=False
                )
                if raw:
                    gaps = json.loads(raw)
            gaps.append(
                {
                    "query": query,
                    "reason": reason,
                    "at": datetime.now().isoformat(timespec="seconds"),
                }
            )
            await self.capability_worker.write_file(
                GAPS_FILE,
                json.dumps(gaps, indent=2),
                in_ability_directory=False,
                mode="w",
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"propertypro gap: {e}")

    async def _close_tour(self):
        n = len(self.session_questions)
        if n:
            await self.capability_worker.speak(
                f"Closing the tour. I've saved {n} question"
                f"{'s' if n != 1 else ''} for the listing agent. "
                "Say hello to start again."
            )
        else:
            await self.capability_worker.speak(
                "Closing the tour. Say hello to start again."
            )
        self.showing_started = False
