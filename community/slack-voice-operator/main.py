import json
from datetime import datetime, timezone

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

STORAGE_KEY = "slack_voice_operator"

HOTWORDS = {
    "check my slack", "slack update", "slack messages", "open slack",
    "what's on slack", "any slack", "slack notification", "slack notifications",
    "any mentions", "did anyone ping me", "check my pings", "new in slack",
    "message on slack", "send a slack", "slack message to", "send slack",
    "message via slack", "dm on slack", "slack message",
    "list my slack channels", "my slack channels", "slack channels",
    "what's in slack", "what happened in slack", "what did i miss on slack",
    "change my slack", "slack settings", "update my slack",
}

EXIT_WORDS = {"stop", "done", "exit", "quit", "bye", "cancel", "nothing"}
EXIT_PHRASES = {"that's all", "thats all", "no thanks", "never mind"}

INTENTS = {"MENTIONS", "SUMMARY", "SEND", "CHANNELS", "SETUP", "EXIT"}


class SlackVoiceOperator(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    slack_client: WebClient = None

    # Do not change following tag of register capability
    # {{register capability}}

    def does_match(self, text: str) -> bool:
        text_lower = text.lower()
        return any(h in text_lower for h in HOTWORDS)

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self._run())

    async def _run(self):
        try:
            trigger = await self.capability_worker.wait_for_complete_transcription()

            token = self.capability_worker.get_slack_key() or ""
            if not token:
                await self.capability_worker.speak(
                    "Your Slack account isn't linked yet. "
                    "Go to app dot openhome dot com, open Settings, and link your Slack account to get started."
                )
                return

            self.slack_client = WebClient(token=token)

            config = self._load_config()
            fresh_setup = not (config and config.get("slack_user_id"))

            if fresh_setup:
                config = await self._handle_setup(config or {})
                if not config:
                    return
            else:
                if trigger and not self._is_exit(trigger):
                    intent = self._classify_intent(trigger)
                    if intent == "EXIT":
                        await self.capability_worker.speak("Sure, I'll let you know if anything important comes in.")
                        return
                    await self._dispatch(intent, trigger, config)

            while True:
                reply = await self.capability_worker.user_response()
                if not reply or self._is_exit(reply):
                    await self.capability_worker.speak("Got it. I'll ping you if any important mentions come in.")
                    break
                intent = self._classify_intent(reply)
                if intent == "EXIT":
                    await self.capability_worker.speak("Got it. I'll ping you if any important mentions come in.")
                    break
                await self._dispatch(intent, reply, config)

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[SlackVoiceOperator] Error: {e}")
        finally:
            self.capability_worker.resume_normal_flow()

    # ── Setup ──────────────────────────────────────────────────────────────

    async def _handle_setup(self, config: dict) -> dict:
        user_name = await self._load_user_name()
        if not user_name:
            await self.capability_worker.speak("What's your name?")
            reply = await self.capability_worker.user_response()
            if reply:
                user_name = self.capability_worker.text_to_text_response(
                    f"Extract the first name from: '{reply}'. Return only the name."
                ).strip()
        config["user_name"] = user_name

        try:
            auth = self.slack_client.auth_test()
            config["slack_user_id"] = auth["user_id"]
            workspace = auth.get("team", "your workspace")
        except SlackApiError as e:
            await self.capability_worker.speak(
                "I couldn't connect to Slack. "
                "Check that your account is properly linked in OpenHome settings."
            )
            self.worker.editor_logging_handler.error(f"[SlackVoiceOperator] auth_test: {e}")
            return None

        greeting = f"Hi {user_name}! " if user_name else ""
        await self.capability_worker.speak(
            f"{greeting}Connected to {workspace}. Let me fetch your channels."
        )

        channels = self._fetch_all_channels()
        config["channel_cache"] = channels

        if not channels:
            await self.capability_worker.speak(
                "I connected to Slack but couldn't find any channels. "
                "Make sure you're a member of at least one channel, then try again."
            )
            return None

        sample = ", ".join(f"#{c['name']}" for c in channels[:5])
        suffix = f" and {len(channels) - 5} more" if len(channels) > 5 else ""
        await self.capability_worker.speak(
            f"Found {len(channels)} channel{'s' if len(channels) != 1 else ''} — "
            f"{sample}{suffix}. "
            "Which channels should I watch for mentions in the background? "
            "Say the names, or say 'all' to watch everything."
        )
        watch_reply = await self.capability_worker.user_response()
        if not watch_reply or "all" in (watch_reply or "").lower():
            watch = channels[:10]
        else:
            watch = self._match_channels_from_utterance(watch_reply, channels)
            if not watch:
                watch = channels[:3]

        config["watch_channels"] = [c["id"] for c in watch]
        config["watch_channel_names"] = [c["name"] for c in watch]
        config["last_mention_ts"] = str(datetime.now(timezone.utc).timestamp())

        watch_names = ", ".join(f"#{n}" for n in config["watch_channel_names"])
        await self.capability_worker.speak(
            f"All set. I'll watch {watch_names} for mentions. What would you like to check?"
        )

        self._save_config(config)
        return config

    # ── Intent dispatch ────────────────────────────────────────────────────

    async def _dispatch(self, intent: str, utterance: str, config: dict):
        if intent == "MENTIONS":
            await self._handle_mentions(config)
        elif intent == "SUMMARY":
            await self._handle_summary(utterance, config)
        elif intent == "SEND":
            await self._handle_send(utterance, config)
        elif intent == "CHANNELS":
            await self._handle_channels(config)
        elif intent == "SETUP":
            updated = await self._handle_setup(config)
            if updated:
                config.update(updated)
        else:
            await self.capability_worker.speak(
                "I can check your mentions, summarize a channel, send a message, or list your channels."
            )

    # ── Mentions ───────────────────────────────────────────────────────────

    async def _handle_mentions(self, config: dict):
        user_id = config.get("slack_user_id", "")
        watch_channels = config.get("watch_channels", [])
        channel_cache = config.get("channel_cache", [])

        if not watch_channels:
            await self.capability_worker.speak(
                "You don't have any channels configured yet. Say 'change my Slack settings' to set them up."
            )
            return

        lookback = str(datetime.now(timezone.utc).timestamp() - 86400)
        mentions = []
        for ch_id in watch_channels:
            try:
                result = self.slack_client.conversations_history(
                    channel=ch_id, oldest=lookback, limit=50
                )
                for msg in result["messages"]:
                    text = msg.get("text", "")
                    if f"<@{user_id}>" in text:
                        ch_name = next((c["name"] for c in channel_cache if c["id"] == ch_id), ch_id)
                        mentions.append({"channel": ch_name, "text": text})
            except SlackApiError as e:
                self.worker.editor_logging_handler.error(f"[SlackVoiceOperator] history {ch_id}: {e}")
                continue

        if not mentions:
            await self.capability_worker.speak("No mentions in the last 24 hours. You're all clear.")
            return

        raw = "\n".join(f"[#{m['channel']}] {m['text']}" for m in mentions)
        summary = self.capability_worker.text_to_text_response(
            f"Summarize these Slack @mentions for the user. "
            f"Group by channel. Note who mentioned them and what it's about. "
            f"Be concise — 2 to 4 sentences max. Omit raw Slack user IDs.\n\n{raw}"
        )
        count = len(mentions)
        await self.capability_worker.speak(
            f"You have {count} mention{'s' if count != 1 else ''} in the last 24 hours. {summary}"
        )

    # ── Summary ────────────────────────────────────────────────────────────

    async def _handle_summary(self, utterance: str, config: dict):
        channels = config.get("channel_cache", [])
        if not channels:
            await self.capability_worker.speak("Let me refresh your channel list first.")
            channels = self._fetch_all_channels()
            config["channel_cache"] = channels
            self._save_config(config)

        if not channels:
            await self.capability_worker.speak(
                "I couldn't find any channels. Check that your Slack account is properly linked."
            )
            return

        channel_list = ", ".join(c["name"] for c in channels)
        target_name = self.capability_worker.text_to_text_response(
            f"From this request: '{utterance}', identify which Slack channel the user wants to summarize. "
            f"Available channels: {channel_list}. "
            f"Return only the exact channel name from the list, or NONE if not mentioned."
        ).strip().lower().lstrip("#")

        if target_name == "none" or not target_name:
            await self.capability_worker.speak("Which channel would you like me to summarize?")
            reply = await self.capability_worker.user_response()
            if not reply:
                return
            target_name = reply.lower().strip().lstrip("#")

        channel = self._fuzzy_match_channel(target_name, channels)
        if not channel:
            await self.capability_worker.speak(
                f"I couldn't match '{target_name}' to a channel. Try using the full channel name."
            )
            return

        try:
            result = self.slack_client.conversations_history(channel=channel["id"], limit=25)
            messages = [m for m in result["messages"] if m.get("text")]
        except SlackApiError as e:
            await self.capability_worker.speak(
                f"I couldn't read #{channel['name']}. "
                "Make sure you're a member of that channel."
            )
            self.worker.editor_logging_handler.error(f"[SlackVoiceOperator] history: {e}")
            return

        if not messages:
            await self.capability_worker.speak(f"#{channel['name']} has been quiet — no recent messages.")
            return

        raw = "\n".join(f"- {m['text']}" for m in reversed(messages))
        summary = self.capability_worker.text_to_text_response(
            f"Summarize this Slack channel activity in 2 to 3 sentences. "
            f"Focus on decisions made, blockers raised, and action items. "
            f"Skip small talk and greetings. Omit raw Slack user IDs.\n\n{raw}"
        )
        await self.capability_worker.speak(f"Here's what's happening in #{channel['name']}: {summary}")

    # ── Send ───────────────────────────────────────────────────────────────

    async def _handle_send(self, utterance: str, config: dict):
        channels = config.get("channel_cache", [])

        extracted = self.capability_worker.text_to_text_response(
            f"From this request, extract the Slack recipient and the message to send. "
            f"Recipient can be a person's name or a channel (e.g. #general). "
            f"Return JSON only — no markdown: {{\"recipient\": \"...\", \"message\": \"...\"}}\n"
            f"Request: {utterance}"
        ).strip()

        try:
            parsed = json.loads(extracted)
            recipient = parsed.get("recipient", "").strip()
            message = parsed.get("message", "").strip()
        except Exception:
            recipient = ""
            message = ""

        if not recipient or not message:
            await self.capability_worker.speak("Who should I message, and what should I say?")
            follow_up = await self.capability_worker.user_response()
            if not follow_up:
                return
            extracted2 = self.capability_worker.text_to_text_response(
                f"Extract Slack recipient and message from: '{follow_up}'. "
                f"Return JSON only: {{\"recipient\": \"...\", \"message\": \"...\"}}"
            ).strip()
            try:
                parsed2 = json.loads(extracted2)
                recipient = parsed2.get("recipient", "").strip()
                message = parsed2.get("message", "").strip()
            except Exception:
                pass

        if not recipient or not message:
            await self.capability_worker.speak("I couldn't work out who to message or what to say. Please try again.")
            return

        target_id = None
        display_name = recipient

        if recipient.startswith("#"):
            clean = recipient.lstrip("#").lower()
            matched_ch = self._fuzzy_match_channel(clean, channels)
            if matched_ch:
                target_id = matched_ch["id"]
                display_name = f"#{matched_ch['name']}"
        else:
            user_cache = config.get("user_cache") or []
            if not user_cache:
                user_cache = self._fetch_users()
                config["user_cache"] = user_cache
                self._save_config(config)
            matched_user = self._fuzzy_match_user(recipient, user_cache)
            if matched_user:
                target_id = matched_user["id"]
                display_name = matched_user["name"]

        if not target_id:
            await self.capability_worker.speak(
                f"I couldn't find '{recipient}' in your workspace. "
                "Try using their exact Slack display name or say the channel name."
            )
            return

        confirmed = await self.capability_worker.run_confirmation_loop(
            f"Sending to {display_name}: '{message}' — shall I send it?"
        )
        if not confirmed:
            await self.capability_worker.speak("Message cancelled.")
            return

        try:
            self.slack_client.chat_postMessage(channel=target_id, text=message)
            await self.capability_worker.speak("Sent.")
        except SlackApiError as e:
            err = e.response.get("error", "unknown error")
            await self.capability_worker.speak(f"Couldn't send the message: {err}.")
            self.worker.editor_logging_handler.error(f"[SlackVoiceOperator] postMessage: {e}")

    # ── Channels ───────────────────────────────────────────────────────────

    async def _handle_channels(self, config: dict):
        channels = self._fetch_all_channels()
        if channels:
            config["channel_cache"] = channels
            self._save_config(config)

        if not channels:
            await self.capability_worker.speak("I couldn't retrieve your channel list. Check that your Slack account is linked.")
            return

        names = ", ".join(f"#{c['name']}" for c in channels[:10])
        suffix = f" — and {len(channels) - 10} more" if len(channels) > 10 else ""
        await self.capability_worker.speak(
            f"You're in {len(channels)} channel{'s' if len(channels) != 1 else ''}: {names}{suffix}."
        )

    # ── Helpers ────────────────────────────────────────────────────────────

    def _classify_intent(self, text: str) -> str:
        result = self.capability_worker.text_to_text_response(
            "Classify this Slack assistant request. Return ONLY one label.\n"
            "MENTIONS = checking @mentions or pings\n"
            "SUMMARY = summarize a channel's recent messages\n"
            "SEND = compose or send a message to someone\n"
            "CHANNELS = list or refresh available channels\n"
            "SETUP = change settings or re-configure\n"
            "EXIT = done, stop, quit, nothing\n"
            f"Request: {text}"
        ).strip().upper().split()[0]
        return result if result in INTENTS else "MENTIONS"

    def _is_exit(self, text: str) -> bool:
        text_lower = text.lower().strip()
        if any(p in text_lower for p in EXIT_PHRASES):
            return True
        return bool(set(text_lower.split()) & EXIT_WORDS)

    async def _load_user_name(self) -> str:
        for filename in ("user_profile.md", "user_summary.md"):
            try:
                content = await self.capability_worker.read_file(filename, in_ability_directory=False)
                if content:
                    name = self.capability_worker.text_to_text_response(
                        f"Extract the person's first name from this profile. "
                        f"Return only the name, or UNKNOWN if not found.\n{content}"
                    ).strip()
                    if name and name != "UNKNOWN":
                        return name
            except Exception:
                pass
        return ""

    def _fetch_all_channels(self) -> list:
        try:
            result = self.slack_client.conversations_list(
                types="public_channel,private_channel",
                exclude_archived=True,
                limit=200,
            )
            return [{"id": c["id"], "name": c["name"]} for c in result["channels"]]
        except SlackApiError as e:
            self.worker.editor_logging_handler.error(f"[SlackVoiceOperator] conversations_list: {e}")
            return []

    def _fetch_users(self) -> list:
        try:
            result = self.slack_client.users_list(limit=200)
            return [
                {
                    "id": m["id"],
                    "name": m.get("profile", {}).get("real_name") or m.get("name", ""),
                }
                for m in result["members"]
                if not m.get("is_bot") and not m.get("deleted")
            ]
        except SlackApiError as e:
            self.worker.editor_logging_handler.error(f"[SlackVoiceOperator] users_list: {e}")
            return []

    def _fuzzy_match_channel(self, query: str, channels: list) -> dict:
        query = query.lower().strip().lstrip("#")
        for c in channels:
            if c["name"].lower() == query:
                return c
        for c in channels:
            if query in c["name"].lower() or c["name"].lower() in query:
                return c
        if channels:
            name_list = ", ".join(c["name"] for c in channels)
            best = self.capability_worker.text_to_text_response(
                f"Match '{query}' to the closest channel from: {name_list}. "
                f"Return only the exact channel name, or NONE."
            ).strip().lower()
            for c in channels:
                if c["name"].lower() == best:
                    return c
        return None

    def _fuzzy_match_user(self, query: str, users: list) -> dict:
        query_lower = query.lower().strip()
        for u in users:
            if u["name"].lower() == query_lower:
                return u
        for u in users:
            if query_lower in u["name"].lower():
                return u
        if users:
            name_list = ", ".join(u["name"] for u in users[:60])
            best = self.capability_worker.text_to_text_response(
                f"Match '{query}' to the closest person from: {name_list}. "
                f"Return only the exact name, or NONE."
            ).strip()
            for u in users:
                if u["name"].lower() == best.lower():
                    return u
        return None

    def _match_channels_from_utterance(self, utterance: str, channels: list) -> list:
        name_list = ", ".join(c["name"] for c in channels)
        result = self.capability_worker.text_to_text_response(
            f"From this request: '{utterance}', extract all channel names the user wants to watch. "
            f"Match against: {name_list}. "
            f"Return a comma-separated list of exact channel names, or NONE."
        ).strip()
        if result.upper() == "NONE":
            return []
        selected = {n.strip().lstrip("#").lower() for n in result.split(",")}
        return [c for c in channels if c["name"].lower() in selected]

    def _load_config(self) -> dict:
        stored = self.capability_worker.get_single_key(STORAGE_KEY)
        return stored if stored else {}

    def _save_config(self, config: dict):
        try:
            self.capability_worker.create_key(STORAGE_KEY, config)
        except Exception:
            try:
                self.capability_worker.update_key(STORAGE_KEY, config)
            except Exception as e:
                self.worker.editor_logging_handler.error(f"[SlackVoiceOperator] Save error: {e!r}")
