import json
import re
import html
from datetime import datetime, timezone

import requests
from requests.auth import HTTPBasicAuth

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


class TwilioSmsCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    prefs_file: str = "twilio_sms_prefs.json"
    prefs: dict = None

    # {{register_capability}}

    async def load_prefs(self):
        """Safe, async loading of preferences using OpenHome SDK file helpers."""
        self.prefs = {}
        try:
            exists = await self.capability_worker.check_if_file_exists(self.prefs_file, False)

            if exists:
                content = await self.capability_worker.read_file(self.prefs_file, False)
                if content:
                    self.prefs = json.loads(content)
        except Exception as e:
            if self.worker and hasattr(self.worker, 'editor_logging_handler'):
                self.worker.editor_logging_handler.error(f"Error loading prefs: {str(e)}")

        if not self.prefs:
            self.prefs = {
                "account_sid": "",
                "auth_token": "",
                "twilio_number": "",
                "contacts": {},
                "default_country_code": "+1",
                "confirm_before_send": True,
                "voice_enabled": True,
                "voice_say_voice": "alice",
                "voice_say_language": "en-US",
                "confirm_before_call": True,
                "max_call_duration": 120,
                "last_outbound_call_sid": ""
            }
            await self.save_prefs()
            return

        needs_save = False

        if "contacts" not in self.prefs:
            self.prefs["contacts"] = {}
            needs_save = True

        if "default_country_code" not in self.prefs:
            self.prefs["default_country_code"] = "+1"
            needs_save = True

        if "confirm_before_send" not in self.prefs:
            self.prefs["confirm_before_send"] = True
            needs_save = True

        voice_defaults = {
            "voice_enabled": True,
            "voice_say_voice": "alice",
            "voice_say_language": "en-US",
            "confirm_before_call": True,
            "max_call_duration": 120,
            "last_outbound_call_sid": ""
        }
        for key, default_val in voice_defaults.items():
            if key not in self.prefs:
                self.prefs[key] = default_val
                needs_save = True

        if needs_save:
            await self.save_prefs()

    async def save_prefs(self):
        """Save preferences to the JSON file async using OpenHome file helpers."""
        if self.prefs is None:
            self.prefs = {}
        try:
            content = json.dumps(self.prefs, indent=2)
            await self.capability_worker.write_file(self.prefs_file, content, False)
        except Exception as e:
            if self.worker and hasattr(self.worker, 'editor_logging_handler'):
                self.worker.editor_logging_handler.error(f"Failed to save prefs: {str(e)}")

    def twilio_request(self, method, path, data=None, params=None):
        """Execute an authenticated request to the Twilio REST API."""
        account_sid = self.prefs.get("account_sid")
        auth_token = self.prefs.get("auth_token")

        if not account_sid or not auth_token:
            return {"error": "missing_credentials"}

        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/{path}"
        auth = HTTPBasicAuth(account_sid, auth_token)

        try:
            if method == "GET":
                resp = requests.get(url, auth=auth, params=params, timeout=15)
            elif method == "POST":
                resp = requests.post(url, auth=auth, data=data, timeout=15)
            else:
                return {"error": f"unsupported method {method}"}

            if resp.status_code in (200, 201, 204):
                try:
                    return resp.json()
                except Exception:
                    return {"status": "ok"}
            else:
                error_data = resp.json() if resp.text else {}
                return {
                    "error": f"http_{resp.status_code}",
                    "message": error_data.get("message", "Unknown Twilio Error"),
                    "code": error_data.get("code", 0)
                }
        except Exception as e:
            return {"error": str(e)}

    # --- CORE VOICE & SMS METHODS ---

    def compose_twiml(self, message_text):
        """Compose TwiML for a voice message call with XML escaping."""
        voice = self.prefs.get("voice_say_voice", "alice")
        lang = self.prefs.get("voice_say_language", "en-US")

        safe_msg = html.escape(message_text)
        safe_voice = html.escape(voice)
        safe_lang = html.escape(lang)

        return (
            f'<Response>'
            f'<Pause length="1"/>'
            f'<Say voice="{safe_voice}" language="{safe_lang}">'
            f'Hello. You have a voice message from OpenHome. '
            f'{safe_msg}'
            f'</Say>'
            f'<Pause length="1"/>'
            f'<Say voice="{safe_voice}" language="{safe_lang}">'
            f'End of message. Goodbye.'
            f'</Say>'
            f'</Response>'
        )

    def send_sms(self, to_number, body):
        data = {
            "From": self.prefs.get("twilio_number", ""),
            "To": to_number,
            "Body": body,
        }
        return self.twilio_request("POST", "Messages.json", data=data)

    def make_voice_call(self, to_number, twiml):
        data = {
            "From": self.prefs.get("twilio_number", ""),
            "To": to_number,
            "Twiml": twiml,
            "Timeout": 30
        }
        return self.twilio_request("POST", "Calls.json", data=data)

    def get_recent_calls(self, limit=10, direction=None):
        """Get recent calls from the Twilio account."""
        params = {"PageSize": min(limit, 50)}
        if direction == "outbound":
            params["From"] = self.prefs.get("twilio_number", "")
        elif direction == "inbound":
            params["To"] = self.prefs.get("twilio_number", "")

        result = self.twilio_request("GET", "Calls.json", params=params)
        if isinstance(result, dict):
            return result.get("calls", [])
        return []

    # --- UTILITIES ---

    def extract_json_from_llm(self, text):
        clean_text = text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        if clean_text.startswith("```"):
            clean_text = clean_text[3:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
        try:
            return json.loads(clean_text.strip())
        except Exception:
            return {}

    def format_message_time(self, date_string):
        try:
            dt = datetime.strptime(date_string, "%a, %d %b %Y %H:%M:%S %z")
            now = datetime.now(timezone.utc)
            delta = now - dt
            hour = dt.strftime("%I:%M %p").lstrip("0")

            if delta.days == 0:
                return f"today at {hour}"
            elif delta.days == 1:
                return f"yesterday at {hour}"
            elif delta.days < 7:
                return f"on {dt.strftime('%A')} at {hour}"
            else:
                return f"on {dt.strftime('%B %d')}"
        except Exception:
            return "recently"

    def format_delivery_status(self, status):
        status_map = {
            "queued": "Your message is waiting to be sent.",
            "sending": "Your message is being sent right now.",
            "sent": "Your message was sent, but I haven't gotten delivery confirmation yet.",
            "delivered": "Your message was delivered.",
            "failed": "Your message failed to send.",
            "undelivered": "Your message couldn't be delivered.",
        }
        return status_map.get(status, f"Message status is: {status}")

    def normalize_phone_number(self, raw_number):
        digits = re.sub(r'[^\d+]', '', raw_number)
        if digits.startswith('+'):
            if len(digits) >= 11:
                return digits
            return None
        if len(digits) == 10:
            return f"{self.prefs.get('default_country_code', '+1')}{digits}"
        if len(digits) == 11 and digits.startswith('1'):
            return f"+{digits}"
        return None

    def reverse_lookup(self, phone_number):
        """Find contact name by phone number."""
        if not phone_number:
            return None
        contacts = self.prefs.get("contacts", {})
        for name, num in contacts.items():
            if num == phone_number:
                return name
        return None

    def resolve_contact(self, spoken_name):
        contacts = self.prefs.get("contacts", {})
        lower_name = spoken_name.lower().strip()

        for name, number in contacts.items():
            if name.lower() == lower_name:
                return {"name": name, "number": number}

        if contacts:
            contact_list = ", ".join(contacts.keys())
            prompt = f"""Match the spoken name to the closest contact.
            User said: "{spoken_name}"
            Available contacts: {contact_list}
            Return ONLY the exact contact name from the list, or "none" if no match."""
            result = self.capability_worker.text_to_text_response(prompt)
            clean = result.strip().strip('"').lower()
            for name, number in contacts.items():
                if name.lower() == clean:
                    return {"name": name, "number": number}
        return None

    def format_call_status(self, call):
        """Format a single call status for voice."""
        status = call.get("status", "")
        duration = call.get("duration", "0")
        dur_int = int(duration) if duration else 0

        status_map = {
            "queued": "Your call is waiting to go through.",
            "ringing": "The phone is ringing right now.",
            "in-progress": "The call is active right now.",
            "completed": f"Your call went through. It lasted {dur_int} seconds.",
            "busy": "The line was busy.",
            "no-answer": "They didn't pick up.",
            "failed": "The call couldn't connect.",
            "canceled": "That call was canceled."
        }
        return status_map.get(status, f"Call status is: {status}")

    def format_call_for_voice(self, call):
        """Format a Twilio call record for voice readback."""
        direction = call.get("direction", "")
        to_num = call.get("to", "")
        from_num = call.get("from", "")
        duration = call.get("duration")
        date_str = call.get("start_time") or call.get("date_created", "")

        if "outbound" in direction:
            other_number = to_num
        else:
            other_number = from_num

        contact_name = self.reverse_lookup(other_number)
        if contact_name:
            party = contact_name
        else:
            safe_num = other_number[-4:] if other_number else "unknown"
            party = f"an unknown number ending in {safe_num}"

        dur_int = int(duration) if duration else 0
        if dur_int == 0:
            dur_text = "no connection"
        elif dur_int < 60:
            dur_text = f"{dur_int} seconds"
        else:
            mins = dur_int // 60
            secs = dur_int % 60
            dur_text = f"{mins} minute{'s' if mins != 1 else ''}"
            if secs > 0:
                dur_text += f" and {secs} seconds"

        time_display = self.format_message_time(date_str)

        if "outbound" in direction:
            return f"You called {party} {time_display}, the call lasted {dur_text}."
        else:
            return f"{party} called you {time_display}, the call lasted {dur_text}."

    # --- VOICE CALL HANDLERS ---

    async def handle_voice_call(self, user_input):
        if not self.prefs.get("voice_enabled", True):
            await self.capability_worker.speak("Voice calls are currently disabled in your preferences.")
            return

        contacts = self.prefs.get("contacts", {})
        contact_names = ", ".join(contacts.keys())

        extract_prompt = f"""The user wants to make a phone call and leave a message. Extract the recipient and message body.
        User said: "{user_input}"
        Known contacts: {contact_names}
        Return ONLY valid JSON: {{"recipient": "contact name", "message_body": "the message to deliver"}}"""

        llm_response = self.capability_worker.text_to_text_response(extract_prompt)
        parsed_data = self.extract_json_from_llm(llm_response)

        recipient_name_raw = parsed_data.get("recipient", "").lower()
        body = parsed_data.get("message_body", "")

        if not recipient_name_raw or not body:
            await self.capability_worker.speak("I couldn't figure out who to call or what to say. Please try again.")
            return

        contact = self.resolve_contact(recipient_name_raw)
        if not contact:
            await self.capability_worker.speak(f"I don't have a contact named {recipient_name_raw}. Please add them first.")
            return

        to_number = contact["number"]
        recipient_name = contact["name"]

        if self.prefs.get("confirm_before_call", True):
            await self.capability_worker.speak(f"I'll call {recipient_name} and say: '{body}'. Place the call?")
            confirm_input = await self.capability_worker.user_response()

            if not confirm_input or not ("yes" in confirm_input.lower() or "call" in confirm_input.lower() or "sure" in confirm_input.lower() or "ok" in confirm_input.lower()):
                await self.capability_worker.speak("Call cancelled.")
                return

        await self.capability_worker.speak(f"Calling {recipient_name} now. The message will play when they pick up.")

        twiml = self.compose_twiml(body)
        result = self.make_voice_call(to_number, twiml)

        if "error" in result:
            error_code = result.get("code")
            error_message = result.get("message", str(result.get("error")))

            if self.worker and hasattr(self.worker, 'editor_logging_handler'):
                self.worker.editor_logging_handler.error(f"TWILIO CALL ERROR -> Code: {error_code}, Message: {error_message}")

            if error_code == 21211:
                await self.capability_worker.speak("That doesn't look like a valid phone number.")
            elif error_code in (21216, 21219):
                await self.capability_worker.speak("Your trial account can only call verified numbers.")
            elif error_code == 21214:
                await self.capability_worker.speak("I couldn't reach that number. It might be out of service.")
            else:
                await self.capability_worker.speak(f"Call failed. Twilio says: {error_message}")
        else:
            if "sid" in result:
                self.prefs["last_outbound_call_sid"] = result["sid"]
                await self.save_prefs()

    async def handle_read_calls(self):
        """Read recent call log."""
        await self.capability_worker.speak("Checking your recent calls...")
        calls = self.get_recent_calls(limit=5)

        if not calls:
            await self.capability_worker.speak("You don't have any recent calls.")
            return

        await self.capability_worker.speak(f"You have {len(calls)} recent calls.")
        for i, call in enumerate(calls):
            spoken_text = self.format_call_for_voice(call)
            prefix = "First" if i == 0 else "Next"
            await self.capability_worker.speak(f"{prefix}, {spoken_text}")

    async def handle_check_call(self):
        """Check status of the last placed call."""
        last_sid = self.prefs.get("last_outbound_call_sid")
        if not last_sid:
            await self.capability_worker.speak("You haven't made any voice calls recently that I can check.")
            return

        await self.capability_worker.speak("Checking call status...")
        result = self.twilio_request("GET", f"Calls/{last_sid}.json")

        if "error" in result:
            await self.capability_worker.speak("I couldn't reach Twilio to check the status right now.")
            return

        spoken_status = self.format_call_status(result)
        await self.capability_worker.speak(spoken_status)

    async def handle_cancel_call(self):
        """Cancel or end the last placed call."""
        last_sid = self.prefs.get("last_outbound_call_sid")
        if not last_sid:
            await self.capability_worker.speak("There is no recent call to cancel.")
            return

        result = self.twilio_request("GET", f"Calls/{last_sid}.json")
        if "error" in result:
            await self.capability_worker.speak("I couldn't reach Twilio to cancel the call.")
            return

        status = result.get("status", "")
        if status in ["queued", "ringing"]:
            cancel_res = self.twilio_request("POST", f"Calls/{last_sid}.json", data={"Status": "canceled"})
            if "error" not in cancel_res:
                await self.capability_worker.speak("The call has been successfully canceled.")
            else:
                await self.capability_worker.speak("I tried to cancel it, but it might have already connected.")
        elif status == "in-progress":
            end_res = self.twilio_request("POST", f"Calls/{last_sid}.json", data={"Status": "completed"})
            if "error" not in end_res:
                await self.capability_worker.speak("The call was in progress, but I have ended it.")
            else:
                await self.capability_worker.speak("I couldn't end the active call.")
        else:
            await self.capability_worker.speak(f"It's too late to cancel. The call is already {status}.")

    # --- SMS HANDLERS (UNCHANGED) ---

    async def handle_read_texts(self):
        await self.capability_worker.speak("Checking your messages...")
        params = {"To": self.prefs.get("twilio_number", ""), "PageSize": 20}
        result = self.twilio_request("GET", "Messages.json", params=params)

        if "error" in result:
            await self.capability_worker.speak("I couldn't connect to Twilio to check your messages.")
            return

        messages = result.get("messages", [])
        inbound = [m for m in messages if m.get("direction") == "inbound"]

        if not inbound:
            await self.capability_worker.speak("You don't have any incoming messages.")
            return

        last_read_sid = self.prefs.get("last_read_sid")
        new_messages = []
        for msg in inbound:
            if msg["sid"] == last_read_sid:
                break
            new_messages.append(msg)

        messages_to_read = []
        is_new = True

        if not new_messages:
            await self.capability_worker.speak("You have no new messages. Would you like me to read your older messages anyway?")
            ans = await self.capability_worker.user_response()
            if ans and ("yes" in ans.lower() or "sure" in ans.lower() or "read" in ans.lower() or "okay" in ans.lower()):
                messages_to_read = inbound[:3]
                is_new = False
                await self.capability_worker.speak("Here are your last messages.")
            else:
                await self.capability_worker.speak("Okay.")
                return
        else:
            messages_to_read = new_messages[:5]
            if len(new_messages) == 1:
                await self.capability_worker.speak("You have 1 new message.")
            else:
                await self.capability_worker.speak(f"You have {len(new_messages)} new messages. I'll read the latest {len(messages_to_read)}.")

        for i, msg in enumerate(messages_to_read):
            sender_number = msg.get("from", "")
            contact_name = self.reverse_lookup(sender_number)
            if contact_name:
                sender_display = contact_name
            else:
                sender_display = f"an unknown number ending in {sender_number[-4:]}"

            time_display = self.format_message_time(msg.get("date_sent", ""))
            body_clean = msg.get("body", "")
            prefix = "First" if i == 0 else "Next"

            await self.capability_worker.speak(f"{prefix}, from {sender_display} {time_display}: {body_clean}")

        if is_new and new_messages:
            self.prefs["last_read_sid"] = new_messages[0]["sid"]
            await self.save_prefs()

    async def handle_send_text(self, user_input):
        contacts = self.prefs.get("contacts", {})
        contact_names = ", ".join(contacts.keys())

        extract_prompt = f"""The user wants to send a text message. Extract the recipient and message body.
        User said: "{user_input}"
        Known contacts: {contact_names}
        Return ONLY valid JSON: {{"recipient": "contact name", "body": "the message to send"}}"""

        llm_response = self.capability_worker.text_to_text_response(extract_prompt)
        parsed_data = self.extract_json_from_llm(llm_response)

        recipient_name_raw = parsed_data.get("recipient", "").lower()
        body = parsed_data.get("body", "")

        if not recipient_name_raw or not body:
            await self.capability_worker.speak("I couldn't figure out who to send that to or what to say. Please try again.")
            return

        contact = self.resolve_contact(recipient_name_raw)
        if not contact:
            await self.capability_worker.speak(f"I don't have a contact named {recipient_name_raw}. Please add them first.")
            return

        to_number = contact["number"]
        recipient_name = contact["name"]

        await self.capability_worker.speak(f"I'll text {recipient_name}: '{body}'. Should I send it?")
        confirm_input = await self.capability_worker.user_response()

        if not confirm_input:
            await self.capability_worker.speak("Message cancelled.")
            return

        if "yes" in confirm_input.lower() or "send" in confirm_input.lower() or "sure" in confirm_input.lower() or "ok" in confirm_input.lower():
            await self.capability_worker.speak("Sending...")
            result = self.send_sms(to_number, body)

            if "error" in result:
                error_code = result.get("code")
                if error_code == 21211:
                    await self.capability_worker.speak("That doesn't look like a valid phone number.")
                elif error_code == 21610:
                    await self.capability_worker.speak("That number has opted out of receiving messages.")
                elif error_code == 30005:
                    await self.capability_worker.speak("That number doesn't exist or can't receive texts.")
                else:
                    await self.capability_worker.speak("Sorry, the message failed to send. Check your account balance or number.")
            else:
                if "sid" in result:
                    self.prefs["last_sent_sid"] = result["sid"]
                    await self.save_prefs()
                await self.capability_worker.speak(f"Message sent to {recipient_name}.")
        else:
            await self.capability_worker.speak("Okay, I won't send it.")

    async def handle_check_delivery(self):
        last_sent_sid = self.prefs.get("last_sent_sid")
        if not last_sent_sid:
            await self.capability_worker.speak("You haven't sent any messages recently that I can check.")
            return

        await self.capability_worker.speak("Checking delivery status...")
        result = self.twilio_request("GET", f"Messages/{last_sent_sid}.json")

        if "error" in result:
            await self.capability_worker.speak("I couldn't check the status right now. Please try again later.")
            return

        status = result.get("status", "unknown")
        spoken_status = self.format_delivery_status(status)
        await self.capability_worker.speak(spoken_status)

    async def handle_read_from(self, user_input):
        extract_prompt = f"""The user wants to read texts from a specific person. Extract the sender's name.
        User said: "{user_input}"
        Return ONLY valid JSON: {{"sender": "contact name"}}"""

        llm_response = self.capability_worker.text_to_text_response(extract_prompt)
        parsed_data = self.extract_json_from_llm(llm_response)

        sender_name_raw = parsed_data.get("sender", "").lower()

        if not sender_name_raw:
            await self.capability_worker.speak("I couldn't figure out whose messages you want to read.")
            return

        contact = self.resolve_contact(sender_name_raw)
        if not contact:
            await self.capability_worker.speak(f"I don't have a contact named {sender_name_raw}.")
            return

        from_number = contact["number"]
        sender_name = contact["name"]

        await self.capability_worker.speak(f"Checking messages from {sender_name}...")

        params = {"To": self.prefs.get("twilio_number", ""), "From": from_number, "PageSize": 5}
        result = self.twilio_request("GET", "Messages.json", params=params)

        if "error" in result:
            await self.capability_worker.speak(f"I couldn't fetch messages from {sender_name}.")
            return

        messages = result.get("messages", [])
        inbound = [m for m in messages if m.get("direction") == "inbound"]

        if not inbound:
            await self.capability_worker.speak(f"You don't have any recent messages from {sender_name}.")
            return

        messages_to_read = inbound[:5]
        await self.capability_worker.speak(f"I found {len(messages_to_read)} recent messages from {sender_name}...")

        for i, msg in enumerate(messages_to_read):
            time_display = self.format_message_time(msg.get("date_sent", ""))
            body_clean = msg.get("body", "")
            prefix = "First" if i == 0 else "Next"
            await self.capability_worker.speak(f"{prefix}, {time_display}: {body_clean}")

    # --- CONTACT AND ACCOUNT HANDLERS ---

    async def handle_add_contact(self, user_input):
        extract_prompt = f"""Extract the contact name and phone number from the user's input.
        User said: "{user_input}"
        IMPORTANT: Format the phone number as digits only (convert words to digits).
        Return ONLY valid JSON: {{"name": "contact name", "number": "phone number"}}
        If either is missing, return an empty string."""

        llm_response = self.capability_worker.text_to_text_response(extract_prompt)
        parsed_data = self.extract_json_from_llm(llm_response)

        name = parsed_data.get("name", "").lower()
        raw_number = parsed_data.get("number", "")

        if not name or not raw_number:
            await self.capability_worker.speak("I didn't catch the name or the phone number. Try saying, 'Add Sarah with number 555 123 4567'.")
            return

        clean_number = self.normalize_phone_number(raw_number)
        if not clean_number:
            await self.capability_worker.speak(f"The number {raw_number} doesn't look like a valid phone number.")
            return

        await self.capability_worker.speak(f"I will save {name} as {clean_number}. Is that correct?")
        confirm = await self.capability_worker.user_response()

        if confirm and ("yes" in confirm.lower() or "sure" in confirm.lower() or "ok" in confirm.lower() or "right" in confirm.lower()):
            contacts = self.prefs.get("contacts", {})
            contacts[name] = clean_number
            self.prefs["contacts"] = contacts
            await self.save_prefs()
            await self.capability_worker.speak(f"{name} has been added to your contacts.")
        else:
            await self.capability_worker.speak("Okay, I canceled it.")

    async def handle_remove_contact(self, user_input):
        contacts = self.prefs.get("contacts", {})
        if not contacts:
            await self.capability_worker.speak("You don't have any contacts saved yet.")
            return

        contact_names = ", ".join(contacts.keys())
        extract_prompt = f"""Extract the contact name the user wants to remove.
        User said: "{user_input}"
        Known contacts: {contact_names}
        Return ONLY valid JSON: {{"name": "contact name"}}"""

        llm_response = self.capability_worker.text_to_text_response(extract_prompt)
        parsed_data = self.extract_json_from_llm(llm_response)

        name = parsed_data.get("name", "").lower()
        if not name or name not in contacts:
            await self.capability_worker.speak(f"I couldn't find {name} in your contacts. You currently have: {contact_names}.")
            return

        await self.capability_worker.speak(f"Are you sure you want to remove {name} from your contacts?")
        confirm = await self.capability_worker.user_response()

        if confirm and ("yes" in confirm.lower() or "sure" in confirm.lower() or "remove" in confirm.lower() or "delete" in confirm.lower()):
            del contacts[name]
            self.prefs["contacts"] = contacts
            await self.save_prefs()
            await self.capability_worker.speak(f"{name} has been removed.")
        else:
            await self.capability_worker.speak(f"Okay, {name} was not removed.")

    async def handle_list_contacts(self):
        contacts = self.prefs.get("contacts", {})
        if not contacts:
            await self.capability_worker.speak("You don't have any contacts saved yet.")
            return

        names = list(contacts.keys())
        if len(names) == 1:
            await self.capability_worker.speak(f"You have 1 contact: {names[0]}.")
        else:
            names_str = ", ".join(names[:-1]) + ", and " + names[-1]
            await self.capability_worker.speak(f"You have {len(names)} contacts: {names_str}.")

    async def handle_account_balance(self):
        await self.capability_worker.speak("Checking your Twilio balance...")
        result = self.twilio_request("GET", "Balance.json")

        if "error" in result:
            await self.capability_worker.speak("I couldn't retrieve your account balance.")
            return

        balance = result.get("balance", "unknown")
        currency = result.get("currency", "")
        await self.capability_worker.speak(f"Your Twilio account balance is {balance} {currency}.")

    # --- MAIN LOOP ---

    async def run(self):
        try:
            await self.load_prefs()

            if not self.prefs.get("account_sid") or not self.prefs.get("auth_token") or not self.prefs.get("twilio_number"):
                await self.capability_worker.speak("Twilio credentials are missing. Please configure your Account SID, Auth Token, and Twilio phone number in the preferences file.")
                return

            await self.capability_worker.speak("Twilio is ready. What would you like to do?")

            while True:
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    await self.capability_worker.speak("Please say something like 'Call mom', 'Send a text' or 'Read my calls'.")
                    continue

                lower_input = user_input.lower().strip()

                if lower_input in ["exit", "stop", "quit", "done"]:
                    await self.capability_worker.speak("Exiting. Goodbye.")
                    break

                classify_prompt = f"""You are a voice command router. Classify the user's intent based on their input.
                Intents:
                - voice_call (e.g., "call mom and tell her...", "leave a message for dad")
                - read_calls (e.g., "read my calls", "who called me", "recent calls")
                - check_call (e.g., "did my call go through", "what happened with the call")
                - cancel_call (e.g., "cancel that call", "stop don't call")
                - send_text (e.g., "send a text to john", "message mom")
                - read_texts (e.g., "read my messages", "check texts", "any new texts")
                - read_from (e.g., "what did robot say", "read texts from john")
                - check_delivery (e.g., "did my text go through", "was it delivered")
                - account_balance (e.g., "how much Twilio credit", "account balance")
                - add_contact (e.g., "add a contact", "save number")
                - remove_contact (e.g., "remove contact", "delete john")
                - list_contacts (e.g., "who is in my contacts", "show contacts")
                - exit (e.g., "stop", "exit")
                - unknown

                User said: "{user_input}"
                Return ONLY valid JSON: {{"intent": "string"}}"""

                llm_response = self.capability_worker.text_to_text_response(classify_prompt)
                parsed_intent = self.extract_json_from_llm(llm_response)
                intent = parsed_intent.get("intent", "unknown")

                if intent == "voice_call":
                    await self.handle_voice_call(user_input)
                elif intent == "read_calls":
                    await self.handle_read_calls()
                elif intent == "check_call":
                    await self.handle_check_call()
                elif intent == "cancel_call":
                    await self.handle_cancel_call()
                elif intent == "send_text":
                    await self.handle_send_text(user_input)
                elif intent == "read_texts":
                    await self.handle_read_texts()
                elif intent == "read_from":
                    await self.handle_read_from(user_input)
                elif intent == "check_delivery":
                    await self.handle_check_delivery()
                elif intent == "account_balance":
                    await self.handle_account_balance()
                elif intent == "add_contact":
                    await self.handle_add_contact(user_input)
                elif intent == "remove_contact":
                    await self.handle_remove_contact(user_input)
                elif intent == "list_contacts":
                    await self.handle_list_contacts()
                elif intent == "exit":
                    await self.capability_worker.speak("Goodbye.")
                    break
                else:
                    await self.capability_worker.speak("I didn't catch that. You can say 'Call someone', 'Read my calls', or 'Send a text'.")

                await self.capability_worker.speak("Anything else?")

        except Exception as e:
            if self.worker and hasattr(self.worker, 'editor_logging_handler'):
                self.worker.editor_logging_handler.error(f"Crash: {str(e)}")
            await self.capability_worker.speak("An internal error occurred.")
        finally:
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())
