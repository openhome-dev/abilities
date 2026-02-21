import json
import os
import re
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
    
    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        """Registers the capability by loading config from config.json."""
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def load_prefs(self):
        """Safe loading of preferences without overwriting existing data."""
        self.prefs = {}
        try:
            with open(self.prefs_file, "r") as f:
                self.prefs = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            # If the file does not exist (first run), create a clean template
            self.prefs = {
                "account_sid": "",
                "auth_token": "",
                "twilio_number": "",
                "contacts": {},
                "default_country_code": "+1",
                "confirm_before_send": True
            }
            self.save_prefs()
            return

        # If the file exists, verify the structure without touching user keys
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

        if needs_save:
            self.save_prefs()
            
    def save_prefs(self):
        """Save preferences to the JSON file."""
        if self.prefs is None:
            self.prefs = {}
        try:
            with open(self.prefs_file, "w") as f:
                json.dump(self.prefs, f, indent=2)
        except Exception:
            pass

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

    def send_sms(self, to_number, body):
        """Send an SMS via the Twilio API."""
        data = {
            "From": self.prefs.get("twilio_number", ""),
            "To": to_number,
            "Body": body,
        }
        return self.twilio_request("POST", "Messages.json", data=data)

    def extract_json_from_llm(self, text):
        """Clean markdown formatting from the LLM response and parse the JSON."""
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

    def clean_message_for_voice(self, body):
        """Clean SMS text and expand abbreviations for Text-to-Speech (TTS)."""
        replacements = {
            "lol": "L O L", "omg": "O M G", "btw": "by the way",
            "imo": "in my opinion", "idk": "I don't know", "tbh": "to be honest", 
            "fyi": "for your information", "brb": "be right back", "rn": "right now", 
            "nvm": "never mind", "lmk": "let me know", "ty": "thank you", 
            "np": "no problem", "ur": "your", "u": "you", "r": "are", "k": "okay"
        }
        words = body.split()
        cleaned = []
        for word in words:
            lower = word.lower().strip('.,!?')
            if lower in replacements:
                cleaned.append(replacements[lower])
            else:
                cleaned.append(word)
        result = " ".join(cleaned)
        
        # Replace URLs with spoken equivalent
        result = re.sub(r'https?://\S+', 'a link', result)
        
        # Truncate long messages
        if len(result) > 500:
            result = result[:500] + "... message truncated."
        return result

    def format_message_time(self, date_string):
        """Convert a Twilio date string into a human-readable format."""
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
                day = dt.strftime("%A")
                return f"on {day} at {hour}"
            else:
                return f"on {dt.strftime('%B %d')}"
        except Exception:
            return "recently"

    def format_delivery_status(self, status):
        """Translate Twilio system status into a voice-friendly text."""
        status_map = {
            "queued": "Your message is waiting to be sent.",
            "sending": "Your message is being sent right now.",
            "sent": "Your message was sent, but I haven't gotten delivery confirmation yet.",
            "delivered": "Your message was delivered.",
            "failed": "Your message failed to send.",
            "undelivered": "Your message couldn't be delivered. The number might be wrong or they may have opted out.",
        }
        return status_map.get(status, f"Message status is: {status}")

    def normalize_phone_number(self, raw_number):
        """Normalize a spoken phone number to E.164 format."""
        digits = re.sub(r'[^\d+]', '', raw_number)
        
        if digits.startswith('+'):
            return digits if len(digits) >= 11 else None
            
        if len(digits) == 10:
            default_cc = self.prefs.get("default_country_code", "+1")
            return f"{default_cc}{digits}"
            
        if len(digits) == 11 and digits.startswith('1'):
            return f"+{digits}"
            
        return None

    def resolve_contact(self, spoken_name):
        """Smart contact search (Exact match first, then LLM fuzzy search)."""
        contacts = self.prefs.get("contacts", {})
        lower_name = spoken_name.lower().strip()
        
        # 1. Exact match
        for name, number in contacts.items():
            if name.lower() == lower_name:
                return {"name": name, "number": number}

        # 2. Fuzzy search via LLM
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

    # --- CONTACT MANAGEMENT HANDLERS ---

    async def handle_add_contact(self, user_input):
        """Logic for adding a new contact."""
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
            self.save_prefs()
            await self.capability_worker.speak(f"{name} has been added to your contacts.")
        else:
            await self.capability_worker.speak("Okay, I canceled it.")

    async def handle_remove_contact(self, user_input):
        """Logic for removing a contact."""
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
            self.save_prefs()
            await self.capability_worker.speak(f"{name} has been removed.")
        else:
            await self.capability_worker.speak(f"Okay, {name} was not removed.")

    async def handle_list_contacts(self):
        """Logic for listing all saved contacts."""
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

    # --- EXISTING HANDLERS ---

    async def handle_account_balance(self):
        """Check the Twilio account balance."""
        await self.capability_worker.speak("Checking your Twilio balance...")
        result = self.twilio_request("GET", "Balance.json")
        
        if "error" in result:
            await self.capability_worker.speak("I couldn't retrieve your account balance.")
            return
            
        balance = result.get("balance", "unknown")
        currency = result.get("currency", "")
        await self.capability_worker.speak(f"Your Twilio account balance is {balance} {currency}.")

    async def handle_read_from(self, user_input):
        """Read recent messages from a specific contact."""
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
        await self.capability_worker.speak(f"I found {len(messages_to_read)} recent messages from {sender_name}.")

        for i, msg in enumerate(messages_to_read):
            time_display = self.format_message_time(msg.get("date_sent", ""))
            body_clean = self.clean_message_for_voice(msg.get("body", ""))
            prefix = "First" if i == 0 else "Next"
            await self.capability_worker.speak(f"{prefix}, {time_display}: {body_clean}")

    async def handle_read_texts(self):
        """Fetch and read the latest incoming SMS messages."""
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

        contacts = self.prefs.get("contacts", {})

        for i, msg in enumerate(messages_to_read):
            sender_number = msg.get("from", "")
            contact_name = None
            for name, num in contacts.items():
                if num == sender_number:
                    contact_name = name
                    break
            
            if contact_name:
                sender_display = contact_name
            else:
                sender_display = f"an unknown number ending in {sender_number[-4:]}"

            time_display = self.format_message_time(msg.get("date_sent", ""))
            body_clean = self.clean_message_for_voice(msg.get("body", ""))

            prefix = "First" if i == 0 else "Next"
            
            await self.capability_worker.speak(f"{prefix}, from {sender_display} {time_display}: {body_clean}")

        if is_new and new_messages:
            self.prefs["last_read_sid"] = new_messages[0]["sid"]
            self.save_prefs()

    async def handle_send_text(self, user_input):
        """Parse recipient and body, and send an SMS."""
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
                    self.save_prefs()
                await self.capability_worker.speak(f"Message sent to {recipient_name}.")
        else:
            await self.capability_worker.speak("Okay, I won't send it.")

    async def handle_check_delivery(self):
        """Check the delivery status of the last sent message."""
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

    async def run(self):
        """Main interaction loop for the capability."""
        try:
            self.load_prefs()
            
            if not self.prefs.get("account_sid") or not self.prefs.get("auth_token") or not self.prefs.get("twilio_number"):
                await self.capability_worker.speak("Twilio credentials are missing. Please configure your Account SID, Auth Token, and Twilio phone number in the preferences file.")
                return

            await self.capability_worker.speak("Twilio SMS is ready. What would you like to do?")

            while True:
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    await self.capability_worker.speak("Please say something like 'Send a text' or 'Read my messages'.")
                    continue

                lower_input = user_input.lower().strip()

                if lower_input in ["exit", "stop", "quit", "done"]:
                    await self.capability_worker.speak("Exiting. Goodbye.")
                    break

                classify_prompt = f"""You are a voice command router. Classify the user's intent based on their input.
                Intents: 
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

                if intent == "send_text":
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
                    await self.capability_worker.speak("I didn't catch that. You can say 'Send a text', 'Read messages', or 'List contacts'.")

                await self.capability_worker.speak("Anything else?")

        except Exception as e:
            if self.worker and hasattr(self.worker, 'editor_logging_handler'):
                # Correctly using .error() to avoid "not callable" issue
                self.worker.editor_logging_handler.error(f"Crash: {str(e)}")
            await self.capability_worker.speak("An internal error occurred.")
        finally:
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())