import asyncio
import datetime
import json

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# REHNUMA — a spoken Urdu guide for people who cannot read.
#
# Explains utility bills and official documents out loud, walks the user
# through government processes (CNIC, passport, bay form), and remembers
# saved bills so later questions like "mera bill kab due hai" can be answered.
#
# The document wallet is optional. Save the base URL of your own wallet
# server in OpenHome Settings -> API Keys under the name below. Without it
# the ability still answers government process questions normally.
# See README.md for the two endpoints a wallet server must expose.
# =============================================================================

SERVER_URL_KEY = "rehnuma_server_url"   # label in Settings -> API Keys
REQUEST_TIMEOUT = 8
EMAIL_TIMEOUT = 45                      # sending renders a file, so allow more
MAX_DOCUMENTS_CHARS = 8000              # keep the prompt inside a sane budget
RECENT_TURNS = 10                       # conversation lines kept for context

INTRO_PROMPT = ("Ji, Rehnuma haazir hai. Bill ya form ke baare mein poochein, "
                "ya bill ki photo bhej kar mujh se poochein.")
EXIT_PROMPT = "Theek hai, Allah Hafiz. Zaroorat ho to phir bula lijiye ga."
NOT_UNDERSTOOD = "Maaf kijiye, main samajh nahi paya. Zara phir se kahiye."
PHOTO_FOUND = "Ji, aap ka bheja hua kaghaz mil gaya hai. Suniye."
ERROR_PROMPT = ("Maaf kijiye, abhi kuch gadbad ho gayi hai. "
                "Thori der baad phir koshish kijiye ga.")
MAIL_SENT = "Ji, aap ke email par bhej diya hai."
MAIL_NO_ADDRESS = ("Aap ka email address abhi mehfooz nahi hai. Website par "
                   "apna email likh dein, phir main bhej doon ga.")
MAIL_FAILED = ("Maaf kijiye, email nahi ja saka. "
               "Zara baad mein koshish karte hain.")
EXPLAIN_NEWEST = ("Sab se naya uploaded document tafseel se samjhao: yeh kya "
                  "hai, kitne paise dene hain ya is mein kya likha hai, aakhri "
                  "tareekh kya hai, koi khaas baat ho to woh bhi batao.")

# Hindi speech-to-text returns Devanagari, so every exit word is listed in
# Roman, Devanagari and Urdu script.
EXIT_WORDS = ("shukriya", "khuda hafiz", "allah hafiz", "khatam", "bas",
              "bye", "exit", "stop", "goodbye",
              "शुक्रिया", "ख़ुदा हाफ़िज़", "खुदा हाफिज", "अल्लाह हाफ़िज़",
              "अल्लाह हाफिज", "खत्म", "बस",
              "شکریہ", "خدا حافظ", "اللہ حافظ", "ختم", "بس")

# Words that mean "I was asking about the photo I just sent" — used to avoid
# answering the same question twice when a new upload arrives mid-turn.
PHOTO_WORDS = ("photo", "tasveer", "kaghaz", "bhej",
               "फोटो", "काग़ज़", "तस्वीर", "تصویر", "کاغذ")

# Any mention of email means the user wants the document sent. Kept broad on
# purpose: a missed match lets the model answer instead, and it may then claim
# to have sent something it did not.
MAIL_WORDS = ("email", "e mail", "e-mail", "mail", "gmail", "imel", "inbox",
              "forward", "send it", "send me", "send this", "send the bill",
              "ईमेल", "इमेल", "मेल", "ई मेल", "जीमेल",
              "ای میل", "ایمیل", "میل", "جی میل")

BASE_PROMPT = """You are Rehnuma, a calm, patient male voice guide for people
in Pakistan who cannot read. You explain bills, official documents and
government processes (CNIC renewal, passport, bay form, bank and school
forms).

LANGUAGE RULES:
1. Reply only in simple spoken Urdu written in Roman letters, for example:
   Aap ka bill 2400 rupay hai.
2. Everyday Urdu words: raqam, tareekh, bijli, jurmana, baqaya, daftar.
3. Never start a reply with any greeting or salutation. Answer directly.
4. Numbers stay as plain digits: 2400 rupay, 15 July. Never convert them
   into Urdu words.
5. Two to four short sentences. No lists, no markdown. Text is spoken aloud.
6. You are male: samajh gaya, karta hoon, bata doon ga. Never karti hoon.
7. The user cannot read. Explain what things mean and what to do. Never tell
   them to read something.

ANSWERING RULES:
- The user's saved documents are given below as JSON. Answer bill and
  document questions from them. Match which document the user means by month,
  issuer, address, name or amount. If several match and the answer differs,
  ask one short question naming the choices. If none match, say honestly you
  do not have that record and ask them to send a photo of it.
- For government process questions give practical steps: documents to take,
  fee, where to go, what to say to the clerk. Rough fees: CNIC renewal
  normal 750 rupay urgent 2050, passport 10 saal normal 9000 urgent 15000,
  bay form union council 200 se 500. CNIC and passport need NADRA / passport
  office visit, Pak-ID app works for CNIC renewal at home.
- If unsure of a fact, say so honestly and name the right office or helpline.
- NEVER claim you have sent an email. Emailing is handled by the system, not
  by you. If the user seems to want a document emailed, ask them to say the
  word email clearly, for example: email kar dein.
- Use today's date for anything time related: how many days remain, whether a
  due date has passed. If any saved bill's due date is within the next 3 days
  or already passed, begin your FIRST reply of the conversation with one short
  warning line starting with: Yaad dahani. Do this once only, never repeat it.

TODAY'S DATE: {today}

USER'S SAVED DOCUMENTS:
{documents}

RECENT CONVERSATION (resolve words like uska, woh from here):
{recent}"""


class RehnumaBillReaderCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    server_url: str = ""

    # {{register capability}}

    # --- logging helpers -----------------------------------------------

    def _log(self, message: str):
        self.worker.editor_logging_handler.info(f"[Rehnuma] {message}")

    def _err(self, message: str):
        self.worker.editor_logging_handler.error(f"[Rehnuma] {message}")

    # --- document wallet -------------------------------------------------

    def _load_server_url(self) -> str:
        """Read the wallet server base URL from Settings -> API Keys.
        Returns an empty string when the user has not configured one."""
        try:
            value = self.capability_worker.get_api_keys(SERVER_URL_KEY)
            if isinstance(value, str):
                return value.strip().rstrip("/")
        except Exception as error:
            self._err(f"server URL lookup failed: {error!r}")
        return ""

    def fetch_documents(self) -> list:
        """Every document the user has uploaded, newest last. Blocking —
        always call through asyncio.to_thread."""
        if not self.server_url:
            return []
        try:
            response = requests.get(f"{self.server_url}/api/documents",
                                    timeout=REQUEST_TIMEOUT)
            if response.status_code != 200:
                self._err(f"/api/documents returned {response.status_code}")
                return []
            documents = response.json()
            return documents if isinstance(documents, list) else []
        except Exception as error:
            self._err(f"/api/documents failed: {error!r}")
            return []

    def has_new_photo(self) -> bool:
        """True when an upload has arrived that we have not spoken about yet.
        Blocking — always call through asyncio.to_thread."""
        if not self.server_url:
            return False
        try:
            response = requests.get(f"{self.server_url}/api/pending",
                                    timeout=REQUEST_TIMEOUT)
            if response.status_code != 200:
                self._err(f"/api/pending returned {response.status_code}")
                return False
            pending = response.json()
            return bool(pending and pending.get("data"))
        except Exception as error:
            self._err(f"/api/pending failed: {error!r}")
            return False

    def wants_email(self, text: str) -> bool:
        """True when the user asked for a document to be emailed."""
        lowered = (text or "").lower()
        return any(word in lowered for word in MAIL_WORDS)

    def send_email(self, hint: str = "") -> str:
        """Ask the wallet server to email the document the user meant, and
        return the line to speak back. The server chooses the document from the
        hint and holds the address, so no personal data passes through here.
        Blocking — always call through asyncio.to_thread."""
        if not self.server_url:
            self._log("email requested but no wallet server is configured")
            return MAIL_FAILED
        try:
            response = requests.post(f"{self.server_url}/api/email_send",
                                     json={"hint": hint},
                                     timeout=EMAIL_TIMEOUT)
            body = response.json() if response.content else {}
            if response.status_code == 200 and body.get("ok"):
                return MAIL_SENT
            error = str(body.get("error", ""))
            if "no email" in error.lower():
                return MAIL_NO_ADDRESS
            self._err(f"/api/email_send returned "
                      f"{response.status_code}: {error[:200]}")
        except Exception as error:
            self._err(f"/api/email_send failed: {error!r}")
        return MAIL_FAILED

    # --- conversation ----------------------------------------------------

    def is_exit(self, text: str) -> bool:
        """Match exit words as whole tokens so that 'bas' does not fire inside
        an unrelated word, while multi word phrases match as substrings."""
        lowered = (text or "").lower()
        tokens = lowered.replace("?", " ").replace("؟", " ").split()
        for word in EXIT_WORDS:
            if " " in word:
                if word in lowered:
                    return True
            elif word in tokens:
                return True
        return False

    def answer(self, user_input: str, documents: list, recent: list) -> str:
        """Ask the LLM the user's question with the saved documents, today's
        date and the recent turns as context. Blocking — call via to_thread."""
        system_prompt = BASE_PROMPT.format(
            today=datetime.date.today().strftime("%d %B %Y"),
            documents=json.dumps(documents,
                                 ensure_ascii=False)[:MAX_DOCUMENTS_CHARS],
            recent="\n".join(recent) if recent else "(none)")
        try:
            return self.capability_worker.text_to_text_response(
                user_input, system_prompt=system_prompt)
        except Exception as error:
            self._err(f"LLM call failed: {error!r}")
            return ""

    async def _announce_new_photo(self, recent: list) -> list:
        """Speak an explanation of the newest upload and return the updated
        recent-turns list."""
        await self.capability_worker.speak(PHOTO_FOUND)
        documents = await asyncio.to_thread(self.fetch_documents)
        reply = await asyncio.to_thread(self.answer, EXPLAIN_NEWEST,
                                        documents, recent)
        if not reply:
            await self.capability_worker.speak(ERROR_PROMPT)
            return recent
        await self.capability_worker.speak(reply)
        return (recent + ["User: (naya kaghaz bheja)",
                          f"Rehnuma: {reply}"])[-RECENT_TURNS:]

    async def qa_loop(self):
        await self.capability_worker.speak(INTRO_PROMPT)
        recent = []

        # A photo may already be waiting from before the user spoke.
        if await asyncio.to_thread(self.has_new_photo):
            recent = await self._announce_new_photo(recent)

        while True:
            user_input = await self.capability_worker.user_response()

            if not user_input or not user_input.strip():
                continue

            if self.is_exit(user_input):
                break

            # Checked before anything else: emailing is done by the server, so
            # the request must not reach the LLM, which would otherwise reply
            # as though it had sent the message itself.
            if self.wants_email(user_input):
                line = await asyncio.to_thread(self.send_email, user_input)
                await self.capability_worker.speak(line)
                recent = (recent + [f"User: {user_input}",
                                    f"Rehnuma: {line}"])[-RECENT_TURNS:]
                continue

            # A photo can land mid-conversation; explain it before answering.
            if await asyncio.to_thread(self.has_new_photo):
                recent = await self._announce_new_photo(recent)
                if any(word in user_input.lower() for word in PHOTO_WORDS):
                    continue  # they were asking about this photo; already done

            documents = await asyncio.to_thread(self.fetch_documents)
            reply = await asyncio.to_thread(self.answer, user_input,
                                            documents, recent)
            await self.capability_worker.speak(reply or NOT_UNDERSTOOD)
            if reply:
                recent = (recent + [f"User: {user_input}",
                                    f"Rehnuma: {reply}"])[-RECENT_TURNS:]

        await self.capability_worker.speak(EXIT_PROMPT)

    async def run(self):
        try:
            self.server_url = self._load_server_url()
            if not self.server_url:
                # Not fatal: process guidance still works without a wallet.
                self._log("no wallet server configured; documents disabled")
            await self.qa_loop()
        except Exception as error:
            self._err(f"unhandled error: {error!r}")
            try:
                await self.capability_worker.speak(ERROR_PROMPT)
            except Exception:
                pass  # already failing; never block the exit below
        finally:
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())
