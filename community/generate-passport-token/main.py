import re
import aiohttp
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# CONFIG
# =============================================================================
# Nothing below is hardcoded. Add these three keys in OpenHome Settings ->
# API Keys (names must match exactly) before using this ability:
#   - "passport_admin_cnic"      the kiosk service account's CNIC
#   - "passport_admin_password"  the kiosk service account's password
#   - "passport_api_base_url"    base URL of the Flask backend (e.g. an ngrok URL)
#
# This agent's whole job is to take a citizen's spoken details and generate a
# token for them - the citizen never has their own account, so we log in once,
# automatically, with the kiosk service account instead of asking them for a
# CNIC/password.
# ---------------------------------------------------------------------------
ADMIN_CNIC_KEY = "passport_admin_cnic"
ADMIN_PASSWORD_KEY = "passport_admin_password"
API_BASE_KEY = "passport_api_base_url"

# ---------------------------------------------------------------------------
# NOTE ON EMAIL: the Ability does NOT send the token email itself anymore.
# Flask's /api/submit route sends it (via send_passport_email in app.py),
# so all we do here is read back data["email_sent"] and report that to the
# citizen. If email delivery is failing, fix it on the Flask/SMTP side
# (app.py's MAIL_* config / send_passport_email), not here.
# ---------------------------------------------------------------------------


# Eastern Arabic-Indic (٠-٩) and Urdu-Persian (۰-۹) numerals -> Western digits.
# STT engines sometimes emit either script when transcribing spoken numbers.
DIGIT_TRANSLATION = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

# Spoken number words -> integer, for numbered-choice questions. STT often
# transcribes a spoken number as the WORD ("one", "ایک", "aik") rather than
# the digit "1" - fast_digit_extract alone misses these since there's no
# digit character to find, so we match the word directly instead of relying
# on an LLM round-trip for something this simple.
NUMBER_WORDS = {
    # English
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "twenty-one": 21, "twenty-two": 22, "twenty-three": 23,
    "twenty-four": 24, "twenty-five": 25, "twenty-six": 26, "twenty-seven": 27,
    "twenty-eight": 28, "twenty-nine": 29, "thirty": 30,
    # Urdu script
    "ایک": 1, "دو": 2, "تین": 3, "چار": 4, "پانچ": 5, "چھ": 6, "سات": 7, "آٹھ": 8,
    "نو": 9, "دس": 10, "گیارہ": 11, "بارہ": 12, "تیرہ": 13, "چودہ": 14, "پندرہ": 15,
    "سولہ": 16, "سترہ": 17, "اٹھارہ": 18, "انیس": 19, "بیس": 20, "اکیس": 21,
    "بائیس": 22, "تئیس": 23, "چوبیس": 24, "پچیس": 25,
    # roman-Urdu
    "aik": 1, "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "panch": 5,
    "paanch": 5, "che": 6, "chay": 6, "saat": 7, "aath": 8, "nau": 9, "dus": 10,
    "das": 10, "gyarah": 11, "barah": 12, "tera": 13, "terah": 13, "chodah": 14,
    "pandrah": 15, "solah": 16, "satrah": 17, "atharah": 18, "unnees": 19, "bees": 20,
}

AFFIRMATIVE_WORDS = [
    "ہاں", "جی ہاں", "جی", "ٹھیک ہے", "بالکل", "درست ہے", "صحیح ہے", "ہو گیا", "کر دیں",
    "اچھا", "اچھا جی", "او کے", "اوکے", "جی بالکل", "بلکل ٹھیک",
    "haan", "han", "haan ji", "han ji", "ji", "thek hai", "theek hai", "sahi hai",
    "bilkul", "yes", "ok", "okay", "acha", "achha", "acha ji", "done", "kar do", "kr do",
]

# Short, exact "I don't have an email" style answers - checked before we
# bother the LLM, so someone without an email isn't stuck retrying forever.
NO_EMAIL_WORDS = [
    "نہیں ہے", "نہیں", "میرے پاس نہیں ہے", "میرے پاس ای میل نہیں ہے", "ای میل نہیں ہے",
    "no email", "nahi hai", "nahi", "no", "skip", "chor dain", "chhor dain",
]

# Words that end the whole flow early - checked on every single turn, before
# any transcript is ever handed to an LLM. Covers Urdu script, roman-Urdu, and
# the standard English exit set (stop/done/bye/cancel/exit/quit/goodbye).
EXIT_WORDS = [
    "روک دیں", "روکیں", "بند کریں", "بند کرو", "کینسل", "کینسل کریں", "چھوڑ دیں",
    "رہنے دیں", "رہنے دو", "نہیں کرنا", "معاف کریں چھوڑ دیں",
    "band karo", "band kardo", "cancel", "chor do", "chhor do", "rehnay do", "rehne do",
    "stop", "exit", "quit", "goodbye", "bye", "done",
]

# Simple, permissive email shape check: something@something.something,
# no spaces. Good enough to catch typos and obviously-broken input without
# being so strict it rejects real, valid, less-common addresses.
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

PROVINCES = ["پنجاب", "سندھ", "خیبرپختونخوا", "بلوچستان", "گلگت بلتستان", "آزاد جموں و کشمیر", "اسلام آباد"]
COMMON_CITIES = [
    "راولپنڈی", "اسلام آباد", "لاہور", "کراچی", "فیصل آباد", "ملتان", "پشاور", "کوئٹہ",
    "سیالکوٹ", "گوجرانوالہ", "حیدرآباد", "سرگودھا", "بہاولپور", "سکھر", "ایبٹ آباد",
    "مردان", "کوہاٹ", "سوات", "مظفرآباد", "میرپور", "کوٹلی", "سکردو", "گلگت", "تربت", "گوادر",
]

# Urdu city name -> English keyword(s) to look for inside a branch address
# string (branch addresses come back from /api/branches in English, e.g.
# "13-C, Al-Hussain Plaza, G-10 Markaz, Islamabad"). Used to narrow the
# branch list down to just the citizen's chosen city before asking them
# to pick one, instead of reading out every branch in the country.
CITY_BRANCH_KEYWORDS = {
    "راولپنڈی": ["rawalpindi"],
    "اسلام آباد": ["islamabad"],
    "لاہور": ["lahore"],
    "کراچی": ["karachi"],
    "فیصل آباد": ["faisalabad"],
    "ملتان": ["multan"],
    "پشاور": ["peshawar"],
    "کوئٹہ": ["quetta"],
    "سیالکوٹ": ["sialkot"],
    "گوجرانوالہ": ["gujranwala"],
    "حیدرآباد": ["hyderabad"],
    "سرگودھا": ["sargodha"],
    "بہاولپور": ["bahawalpur"],
    "سکھر": ["sukkur"],
    "ایبٹ آباد": ["abbottabad"],
    "مردان": ["mardan"],
    "کوہاٹ": ["kohat"],
    "سوات": ["swat"],
    "مظفرآباد": ["muzaffarabad"],
    "میرپور": ["mirpur"],
    "کوٹلی": ["kotli"],
    "سکردو": ["skardu"],
    "گلگت": ["gilgit"],
    "تربت": ["turbat"],
    "گوادر": ["gwadar"],
}

# ---------------------------------------------------------------------------
# English equivalents for the two fixed-choice fields (province, city /
# domicile). The citizen only ever hears and picks from the Urdu names above
# (PROVINCES / COMMON_CITIES) - these dicts are purely for what gets SAVED
# to the backend, so the record is stored in English without any LLM
# round-trip (and without any risk of mistranslation) for these fields.
# ---------------------------------------------------------------------------
PROVINCES_EN = {
    "پنجاب": "Punjab",
    "سندھ": "Sindh",
    "خیبرپختونخوا": "Khyber Pakhtunkhwa",
    "بلوچستان": "Balochistan",
    "گلگت بلتستان": "Gilgit-Baltistan",
    "آزاد جموں و کشمیر": "Azad Jammu & Kashmir",
    "اسلام آباد": "Islamabad",
}

# CITY_BRANCH_KEYWORDS already has exactly one lowercase English keyword per
# COMMON_CITIES entry, so we get clean English city names for free by
# title-casing the first keyword (e.g. "راولپنڈی" -> "rawalpindi" -> "Rawalpindi").
CITY_EN = {urdu: keywords[0].title() for urdu, keywords in CITY_BRANCH_KEYWORDS.items()}

# Which of COMMON_CITIES belong to each province - once the citizen picks a
# province, the city/district/domicile questions only offer (and only show
# as buttons in the UI) cities within that province, instead of all 25
# nationwide. Every COMMON_CITIES entry appears in exactly one list here.
PROVINCE_CITIES = {
    "پنجاب": ["راولپنڈی", "لاہور", "فیصل آباد", "ملتان", "سیالکوٹ", "گوجرانوالہ", "سرگودھا", "بہاولپور"],
    "سندھ": ["کراچی", "حیدرآباد", "سکھر"],
    "خیبرپختونخوا": ["پشاور", "ایبٹ آباد", "مردان", "کوہاٹ", "سوات"],
    "بلوچستان": ["کوئٹہ", "تربت", "گوادر"],
    "گلگت بلتستان": ["سکردو", "گلگت"],
    "آزاد جموں و کشمیر": ["مظفرآباد", "میرپور", "کوٹلی"],
    "اسلام آباد": ["اسلام آباد"],
}


class GeneratePassportTokenCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    api_base: str = ""
    exit_requested: bool = False

    # Do not change following tag of register capability
    # {{register_capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    # ---------------------------------------------------------------
    # Small helpers - yes/no, "no email", and exit detection (works on
    # Urdu script or roman-Urdu transcripts, since STT behavior can vary
    # by provider)
    # ---------------------------------------------------------------

    def is_affirmative(self, text: str) -> bool:
        text = (text or "").strip().lower()
        return any(word in text for word in AFFIRMATIVE_WORDS)

    def is_no_email(self, text: str) -> bool:
        text = (text or "").strip().lower()
        return any(word in text for word in NO_EMAIL_WORDS)

    def is_exit(self, text: str) -> bool:
        text = (text or "").strip().lower()
        return any(word in text for word in EXIT_WORDS)

    def is_valid_email(self, email: str) -> bool:
        return bool(EMAIL_RE.match(email or ""))

    def looks_english(self, text: str) -> bool:
        """True if text has no Urdu/Arabic-script characters, i.e. it's
        already safe to store as-is without running it through a
        translation round-trip."""
        return not any("\u0600" <= ch <= "\u06FF" for ch in (text or ""))

    async def _listen(self) -> str:
        """Read one user turn and check it against the escape hatch before
        any LLM call or field-parsing logic ever sees the transcript. Sets
        exit_requested instead of raising, so every caller just checks the
        flag with a plain if - same pattern the other Abilities use."""
        raw = await self.capability_worker.user_response()
        if self.is_exit(raw):
            self.exit_requested = True
            return ""
        return raw or ""

    def to_urdu(self, english_text: str) -> str:
        """Backend error/status messages come back in English. Translate them
        on the fly so the whole conversation stays in Urdu."""
        if not english_text:
            return "کچھ مسئلہ پیش آیا"
        prompt = (
            "درج ذیل انگریزی جملے کا آسان، بول چال کی اردو میں مختصر ترجمہ کریں۔ "
            "صرف ترجمہ لکھیں، کوئی اضافی وضاحت نہ دیں۔\n\n"
            f"{english_text}"
        )
        try:
            return self.capability_worker.text_to_text_response(prompt).strip()
        except Exception:
            return english_text

    def to_english(self, urdu_text: str) -> str:
        """The free-form fields (name, address, and an occasional branch
        name that didn't match the known list) are collected in Urdu, since that's how
        the citizen actually speaks/types them. The backend record,
        though, is meant to be stored in English - so this converts a
        field's value to English right before it's saved, rather than
        anywhere earlier in the flow. Everything the citizen hears (speak
        prompts, confirmations, retries) stays untouched and in Urdu;
        only the value handed to /api/submit changes.

        Uses transliteration for names/addresses (write the Urdu name in
        correct English spelling) rather than literal translation, since
        translating a person's name or a street name into English words
        would produce nonsense.
        """
        if not urdu_text or self.looks_english(urdu_text):
            return urdu_text
        prompt = (
            "درج ذیل اردو متن کو انگریزی رسم الخط میں درست ہجے کے ساتھ لکھیں (transliterate)۔ "
            "اگر یہ کسی شخص کا نام، پتہ یا جگہ کا نام ہے تو معنی کا ترجمہ نہ کریں، بلکہ درست انگریزی "
            "ہجے میں لکھیں۔ صرف نتیجہ لکھیں، کوئی اضافی وضاحت یا سابقہ نہ دیں۔\n\n"
            f"{urdu_text}"
        )
        try:
            result = self.capability_worker.text_to_text_response(prompt).strip()
            return result or urdu_text
        except Exception:
            return urdu_text

    def fast_digit_extract(self, raw: str) -> str:
        """Fast path: if STT already produced literal digit characters
        (common even for Urdu with numeric STT models), normalize any
        Eastern Arabic-Indic numerals to Western ones and use directly -
        skips an LLM round-trip for the common case."""
        normalized = (raw or "").translate(DIGIT_TRANSLATION)
        return "".join(ch for ch in normalized if ch.isdigit())

    def resolve_spoken_number(self, raw: str):
        """Pull a plain integer out of a transcript, whether it came through
        as a literal digit ('1', '۱') or a spoken number word ('one', 'ایک',
        'aik'). Returns None if nothing usable was found."""
        digits = self.fast_digit_extract(raw)
        if digits.isdigit():
            return int(digits)

        text = (raw or "").strip().lower()
        if text in NUMBER_WORDS:
            return NUMBER_WORDS[text]
        for token in text.replace("-", " ").split():
            if token in NUMBER_WORDS:
                return NUMBER_WORDS[token]
        return None

    def parse_llm_field(self, result: str, fallback: str) -> str:
        result = (result or "").strip()
        if result.startswith("OK:") or result.startswith("RETRY:"):
            return result
        return f"OK:{fallback}"  # safety net if the model ignores the format

    # ---------------------------------------------------------------
    # LLM-backed prompt builders - one per field type. Each takes the raw
    # transcript and returns a prompt asking the model to either clean it
    # up (OK:<value>) or ask a short Urdu follow-up (RETRY:<question>).
    # ---------------------------------------------------------------

    def build_number_prompt(self, field_label, expected_length=None):
        length_note = f" جواب بالکل {expected_length} ہندسوں کا ہونا چاہیے۔" if expected_length else ""

        def _builder(raw):
            return (
                f"صارف نے '{field_label}' کے سوال کا جواب اردو میں بولا ہے، جو نیچے درج ہے۔ "
                "اسے صرف ہندسوں (0 سے 9) میں بدل دیں، کوئی حرف یا اسپیس نہ چھوڑیں۔" + length_note + "\n"
                "اگر جواب واضح اور مکمل ہے تو صرف یہ لکھیں: OK:<ہندسے>\n"
                "اگر جواب نامکمل یا غیر واضح ہے تو یہ لکھیں: RETRY:<مختصر اردو سوال>\n"
                "صرف ایک لائن دیں، کوئی وضاحت نہ دیں۔\n\n"
                f"صارف کا جواب: {raw}"
            )
        return _builder

    def build_dob_prompt(self, raw):
        return (
            "صارف نے اپنی تاریخ پیدائش اردو میں بتائی ہے، جو نیچے درج ہے۔ "
            "اسے YYYY-MM-DD فارمیٹ میں تبدیل کریں (مثلاً 2005-03-14)۔\n"
            "اگر دن، مہینہ اور سال تینوں واضح ہیں تو صرف یہ لکھیں: OK:<YYYY-MM-DD>\n"
            "اگر کچھ نامکمل یا غیر واضح ہے تو یہ لکھیں: RETRY:<مختصر اردو سوال، مثلاً کونسا مہینہ؟>\n"
            "صرف ایک لائن دیں، کوئی وضاحت نہ دیں۔\n\n"
            f"صارف کا جواب: {raw}"
        )

    def build_place_prompt(self, field_label, raw, known_list=None):
        if known_list:
            listing = "، ".join(known_list)
            hint = (
                f"ممکنہ فہرست یہ ہے: {listing}۔ اگر جواب ان میں سے کسی سے ملتا ہے تو وہی نام عین اسی ہجے میں واپس کریں۔ "
                "اگر فہرست میں کوئی مماثل نہیں تو صارف کا بولا ہوا نام درست ہجے میں لکھ کر واپس کریں۔"
            )
        else:
            hint = "صارف کا بولا ہوا مقامی جگہ کا نام درست ہجے میں لکھ کر واپس کریں۔"
        return (
            f"صارف نے '{field_label}' کے سوال کا جواب اردو میں بتایا ہے، جو نیچے درج ہے۔\n{hint}\n"
            "اگر جواب واضح ہے تو صرف یہ لکھیں: OK:<نام>\n"
            "اگر جواب سمجھ نہیں آیا تو یہ لکھیں: RETRY:<مختصر اردو سوال>\n"
            "صرف ایک لائن دیں، کوئی وضاحت نہ دیں۔\n\n"
            f"صارف کا جواب: {raw}"
        )

    def build_choice_number_prompt(self, raw, options_count):
        """Used by ask_choice - the user was asked to speak a plain number
        (1..options_count). This handles spoken number words ("دو", "تین"
        وغیرہ) that fast_digit_extract can't catch since they're not
        literal digit characters."""
        return (
            f"صارف کو {options_count} آپشنز میں سے ایک نمبر بولنا تھا، 1 سے {options_count} کے درمیان۔ "
            "صارف کا جواب نیچے درج ہے۔ اس میں سے صرف نمبر نکالیں۔\n"
            "اگر واضح نمبر مل جائے تو صرف یہ لکھیں: OK:<نمبر>\n"
            "اگر نمبر واضح نہیں ہے یا رینج سے باہر ہے تو یہ لکھیں: RETRY:<مختصر اردو سوال>\n"
            "صرف ایک لائن دیں، کوئی وضاحت نہ دیں۔\n\n"
            f"صارف کا جواب: {raw}"
        )

    # ---------------------------------------------------------------
    # Generic field collector - ask, transcribe, clean with the LLM,
    # retry with a spoken follow-up if unclear.
    # ---------------------------------------------------------------

    async def ask_llm_field(self, question, build_prompt, retries=3, fast_digits=False, expected_length=None):
        await self.capability_worker.speak(question)
        raw = (await self._listen()).strip()
        if self.exit_requested:
            return ""

        for _attempt in range(retries):
            if fast_digits:
                quick = self.fast_digit_extract(raw)
                if quick and (expected_length is None or len(quick) == expected_length):
                    return quick

            result = self.parse_llm_field(
                self.capability_worker.text_to_text_response(build_prompt(raw)), raw
            )
            if result.startswith("OK:"):
                value = result[3:].strip()
                if fast_digits:
                    value = self.fast_digit_extract(value) or value
                return value

            follow_up = result[6:].strip() or "معذرت، سمجھ نہیں آیا۔ ذرا آہستہ اور دوبارہ بتا دیں؟"
            await self.capability_worker.speak(follow_up)
            raw = (await self._listen()).strip()
            if self.exit_requested:
                return ""

        return raw  # fall back to the raw transcript after retries

    # ---------------------------------------------------------------
    # Email - the user TYPES this (see voice_agent.html / the "transcribed"
    # message flow), so we take it exactly as typed. No spoken at-the-rate/
    # dot workaround, no "just the part before @" splitting, no hardcoded
    # gmail.com domain - all of that existed only to work around STT
    # unreliability for spoken addresses, which no longer applies here.
    # ---------------------------------------------------------------

    async def confirm_email(self, email):
        await self.capability_worker.speak(
            f"میں نے آپ کا ای میل یہ نوٹ کیا ہے: {email}۔ اگر یہ درست ہے تو 'OK' کہیں۔"
        )
        confirm = await self._listen()
        if self.exit_requested:
            return False
        return self.is_affirmative(confirm)

    async def ask_email(self, question, retries=3, allow_skip=True):
        await self.capability_worker.speak(question)

        for _attempt in range(retries):
            raw = (await self._listen()).strip()
            if self.exit_requested:
                return None
            if allow_skip and self.is_no_email(raw):
                return None

            email = raw.replace(" ", "").strip(".,;")
            if self.is_valid_email(email):
                email = email.lower()
                if await self.confirm_email(email):
                    return email
                await self.capability_worker.speak("ٹھیک ہے، ایک بار پھر اپنا ای میل ایڈریس لکھیں۔")
                continue

            await self.capability_worker.speak(
                "یہ درست ای میل ایڈریس نہیں لگ رہا۔ براہ کرم دوبارہ لکھیں، جیسے name@example.com۔"
            )

        # Gave it a fair shot - move on without an email rather than
        # looping forever.
        return None

    # ---------------------------------------------------------------
    # Numbered-choice collector - for any field with a finite, known
    # list of options (province, city, domicile, branch). Reads the
    # options out with numbers and asks the user to just speak the
    # number, which is far more reliable over voice/STT than trying to
    # transcribe a full place name correctly.
    # ---------------------------------------------------------------

    async def ask_choice(self, question, options, retries=3):
        if not options:
            return None

        listing = "، ".join(f"نمبر {i + 1} {opt}" for i, opt in enumerate(options))
        await self.capability_worker.speak(f"{question} براہ کرم صرف نمبر بول کر بتائیں: {listing}۔")
        raw = (await self._listen()).strip()
        if self.exit_requested:
            return None

        for _attempt in range(retries):
            # Fast path: transcript has a literal digit or a plain number word
            quick = self.resolve_spoken_number(raw)
            if quick and 1 <= quick <= len(options):
                return options[quick - 1]

            # Fall back to the LLM for anything trickier (numbers buried in
            # a longer sentence, unusual phrasing, etc.)
            result = self.parse_llm_field(
                self.capability_worker.text_to_text_response(
                    self.build_choice_number_prompt(raw, len(options))
                ),
                raw,
            )
            if result.startswith("OK:"):
                resolved = self.resolve_spoken_number(result[3:].strip())
                if resolved and 1 <= resolved <= len(options):
                    return options[resolved - 1]

            follow_up = (
                result[6:].strip() if result.startswith("RETRY:") and result[6:].strip()
                else f"معذرت، صرف 1 سے {len(options)} کے درمیان نمبر بتا دیں۔"
            )
            await self.capability_worker.speak(follow_up)
            raw = (await self._listen()).strip()
            if self.exit_requested:
                return None

        return None  # exhausted retries - caller decides how to handle this

    async def ask_branch(self, city, retries=3):
        """Fetch the real branch list, narrow it down to branches in the
        citizen's chosen city (matching the city's English keyword against
        each branch's address), and let them pick one by number. Branches
        outside the chosen city are never read out."""
        status, data = await self.api_call("GET", "/api/branches")
        all_branches = data.get("branches", []) if data.get("success") else []

        keywords = CITY_BRANCH_KEYWORDS.get(city, [])
        if keywords and all_branches:
            city_branches = [b for b in all_branches if any(kw in b.lower() for kw in keywords)]
        else:
            # unknown city (not in our keyword map) - fall back to the full list
            city_branches = all_branches

        if not city_branches:
            # nothing matched this city - let them speak a branch name instead
            # of getting stuck with an empty numbered list
            return await self.ask_llm_field(
                f"معذرت، {city} میں کوئی برانچ نہیں ملی۔ براہ کرم قریبی برانچ کا نام بتائیں۔",
                lambda raw: self.build_place_prompt("برانچ", raw, all_branches),
                retries=retries,
            )

        if len(city_branches) == 1:
            # only one branch in this city - nothing to choose between
            only = city_branches[0]
            await self.capability_worker.speak(f"آپ کے شہر میں صرف ایک برانچ ہے: {only}۔")
            return only

        return await self.ask_choice(
            "آپ کس برانچ سے ٹوکن لینا چاہتے ہیں؟",
            city_branches,
            retries=retries,
        )

    async def api_call(self, method, path, json_body=None, token=None):
        """Wrapper around aiohttp with unified error handling for the Flask API."""
        headers = {"ngrok-skip-browser-warning": "true"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method, f"{self.api_base}{path}", json=json_body,
                    headers=headers, timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    data = await resp.json()
                    return resp.status, data
        except aiohttp.ClientConnectorError:
            return 0, {"success": False, "error": "connection_failed",
                       "message": "Could not reach the passport server"}
        except aiohttp.ServerTimeoutError:
            return 0, {"success": False, "error": "timeout",
                       "message": "Server took too long to respond"}
        except Exception as e:
            return 0, {"success": False, "error": "unknown", "message": str(e)}

    # ---------------------------------------------------------------
    # Admin / kiosk auto-login - silent, no user interaction. This is what
    # replaces asking the citizen for a CNIC/password. A couple of quiet
    # retries guard against a transient ngrok/network blip.
    # ---------------------------------------------------------------

    async def auto_login_admin(self, admin_cnic, admin_password, retries=2):
        for attempt in range(retries):
            status, data = await self.api_call("POST", "/api/signin", {
                "cnic": admin_cnic, "password": admin_password,
            })
            if data.get("success"):
                return data.get("api_token"), data.get("user")

            self.worker.editor_logging_handler.info(
                f"[passport-token] admin auto-login attempt {attempt + 1} failed "
                f"(status={status}): {data.get('message')}"
            )
            if attempt < retries - 1:
                await self.worker.session_tasks.sleep(1)

        return None, None

    # ---------------------------------------------------------------
    # Main conversation flow - entirely in Urdu
    # ---------------------------------------------------------------

    async def run(self):
        try:
            await self.capability_worker.speak(
                "السلام علیکم! پاسپورٹ ٹوکن سسٹم میں خوش آمدید۔ "
                "میں آپ سے چند آسان سوالات پوچھوں گا تاکہ آپ کا ٹوکن بن سکے۔ "
                "آپ آرام سے، اپنی زبان میں جواب دیں، اگر کوئی سوال سمجھ نہ آئے تو بتا دیجیے گا۔ "
                "کسی بھی وقت 'روک دیں' کہہ کر یہ عمل بند کر سکتے ہیں۔"
            )

            self.api_base = self.capability_worker.get_api_keys(API_BASE_KEY)
            admin_cnic = self.capability_worker.get_api_keys(ADMIN_CNIC_KEY)
            admin_password = self.capability_worker.get_api_keys(ADMIN_PASSWORD_KEY)

            if not self.api_base or not admin_cnic or not admin_password:
                self.worker.editor_logging_handler.error(
                    "[passport-token] missing required API keys - configure "
                    f"{API_BASE_KEY}, {ADMIN_CNIC_KEY}, and {ADMIN_PASSWORD_KEY} in Settings"
                )
                await self.capability_worker.speak(
                    "معذرت، سسٹم ابھی درست طریقے سے سیٹ اپ نہیں ہوا۔ براہ کرم عملے کو بتائیں۔"
                )
                return

            api_token, user = await self.auto_login_admin(admin_cnic, admin_password)

            if not api_token:
                await self.capability_worker.speak(
                    "معذرت، سسٹم اس وقت دستیاب نہیں ہے۔ براہ کرم تھوڑی دیر بعد دوبارہ کوشش کریں یا برانچ کے عملے سے رابطہ کریں۔"
                )
                return

            await self.handle_token_generation(api_token, user)

            if self.exit_requested:
                self.worker.editor_logging_handler.info("[passport-token] user exited the flow")
                await self.capability_worker.speak(
                    "ٹھیک ہے، میں یہ عمل روک رہا ہوں۔ جب چاہیں دوبارہ کوشش کر سکتے ہیں۔"
                )

        except Exception as exc:
            self.worker.editor_logging_handler.info(f"[passport-token] unexpected error: {exc}")
            await self.capability_worker.speak("معذرت، کچھ غلط ہو گیا۔ براہ کرم دوبارہ کوشش کریں۔")
        finally:
            self.capability_worker.resume_normal_flow()

    # ---------------------------------------------------------------
    # Token generation (the actual form fill)
    # ---------------------------------------------------------------

    async def handle_token_generation(self, api_token, user):
        await self.capability_worker.speak("سب سے پہلے بتائیں، درخواست دہندہ کا پورا نام کیا ہے؟")
        name = (await self._listen()).strip()
        if self.exit_requested:
            return

        age = await self.ask_llm_field(
            "درخواست دہندہ کی عمر کتنی ہے؟",
            self.build_number_prompt("عمر"),
            fast_digits=True,
        )
        if self.exit_requested:
            return
        if not age or not age.isdigit():
            await self.capability_worker.speak(
                "معذرت، عمر ٹھیک طرح سمجھ نہیں آئی۔ براہ کرم چیٹ باکس میں ٹائپ کر دیں۔"
            )
            return

        dob = await self.ask_llm_field(
            "تاریخ پیدائش کیا ہے؟ دن، مہینہ اور سال کے ساتھ بتائیں، جیسے چودہ مارچ دو ہزار پانچ۔",
            self.build_dob_prompt,
        )
        if self.exit_requested:
            return

        cnic = await self.ask_llm_field(
            "درخواست دہندہ کا شناختی کارڈ نمبر بتائیں، تیرہ ہندسوں کا، ایک ایک ہندسہ کر کے آہستہ آہستہ۔",
            self.build_number_prompt("شناختی کارڈ نمبر", 13),
            fast_digits=True, expected_length=13,
        )
        if self.exit_requested:
            return

        email = await self.ask_email(
            "اب اپنا مکمل ای میل ایڈریس لکھیں، تاکہ ٹوکن کی رسید آپ کو ای میل پر بھی مل جائے۔ "
            "اگر ای میل نہ ہو تو 'نہیں ہے' لکھ دیں۔"
        )
        if self.exit_requested:
            return
        if not email:
            await self.capability_worker.speak(
                "کوئی بات نہیں، ای میل کے بغیر بھی آپ کا ٹوکن بن جائے گا، بس ٹوکن نمبر ضرور لکھ لیجیے گا۔"
            )

        await self.capability_worker.speak("گھر کا مکمل پتہ کیا ہے؟")
        address = (await self._listen()).strip()
        if self.exit_requested:
            return

        # Province, city, district, and domicile all come from a fixed,
        # known list - the UI (voice_agent.html) shows each one as clickable
        # buttons, parsed straight out of the "نمبر 1 X، نمبر 2 Y..." listing
        # that ask_choice() below speaks/writes; the citizen can just as
        # easily tap a button, say the number out loud, or type it.
        province = await self.ask_choice("آپ کا تعلق کس صوبے سے ہے؟", PROVINCES)
        if self.exit_requested:
            return
        if not province:
            await self.capability_worker.speak(
                "معذرت، صوبے کا انتخاب واضح نہیں ہو سکا۔ براہ کرم چیٹ باکس میں لکھ دیں۔"
            )
            return

        # Everything below is narrowed down to the cities/districts inside
        # the province just picked (e.g. choosing "پنجاب" means only
        # Punjab's cities show up as options here), instead of listing all
        # 25 cities nationwide every time.
        province_cities = PROVINCE_CITIES.get(province, COMMON_CITIES)

        city = await self.ask_choice("شہر کونسا ہے؟", province_cities)
        if self.exit_requested:
            return
        if not city:
            await self.capability_worker.speak(
                "معذرت، شہر کا انتخاب واضح نہیں ہو سکا۔ براہ کرم چیٹ باکس میں لکھ دیں۔"
            )
            return

        district = await self.ask_choice("ضلع کونسا ہے؟", province_cities)
        if self.exit_requested:
            return
        if not district:
            await self.capability_worker.speak(
                "معذرت، ضلع کا انتخاب واضح نہیں ہو سکا۔ براہ کرم چیٹ باکس میں لکھ دیں۔"
            )
            return

        domicile = await self.ask_choice(
            "ڈومیسائل، یعنی آپ مستقل طور پر کس ضلع کے رہائشی ہیں؟", province_cities
        )
        if self.exit_requested:
            return
        if not domicile:
            await self.capability_worker.speak(
                "معذرت، ڈومیسائل کا انتخاب واضح نہیں ہو سکا۔ براہ کرم چیٹ باکس میں لکھ دیں۔"
            )
            return

        # Branch list is narrowed down to the chosen city first, so we only
        # ever read out branches that are actually relevant to the user.
        branch = await self.ask_branch(city)
        if self.exit_requested:
            return
        if not branch:
            await self.capability_worker.speak(
                "معذرت، برانچ کا نام آواز سے نہیں مل سکا۔ براہ کرم چیٹ باکس میں صحیح برانچ کا نام ٹائپ کر دیں۔"
            )
            return

        father_cnic = mother_cnic = None
        if age.isdigit() and int(age) < 18:
            await self.capability_worker.speak(
                "چونکہ درخواست دہندہ کم عمر ہیں، اس لیے مجھے والدین کا شناختی کارڈ نمبر بھی چاہیے۔"
            )
            father_cnic = await self.ask_llm_field(
                "والد کا شناختی کارڈ نمبر بتائیں۔",
                self.build_number_prompt("والد کا شناختی کارڈ نمبر", 13),
                fast_digits=True, expected_length=13,
            )
            if self.exit_requested:
                return
            mother_cnic = await self.ask_llm_field(
                "والدہ کا شناختی کارڈ نمبر بتائیں۔",
                self.build_number_prompt("والدہ کا شناختی کارڈ نمبر", 13),
                fast_digits=True, expected_length=13,
            )
            if self.exit_requested:
                return

        # ------------------------------------------------------------
        # Everything above happens - and is heard by the citizen - in
        # Urdu, since that's the language they speak. The backend record
        # is meant to be stored in English though, so translate/convert
        # right here, immediately before submission:
        #   - name / address: free-form Urdu text -> transliterated to
        #     English via the LLM (to_english).
        #   - province / city / district / domicile: picked from a fixed
        #     Urdu list -> looked up in the pre-built English dicts (no LLM
        #     call, no risk of mistranslation).
        #   - branch: almost always already English (it comes straight from
        #     /api/branches), so it's only translated if the free-form
        #     fallback in ask_branch() happened to return Urdu text.
        #   - age / dob / cnic / father_cnic / mother_cnic / email: already
        #     digits, ISO date, or typed ASCII, so nothing to convert.
        # No speak() calls happen in this block, so nothing changes about
        # what the citizen hears.
        # ------------------------------------------------------------
        name_en = self.to_english(name)
        address_en = self.to_english(address)
        district_en = CITY_EN.get(district) or self.to_english(district)
        province_en = PROVINCES_EN.get(province) or self.to_english(province)
        city_en = CITY_EN.get(city) or self.to_english(city)
        domicile_en = CITY_EN.get(domicile) or self.to_english(domicile)
        branch_en = branch if self.looks_english(branch) else self.to_english(branch)

        await self.capability_worker.speak("ایک لمحہ، میں آپ کی تفصیلات جمع کروا رہا ہوں۔")

        status, data = await self.api_call("POST", "/api/submit", {
            "name": name_en, "age": age, "dob": dob, "cnic": cnic, "email": email,
            "address": address_en, "province": province_en, "city": city_en,
            "district": district_en, "domicile": domicile_en, "branch": branch_en,
            "father_cnic": father_cnic, "mother_cnic": mother_cnic,
        }, token=api_token)

        if not data.get("success"):
            message_urdu = self.to_urdu(data.get("message"))
            await self.capability_worker.speak(f"معذرت، ٹوکن نہیں بن سکا۔ {message_urdu}")
            return

        token = data.get("token")

        # Flask's /api/submit already sends the token email itself
        # (send_passport_email inside app.py) - we just report whatever it
        # tells us in email_sent. The Ability no longer sends its own copy.
        backend_email_sent = bool(data.get("email_sent"))

        if email and backend_email_sent:
            await self.capability_worker.speak(
                f"آپ کا ٹوکن نمبر ہے {token}۔ اس کی تفصیل {email} پر بھیج دی گئی ہے، براہ کرم چیک کر لیں۔"
            )
        elif email:
            self.worker.editor_logging_handler.info(
                f"[passport-token] email delivery failed for token {token} "
                f"(backend_email_sent={backend_email_sent})"
            )
            await self.capability_worker.speak(
                f"آپ کا ٹوکن نمبر ہے {token}، یہ سسٹم میں محفوظ ہو گیا ہے۔ "
                "لیکن ای میل بھیجنے میں مسئلہ ہوا۔ براہ کرم یہ نمبر لکھ لیں اور برانچ پر یہی نمبر بتا دیں۔"
            )
        else:
            await self.capability_worker.speak(
                f"آپ کا ٹوکن نمبر ہے {token}، یہ سسٹم میں محفوظ ہو گیا ہے۔ "
                "براہ کرم یہ نمبر لکھ لیں اور برانچ پر یہی نمبر بتا دیں۔"
            )
