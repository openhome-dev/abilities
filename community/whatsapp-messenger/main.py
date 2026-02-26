import json
import re
from typing import ClassVar

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# WHATSAPP MESSENGER
# Voice-controlled WhatsApp sender via OpenClaw CLI.
# Say who to message and what to say — all by voice.
#
# Contacts are stored locally at ~/.openclaw/wa-contacts.json:
#   { "ali": "+923001234567", "mom": "+11234567890" }
# Unknown contacts are asked for once and auto-saved for next time.
# =============================================================================


class WhatsappMessengerCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    @staticmethod
    def _strip_json_fences(raw: str) -> str:
        """Remove markdown code fences if the LLM wrapped the JSON in them."""
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            inner = lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]
            raw = "\n".join(inner).strip()
        return raw

    CONTACTS_FILE: ClassVar[str] = "~/.openclaw/wa-contacts.json"

    async def _lookup_contact(self, name: str) -> str:
        """Look up an E.164 number by name from ~/.openclaw/wa-contacts.json."""
        try:
            exists = await self.capability_worker.check_if_file_exists(self.CONTACTS_FILE, False)
            if not exists:
                return ""
            raw = await self.capability_worker.read_file(self.CONTACTS_FILE, False)
            contacts = json.loads(raw)
            self.worker.editor_logging_handler.info(f"Parsed contacts: {contacts}")
            name_lower = name.lower()
            for contact_name, number in contacts.items():
                cn_lower = contact_name.lower()
                if cn_lower == name_lower or name_lower in cn_lower or cn_lower in name_lower:
                    return number
        except Exception as e:
            self.worker.editor_logging_handler.info(f"Contact lookup failed: {e}")
        return ""

    async def _auto_learn_contact(self, name: str, number: str):
        """Save a new name→number pair to ~/.openclaw/wa-contacts.json."""
        try:
            safe_name = re.sub(r"[^a-zA-Z0-9 _-]", "", name.lower())[:40].strip()
            safe_number = re.sub(r"[^+\d]", "", number)[:20]
            if not safe_name or not safe_number:
                return
            contacts = {}
            exists = await self.capability_worker.check_if_file_exists(self.CONTACTS_FILE, False)
            if exists:
                raw = await self.capability_worker.read_file(self.CONTACTS_FILE, False)
                try:
                    contacts = json.loads(raw)
                except Exception:
                    pass
            contacts[safe_name] = safe_number
            await self.capability_worker.write_file(
                self.CONTACTS_FILE, json.dumps(contacts, indent=2), False
            )
            self.worker.editor_logging_handler.info(f"Auto-learned: {safe_name} → {safe_number}")
        except Exception as e:
            self.worker.editor_logging_handler.info(f"Auto-learn failed: {e}")

    async def _send_whatsapp(self, number: str, message: str) -> bool:
        """Send WhatsApp message via the openclaw CLI through exec_local_command."""
        safe_msg = message.replace('"', '\\"')
        cmd = f'openclaw message send --channel whatsapp --target "{number}" --message "{safe_msg}"'

        self.worker.editor_logging_handler.info(f"Running: {cmd}")
        response = await self.capability_worker.exec_local_command(cmd)
        self.worker.editor_logging_handler.info(f"Response: {response}")

        data = response.get("data", "") if isinstance(response, dict) else str(response)
        data_lower = data.lower()
        return "messageid" in data_lower or "sent" in data_lower or "success" in data_lower

    async def run(self):
        try:
            user_input = await self.capability_worker.run_io_loop(
                "Who do you want to message on WhatsApp, and what do you want to say?"
            )
            if not user_input or not user_input.strip():
                await self.capability_worker.speak("I didn't catch that. Try again later.")
                return

            self.worker.editor_logging_handler.info(f"User input: '{user_input.strip()}'")

            # LLM extracts recipient (name or number) and message text in one call
            extract_prompt = (
                f"The user dictated a WhatsApp message by voice. The transcription is: '{user_input}'. "
                "Note: voice transcription may be noisy — interpret names and words loosely. "
                "Extract the recipient (a person's name or phone number) and the message to send. "
                "Return ONLY valid JSON with no markdown formatting: "
                '{"recipient": "contact name or E.164 number, or empty string if unclear", "message": "message text or empty string"}'
            )
            raw = self.capability_worker.text_to_text_response(extract_prompt).strip()
            raw = self._strip_json_fences(raw)
            self.worker.editor_logging_handler.info(f"LLM extraction: {raw}")

            try:
                parsed = json.loads(raw)
                recipient = parsed.get("recipient", "").strip()
                message_text = parsed.get("message", "").strip()
            except Exception:
                recipient = ""
                message_text = ""

            # Ask for recipient if not extracted at all
            if not recipient:
                recipient_input = await self.capability_worker.run_io_loop(
                    "I didn't catch who to send to. Please say just the name or number."
                )
                if not recipient_input or not recipient_input.strip():
                    await self.capability_worker.speak("No recipient provided. Cancelled.")
                    return
                name_prompt = (
                    f"The user was asked for a WhatsApp contact name or phone number. "
                    f"They said: '{recipient_input.strip()}'. "
                    "Extract ONLY the contact name or phone number. "
                    "Return just the name or number, nothing else. No quotes, no explanation."
                )
                recipient = self.capability_worker.text_to_text_response(name_prompt).strip().strip("'\"")
                self.worker.editor_logging_handler.info(f"Recipient from voice: '{recipient_input.strip()}' → extracted: '{recipient}'")

            # Normalize non-Latin names (e.g. अली → Ali from voice transcription)
            if recipient and not recipient.lstrip("+").isdigit() and not recipient.isascii():
                norm_prompt = (
                    f"Convert this name to English/Latin script: '{recipient}'. "
                    "Return ONLY the romanized name, nothing else."
                )
                normalized = self.capability_worker.text_to_text_response(norm_prompt).strip().strip("'\".")
                self.worker.editor_logging_handler.info(f"Normalized '{recipient}' → '{normalized}'")
                if normalized and normalized.isascii():
                    recipient = normalized

            # If recipient is a name (not an E.164 number), look it up in contacts file
            number = recipient
            display_name = recipient
            if not recipient.lstrip("+").isdigit():
                self.worker.editor_logging_handler.info(f"Looking up contact: '{recipient}'")
                number = await self._lookup_contact(recipient)
                if number:
                    display_name = recipient.title()
                    self.worker.editor_logging_handler.info(f"Resolved '{recipient}' → {number}")
                else:
                    # Name not found — ask for the number then auto-save it
                    num_input = await self.capability_worker.run_io_loop(
                        f"I don't have a number for {recipient}. What's their WhatsApp number?"
                    )
                    if not num_input or not num_input.strip():
                        await self.capability_worker.speak("No number provided. Cancelled.")
                        return
                    digits = "".join(filter(str.isdigit, num_input))
                    if len(digits) < 7:
                        await self.capability_worker.speak("That doesn't look like a valid number. Cancelled.")
                        return
                    number = "+" + digits
                    self.worker.editor_logging_handler.info(f"Number from voice: {number}")
                    await self._auto_learn_contact(recipient, number)
                    display_name = recipient.title()

            # Ask for message if not extracted
            if not message_text:
                msg_input = await self.capability_worker.run_io_loop(
                    "What message do you want to send?"
                )
                message_text = msg_input.strip() if msg_input else ""
                if not message_text:
                    await self.capability_worker.speak("No message to send. Cancelled.")
                    return

            self.worker.editor_logging_handler.info(
                f"Sending to {number} ({display_name}): '{message_text}'"
            )
            await self.capability_worker.speak(
                f"Sending to {display_name}: {message_text}"
            )

            success = await self._send_whatsapp(number, message_text)

            if success:
                await self.capability_worker.speak("Message sent!")
            else:
                await self.capability_worker.speak(
                    "Sorry, the message couldn't be sent. Make sure WhatsApp is connected in OpenClaw."
                )

        except Exception as e:
            self.worker.editor_logging_handler.error(f"WhatsApp error: {e}")
            await self.capability_worker.speak("Sorry, I ran into an error.")
        finally:
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.editor_logging_handler.info("WhatsApp Messenger ACTIVE")
        self.worker.session_tasks.create(self.run())
