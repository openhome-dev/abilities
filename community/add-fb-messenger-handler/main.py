from typing import ClassVar, Dict
import json
from datetime import datetime, timedelta, timezone
import requests

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

class MessengerHandlerFB(MatchingCapability):
    # {{register capability}}

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    PAGE_ACCESS_TOKEN: ClassVar[str] = "YOUR_PAGE_TOKEN"
    API_VERSION: ClassVar[str] = "v20.0"
    PREFS_FILE: ClassVar[str] = "messenger_prefs.json"
    PAGE_ID: ClassVar[str] = "YOUR_PAGE_ID"
    PAGE_NAME: ClassVar[str] = "YOUR_PAGE_NAME"

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            prefs = await self.load_prefs()

            # Fetch fresh data
            recent_messages, psids, unread_conversations, total_conversations = await self.fetch_recent_messages()
            stored_psids = prefs.get("psids", {})
            stored_psids.update(psids)
            prefs["psids"] = stored_psids
            prefs["messages"] = recent_messages
            await self.save_prefs(prefs)

            # Welcome
            await self.capability_worker.speak(f"Welcome to {self.PAGE_NAME}, what actions do you want to take?")

            last_context = {"last_psid": None, "last_name": None, "last_message": None}

            while True:
                action_text = await self.capability_worker.user_response()
                lower_text = action_text.lower().strip()

                # Exit only on "stop" or "exit"
                if lower_text in ["stop", "exit"]:
                    await self.capability_worker.speak("Okay, exiting Messenger handler. Goodbye!")
                    break

                # LLM parses intent semantically
                parse_prompt = f"""
User said: "{action_text}"

Correct common STT mishears: "summer iced" or "summer age" → "summarize", "samurai" → "summarize", "sin match" → "send message", "somewhere" → "summarize", "some AI" → "send AI", etc.

Consider order/context: "the last one" = last mentioned message/person, "last Android message" = last message containing "android".

Classify as one of these intents about Messenger:
- summarize: total/summary of messages/conversations
- last_unread: show last unread message
- unread_count: how many unread messages/conversations
- keyword_search: how many / search keyword/phrase
- who_sent: who sent/said/wrote specific message/word
- bulk_send: send to multiple/all matching people
- single_send: send to one person (name or her/him/them)
- last_from: last message from specific person
- unknown: anything else

Return ONLY valid JSON:
{{
  "intent": "summarize / last_unread / unread_count / keyword_search / who_sent / bulk_send / single_send / last_from / unknown",
  "keyword": "extracted keyword/phrase or null",
  "name": "person name or pronoun (her/him/them) or null",
  "message": "only actual message content if user is clearly providing short phrase to send (after being asked), otherwise null"
}}
"""
                raw = self.capability_worker.text_to_text_response(parse_prompt)
                raw = raw.replace("```json", "").replace("```", "").strip()
                try:
                    intent_data = json.loads(raw)
                    intent = intent_data.get("intent", "unknown")
                    keyword = intent_data.get("keyword")
                    name = intent_data.get("name")
                    message = intent_data.get("message")
                except:
                    intent = "unknown"

                if intent == "summarize":
                    summary = f"In the last 72 hours or most recent 20 messages, you have {total_conversations} conversations, with {unread_conversations} having unread messages."
                    await self.capability_worker.speak(summary)

                elif intent == "last_unread":
                    unread_msgs = [m for m in recent_messages if not m.get("read", False)]
                    if unread_msgs:
                        last = sorted(unread_msgs, key=lambda m: m["time"], reverse=True)[0]
                        name = stored_psids.get(last["psid"], "Unknown")
                        last_context["last_psid"] = last["psid"]
                        last_context["last_name"] = name
                        last_context["last_message"] = last["text"]
                        await self.capability_worker.speak(f"Last unread message was from {name}: {last['text']} at {last['time']}.")
                    else:
                        await self.capability_worker.speak("No unread messages from users.")

                elif intent == "unread_count":
                    await self.capability_worker.speak(f"You have {unread_conversations} conversations with unread messages from users.")

                elif intent == "keyword_search" and keyword:
                    keyword_lower = keyword.lower()
                    matching_psids = set(m["psid"] for m in recent_messages if keyword_lower in m["text"].lower())
                    count = len(matching_psids)
                    prefs["last_keyword"] = keyword_lower
                    prefs["last_matching_psids"] = list(matching_psids)
                    await self.save_prefs(prefs)
                    await self.capability_worker.speak(f"There are {count} conversations about '{keyword}'.")

                elif intent == "who_sent" and keyword:
                    keyword_lower = keyword.lower()
                    matching = [m for m in recent_messages if keyword_lower in m["text"].lower()]
                    if matching:
                        last = sorted(matching, key=lambda m: m["time"], reverse=True)[0]
                        name = stored_psids.get(last["psid"], "Unknown")
                        last_context["last_psid"] = last["psid"]
                        last_context["last_name"] = name
                        last_context["last_message"] = last["text"]
                        await self.capability_worker.speak(f"{name} sent the message: {last['text']} at {last['time']}.")
                    else:
                        await self.capability_worker.speak(f"No message containing '{keyword}' found.")

                elif intent == "bulk_send":
                    last_matching_psids = prefs.get("last_matching_psids", [])
                    count = len(last_matching_psids)
                    if count == 0:
                        await self.capability_worker.speak("No recent search matches to send to.")
                        continue

                    await self.capability_worker.speak("Sure, what message do you want to send?")
                    reply_text = await self.capability_worker.user_response()

                    while True:
                        await self.capability_worker.speak(f"Confirm send: '{reply_text}' to {count} people? Yes or no.")
                        confirm = await self.capability_worker.user_response()
                        lower_confirm = confirm.lower()
                        if "yes" in lower_confirm:
                            success_count = 0
                            for psid in last_matching_psids:
                                success = await self.send_message(psid, reply_text)
                                if success:
                                    success_count += 1
                                    for m in recent_messages:
                                        if m["psid"] == psid:
                                            m["read"] = True
                            await self.save_prefs(prefs)
                            await self.capability_worker.speak(f"Message sent to {success_count} out of {count} people.")
                            break
                        elif "no" in lower_confirm:
                            await self.capability_worker.speak("Okay, what do you want to send instead?")
                            reply_text = await self.capability_worker.user_response()
                        else:
                            await self.capability_worker.speak("Sorry, please say yes or no.")

                elif intent == "single_send" and name:
                    # Pronoun resolution
                    if name in ["her", "him", "them"]:
                        name = prefs.get("last_name", "Unknown")
                        if name == "Unknown":
                            await self.capability_worker.speak("Sorry, who do you want to send to? (I don't remember the last person)")
                            name = await self.capability_worker.user_response()

                    # Semantic name matching if no exact match
                    psid = next((p for p, n in stored_psids.items() if n.lower() == name.lower()), None)
                    if not psid:
                        names_list = list(stored_psids.values())
                        if names_list:
                            match_prompt = f"""
User is looking for a person named '{name}'.

Find the closest matching name from this list: {json.dumps(names_list)}

Return ONLY the matched name or "Unknown" if no close match.
"""
                            raw_match = self.capability_worker.text_to_text_response(match_prompt)
                            raw_match = raw_match.strip()
                            if raw_match != "Unknown":
                                name = raw_match
                                psid = next((p for p, n in stored_psids.items() if n.lower() == name.lower()), None)
                                await self.capability_worker.speak(f"Found matching name '{name}'.")

                    if not psid:
                        await self.capability_worker.speak(f"No person found with name '{name}'.")
                        continue

                    await self.capability_worker.speak(f"Sure, what message do you want to send to {name}?")
                    reply_text = await self.capability_worker.user_response()

                    while True:
                        await self.capability_worker.speak(f"Confirm send: '{reply_text}' to {name}? Yes or no.")
                        confirm = await self.capability_worker.user_response()
                        lower_confirm = confirm.lower()
                        if "yes" in lower_confirm:
                            success = await self.send_message(psid, reply_text)
                            if success:
                                await self.capability_worker.speak(f"Message sent to {name}!")
                                for m in recent_messages:
                                    if m["psid"] == psid:
                                        m["read"] = True
                                prefs["last_name"] = name
                                last_context["last_name"] = name
                                await self.save_prefs(prefs)
                            else:
                                await self.capability_worker.speak("Failed to send message.")
                            break
                        elif "no" in lower_confirm:
                            await self.capability_worker.speak("Okay, what do you want to send instead?")
                            reply_text = await self.capability_worker.user_response()
                        else:
                            await self.capability_worker.speak("Sorry, please say yes or no.")

                elif intent == "last_from" and name:
                    # Semantic name matching if no exact match
                    psid = next((p for p, n in stored_psids.items() if n.lower() == name.lower()), None)
                    if not psid:
                        names_list = list(stored_psids.values())
                        if names_list:
                            match_prompt = f"""
User is looking for a person named '{name}'.

Find the closest matching name from this list: {json.dumps(names_list)}

Return ONLY the matched name or "Unknown" if no match.
"""
                            raw_match = self.capability_worker.text_to_text_response(match_prompt)
                            raw_match = raw_match.strip()
                            if raw_match != "Unknown":
                                name = raw_match
                                psid = next((p for p, n in stored_psids.items() if n.lower() == name.lower()), None)
                                await self.capability_worker.speak(f"Found matching name '{name}'.")

                    if not psid:
                        await self.capability_worker.speak(f"No user found with name '{name}'.")
                        continue

                    user_msgs = [m for m in recent_messages if m["psid"] == psid]
                    if not user_msgs:
                        await self.capability_worker.speak(f"No messages from {name} in the last 72 hours or most recent {len(recent_messages)} messages.")
                        continue

                    last_msg = sorted(user_msgs, key=lambda m: m["time"], reverse=True)[0]
                    last_context["last_name"] = name
                    await self.capability_worker.speak(f"Last message from {name}: {last_msg['text']} at {last_msg['time']}.")

                else:
                    await self.capability_worker.speak(
                        "Sorry, I didn't understand that. Try something like 'summarize', 'last unread message', "
                        "'how many unread', 'how many about X', 'who sent X', 'send to her', or 'last message from X'."
                    )

                await self.capability_worker.speak("What else can I do?")

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Main error: {str(e)}")
            await self.capability_worker.speak("Something went wrong. Try again?")

        finally:
            self.capability_worker.resume_normal_flow()

    async def fetch_recent_messages(self):
        all_messages = []
        all_psids = {}
        all_conversations = []
        url = f"https://graph.facebook.com/{self.API_VERSION}/me/conversations"
        params = {
            "access_token": self.PAGE_ACCESS_TOKEN,
            "fields": "participants,unread_count,messages.limit(50){message,from,created_time,to}",
            "limit": 50
        }

        while url:
            response = requests.get(url, params=params)
            if response.status_code != 200:
                await self.capability_worker.speak("Failed to fetch messages from Messenger.")
                return [], {}, 0, 0

            data = response.json()
            conversations = data.get("data", [])
            all_conversations.extend(conversations)

            for convo in conversations:
                convo_messages = convo.get("messages", {}).get("data", [])
                for msg in convo_messages:
                    time_str = msg.get("created_time")
                    if not time_str:
                        continue

                    from_id = msg.get("from", {}).get("id")
                    from_name = msg.get("from", {}).get("name", "Unknown")

                    # Skip page-sent messages
                    if from_id == self.PAGE_ID:
                        continue

                    psid = from_id
                    name = from_name

                    if psid and psid != self.PAGE_ID:
                        all_psids[psid] = name
                        all_messages.append({
                            "psid": psid,
                            "name": name,
                            "text": msg.get("message", ""),
                            "time": time_str,
                            "read": False
                        })

            paging = data.get("paging", {})
            url = paging.get("next", None)
            params = {}  # Clear for next full URL

        # Unread conversations: use unread_count > 0 from API
        unread_conversations = sum(1 for c in all_conversations if c.get("unread_count", 0) > 0)

        # Total conversations: those with messages in the fetch
        total_conversations = len({m["psid"] for m in all_messages})

        return all_messages, all_psids, unread_conversations, total_conversations

    async def load_prefs(self) -> Dict:
        prefs = {
            "page_access_token": self.PAGE_ACCESS_TOKEN,
            "messages": [],
            "psids": {},
            "last_keyword": "",
            "last_matching_psids": [],
            "last_name": ""
        }
        if await self.capability_worker.check_if_file_exists(self.PREFS_FILE):
            raw = await self.capability_worker.read_file(self.PREFS_FILE)
            loaded = json.loads(raw)
            prefs.update(loaded)
        return prefs

    async def save_prefs(self, prefs: Dict):
        if await self.capability_worker.check_if_file_exists(self.PREFS_FILE):
            await self.capability_worker.delete_file(self.PREFS_FILE)
        await self.capability_worker.write_file(self.PREFS_FILE, json.dumps(prefs, ensure_ascii=False))

    async def send_message(self, psid: str, text: str) -> bool:
        url = f"https://graph.facebook.com/{self.API_VERSION}/me/messages"
        payload = {
            "recipient": {"id": psid},
            "message": {"text": text}
        }
        params = {"access_token": self.PAGE_ACCESS_TOKEN}
        try:
            response = requests.post(url, params=params, json=payload)
            if response.status_code in (200, 201):
                return True
            else:
                self.worker.editor_logging_handler.error(f"Send failed: {response.text}")
                return False
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Send error: {str(e)}")
            return False