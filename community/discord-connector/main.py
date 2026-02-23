import json
import os
import re
from datetime import datetime
from typing import Optional

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# DISCORD CONNECTOR
# A voice-powered Discord client. Read messages, post updates, get channel
# digests, and list channels — all by voice.
#
# Uses the Discord Bot API (REST v10).
# Create a bot at: https://discord.com/developers/applications
# Required bot permissions: Read Messages, Send Messages, Read Message History
# Required intent: MESSAGE_CONTENT (enable in Bot settings)
#
# After creating your bot:
# 1. Copy the Bot Token
# 2. Invite it to your server with the permissions above
# 3. Replace the placeholder below with your token
# =============================================================================

# -- Discord Bot Token --------------------------------------------------------
# Get yours at: https://discord.com/developers/applications
# 1. Create Application -> Bot -> Reset Token -> Copy
# 2. Enable MESSAGE_CONTENT intent under Bot -> Privileged Gateway Intents
# 3. Invite bot to server via OAuth2 URL Generator (scopes: bot;
#    permissions: Read Messages, Send Messages, Read Message History)
DISCORD_BOT_TOKEN = "REPLACE_WITH_YOUR_BOT_TOKEN"

# -- Discord API Base ---------------------------------------------------------
DISCORD_API_BASE = "https://discord.com/api/v10"

# -- Persistent storage -------------------------------------------------------
PREFS_FILE = "discord_connector_prefs.json"

# -- Exit detection -----------------------------------------------------------
EXIT_WORDS = [
    "done", "exit", "stop", "quit", "bye", "goodbye",
    "nothing else", "all good", "nope", "no thanks",
    "i'm good", "that's it", "that's all", "leave", "cancel",
]

# -- Intent classification prompts --------------------------------------------
TRIGGER_INTENT_PROMPT = (
    "You are classifying a user's Discord-related request.\n\n"
    "Given the user's recent messages, return ONLY a JSON object:\n"
    '{{\n'
    '    "intent": one of ["read_messages", "post_update", "digest", '
    '"list_channels", "unknown"],\n'
    '    "mode": "quick" or "full",\n'
    '    "details": {{any extracted info like channel name, message content, etc}}\n'
    '}}\n\n'
    "Rules:\n"
    '- "read_messages" = user wants to see recent messages from a channel. '
    'Mode: quick\n'
    '- "post_update" = user wants to send/post a message to Discord. '
    'Mode: quick\n'
    '- "digest" = user wants a summary of recent channel activity. '
    'Mode: quick if asking a count, full if asking to "catch me up"\n'
    '- "list_channels" = user wants to see available channels. Mode: quick\n'
    '- If the request is vague like just "discord" or "check discord", '
    'default to digest with mode: full\n\n'
    "User's recent messages:\n{context}"
)

SESSION_INTENT_PROMPT = (
    "You are classifying an in-session Discord command.\n"
    "The user is already inside the Discord assistant.\n\n"
    "Return ONLY valid JSON, no markdown:\n"
    '{{\n'
    '    "intent": one of ["read_messages", "post_update", "digest", '
    '"list_channels", "switch_channel", "unknown"],\n'
    '    "details": {{any extracted info like channel name, message content}}\n'
    '}}\n\n'
    "Examples:\n"
    '"Read me the latest messages" -> {{"intent": "read_messages", '
    '"details": {{}}}}\n'
    '"Post hey everyone" -> {{"intent": "post_update", '
    '"details": {{"content": "hey everyone"}}}}\n'
    '"Summarize the channel" -> {{"intent": "digest", "details": {{}}}}\n'
    '"Show me the channels" -> {{"intent": "list_channels", '
    '"details": {{}}}}\n'
    '"Switch to general" -> {{"intent": "switch_channel", '
    '"details": {{"channel_name": "general"}}}}\n\n'
    "User said: {user_input}"
)

DIGEST_PROMPT = (
    "Summarize these Discord messages into a short spoken briefing "
    "(2-3 sentences max). Focus on the main topics being discussed, "
    "any questions asked, and important announcements. "
    "Keep it conversational — this will be read aloud.\n\n"
    "Channel: {channel_name}\n"
    "Messages:\n{messages}"
)

MESSAGE_READOUT_PROMPT = (
    "Turn these Discord messages into a natural spoken readout. "
    "Read the most recent 5-8 messages. Say who wrote each one and "
    "what they said. Keep it brief — one sentence per message max. "
    "Skip system messages and bot spam. Format usernames naturally.\n\n"
    "Messages:\n{messages}"
)

COMPOSE_PROMPT = (
    "The user wants to post a message to Discord. Clean up their spoken "
    "input into a well-formatted Discord message. Keep the original tone "
    "and intent. Don't add emojis unless the user used them. Keep it "
    "concise.\n\n"
    "User said: {user_input}"
)


class DiscordConnectorCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    prefs: dict = None
    current_guild_id: str = None
    current_channel_id: str = None
    current_channel_name: str = None
    channels_cache: list = None
    idle_count: int = 0
    mode: str = "quick"
    history: list = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------

    async def run(self):
        try:
            self._log("info", "Discord Connector started")
            self.idle_count = 0
            self.channels_cache = None
            self.history = []
            self.prefs = await self._load_prefs()

            # Restore saved channel/guild preferences
            self.current_guild_id = self.prefs.get("guild_id")
            self.current_channel_id = self.prefs.get("channel_id")
            self.current_channel_name = self.prefs.get("channel_name")

            # Validate bot token
            if DISCORD_BOT_TOKEN == "REPLACE_WITH_YOUR_BOT_TOKEN":
                await self.capability_worker.speak(
                    "The Discord bot token hasn't been configured yet. "
                    "Please add your bot token to the ability code."
                )
                return

            # Verify token works and get bot's guilds
            if not self.current_guild_id:
                guilds = self._discord_get_guilds()
                if not guilds:
                    await self.capability_worker.speak(
                        "I couldn't connect to Discord. "
                        "Please check that the bot token is valid "
                        "and the bot has been added to a server."
                    )
                    return
                # Use first guild by default
                self.current_guild_id = guilds[0]["id"]
                self.prefs["guild_id"] = self.current_guild_id
                self.prefs["guild_name"] = guilds[0].get("name", "Unknown")

            # If no channel set, pick the first text channel
            if not self.current_channel_id:
                await self._auto_select_channel()

            # Read trigger context and classify
            trigger_context = self._get_trigger_context()
            intent_data = self._classify_trigger_intent(trigger_context)
            intent = intent_data.get("intent", "unknown")
            self.mode = intent_data.get("mode", "full")

            self._log("info", f"Trigger intent: {intent} | Mode: {self.mode}")

            if self.mode == "quick":
                await self._handle_quick_intent(intent, intent_data)
            else:
                await self._handle_full_mode(intent, intent_data)

        except Exception as e:
            self._log("error", f"Unexpected error: {e}")
            await self.capability_worker.speak(
                "Something went wrong with Discord. Try again in a moment."
            )
        finally:
            self._log("info", "Discord Connector ended")
            self.capability_worker.resume_normal_flow()

    # ------------------------------------------------------------------
    # Trigger context + intent classification
    # ------------------------------------------------------------------

    def _get_trigger_context(self) -> str:
        """Read last 5 user messages from conversation history."""
        try:
            history = self.worker.agent_memory.full_message_history
            if not history:
                return ""
            user_msgs = []
            for msg in reversed(history):
                try:
                    if isinstance(msg, dict):
                        role = msg.get("role")
                        content = msg.get("content")
                    else:
                        role = msg.role if hasattr(msg, "role") else None
                        content = (
                            msg.content if hasattr(msg, "content") else None
                        )
                    if role == "user" and content:
                        user_msgs.append(content)
                    if len(user_msgs) >= 5:
                        break
                except Exception:
                    continue
            return "\n".join(reversed(user_msgs))
        except Exception as e:
            self._log("error", f"Trigger context error: {e}")
            return ""

    def _classify_trigger_intent(self, context: str) -> dict:
        """Use LLM to classify the trigger intent."""
        if not context:
            return {"intent": "digest", "mode": "full", "details": {}}
        try:
            raw = self.capability_worker.text_to_text_response(
                TRIGGER_INTENT_PROMPT.format(context=context)
            )
            clean = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(clean)
        except (json.JSONDecodeError, Exception) as e:
            self._log("error", f"Trigger classification error: {e}")
            return {"intent": "digest", "mode": "full", "details": {}}

    def _classify_session_intent(self, user_input: str) -> dict:
        """Classify intent during an active session."""
        try:
            raw = self.capability_worker.text_to_text_response(
                SESSION_INTENT_PROMPT.format(user_input=user_input)
            )
            clean = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(clean)
        except (json.JSONDecodeError, Exception) as e:
            self._log("error", f"Session classification error: {e}")
            return {"intent": "unknown", "details": {}}

    # ------------------------------------------------------------------
    # Quick mode
    # ------------------------------------------------------------------

    async def _handle_quick_intent(self, intent: str, intent_data: dict):
        """Answer a specific question and offer brief follow-up."""
        details = intent_data.get("details", {})

        await self.capability_worker.speak("One sec, checking Discord.")
        await self._route_intent(intent, details)

        # Brief follow-up window
        await self.capability_worker.speak("Anything else with Discord?")
        follow_up = await self.capability_worker.user_response()
        if follow_up and not self._is_exit(follow_up):
            session_intent = self._classify_session_intent(follow_up)
            await self._route_intent(
                session_intent.get("intent", "unknown"),
                session_intent.get("details", {}),
            )

    # ------------------------------------------------------------------
    # Full mode
    # ------------------------------------------------------------------

    async def _handle_full_mode(self, intent: str, intent_data: dict):
        """Full interactive session with Discord."""
        details = intent_data.get("details", {})

        channel_label = self.current_channel_name or "your Discord"
        await self.capability_worker.speak(
            f"Connected to {channel_label}. Let me check what's new."
        )

        # Initial action based on trigger
        await self._route_intent(intent, details)

        # Session loop
        for _ in range(30):
            user_input = await self.capability_worker.user_response()

            if not user_input or not user_input.strip():
                self.idle_count += 1
                if self.idle_count >= 2:
                    await self.capability_worker.speak(
                        "Alright, closing Discord. Talk later!"
                    )
                    return
                continue

            self.idle_count = 0

            if self._is_exit(user_input):
                await self.capability_worker.speak(
                    "Got it. Closing Discord. Have a good one!"
                )
                return

            session_intent = self._classify_session_intent(user_input)
            await self._route_intent(
                session_intent.get("intent", "unknown"),
                session_intent.get("details", {}),
            )

    # ------------------------------------------------------------------
    # Intent routing
    # ------------------------------------------------------------------

    async def _route_intent(self, intent: str, details: dict):
        """Route a classified intent to its handler."""
        if intent == "read_messages":
            await self._handle_read_messages(details)
        elif intent == "post_update":
            await self._handle_post_update(details)
        elif intent == "digest":
            await self._handle_digest(details)
        elif intent == "list_channels":
            await self._handle_list_channels()
        elif intent == "switch_channel":
            await self._handle_switch_channel(details)
        else:
            await self.capability_worker.speak(
                "I can read messages, post updates, give you a digest, "
                "or list channels. What would you like?"
            )

    # ------------------------------------------------------------------
    # Feature handlers
    # ------------------------------------------------------------------

    async def _handle_read_messages(self, details: dict):
        """Fetch and read out recent messages from the current channel."""
        if not self.current_channel_id:
            await self.capability_worker.speak(
                "No channel selected. Say 'list channels' to pick one."
            )
            return

        messages = self._discord_get_messages(
            self.current_channel_id, limit=15
        )
        if not messages:
            await self.capability_worker.speak(
                "No recent messages in this channel, "
                "or I couldn't fetch them."
            )
            return

        formatted = self._format_messages_for_llm(messages)
        readout = self.capability_worker.text_to_text_response(
            MESSAGE_READOUT_PROMPT.format(messages=formatted)
        )
        await self.capability_worker.speak(readout)
        await self.capability_worker.speak(
            "Want to reply to the channel, or hear more?"
        )

    async def _handle_post_update(self, details: dict):
        """Compose and send a message to the current Discord channel."""
        if not self.current_channel_id:
            await self.capability_worker.speak(
                "No channel selected. Say 'list channels' to pick one."
            )
            return

        # Check if content was already provided
        content = details.get("content") or details.get("message")

        if not content:
            await self.capability_worker.speak(
                "What would you like to post?"
            )
            content = await self.capability_worker.user_response()
            if not content or self._is_exit(content):
                await self.capability_worker.speak("Post cancelled.")
                return

        # Clean up with LLM
        cleaned = self.capability_worker.text_to_text_response(
            COMPOSE_PROMPT.format(user_input=content)
        )

        # Confirm before sending
        channel_label = self.current_channel_name or "the channel"
        await self.capability_worker.speak(
            f"I'll post to {channel_label}: {cleaned}"
        )
        confirmed = await self.capability_worker.run_confirmation_loop(
            "Should I send it?"
        )

        if confirmed:
            await self.capability_worker.speak("Posting now.")
            success = self._discord_send_message(
                self.current_channel_id, cleaned
            )
            if success:
                await self.capability_worker.speak("Posted!")
            else:
                await self.capability_worker.speak(
                    "I had trouble posting that. Check bot permissions."
                )
        else:
            await self.capability_worker.speak("Okay, post cancelled.")

    async def _handle_digest(self, details: dict):
        """Generate a spoken digest of recent channel activity."""
        if not self.current_channel_id:
            await self.capability_worker.speak(
                "No channel selected. Say 'list channels' to pick one."
            )
            return

        messages = self._discord_get_messages(
            self.current_channel_id, limit=30
        )
        if not messages:
            await self.capability_worker.speak(
                "The channel is quiet — no recent messages."
            )
            return

        formatted = self._format_messages_for_llm(messages)
        channel_label = self.current_channel_name or "this channel"
        digest = self.capability_worker.text_to_text_response(
            DIGEST_PROMPT.format(
                channel_name=channel_label, messages=formatted
            )
        )
        await self.capability_worker.speak(digest)

    async def _handle_list_channels(self):
        """List available text channels in the server."""
        if not self.current_guild_id:
            await self.capability_worker.speak(
                "I'm not connected to a server."
            )
            return

        channels = self._get_text_channels()
        if not channels:
            await self.capability_worker.speak(
                "I couldn't find any text channels, "
                "or the bot doesn't have access."
            )
            return

        # Build a spoken list (max 10)
        names = [ch["name"] for ch in channels[:10]]
        channel_list = ", ".join(names)
        await self.capability_worker.speak(
            f"Here are the text channels: {channel_list}."
        )
        await self.capability_worker.speak(
            "Which channel should I switch to?"
        )

        response = await self.capability_worker.user_response()
        if response and not self._is_exit(response):
            await self._handle_switch_channel({"channel_name": response})

    async def _handle_switch_channel(self, details: dict):
        """Switch to a different text channel."""
        target_name = (details.get("channel_name") or "").lower().strip()
        if not target_name:
            await self.capability_worker.speak("Which channel?")
            target_name = await self.capability_worker.user_response()
            if not target_name or self._is_exit(target_name):
                return
            target_name = target_name.lower().strip()

        channels = self._get_text_channels()
        if not channels:
            await self.capability_worker.speak(
                "I couldn't load the channel list."
            )
            return

        # Fuzzy match
        match = None
        for ch in channels:
            if target_name in ch["name"].lower():
                match = ch
                break

        if match:
            self.current_channel_id = match["id"]
            self.current_channel_name = match["name"]
            self.prefs["channel_id"] = match["id"]
            self.prefs["channel_name"] = match["name"]
            await self._save_prefs(self.prefs)
            await self.capability_worker.speak(
                f"Switched to {match['name']}."
            )
        else:
            await self.capability_worker.speak(
                f"I couldn't find a channel matching that. "
                "Say 'list channels' to see what's available."
            )

    # ------------------------------------------------------------------
    # Auto-select first text channel
    # ------------------------------------------------------------------

    async def _auto_select_channel(self):
        """Pick the first text channel if none is configured."""
        channels = self._get_text_channels()
        if channels:
            self.current_channel_id = channels[0]["id"]
            self.current_channel_name = channels[0]["name"]
            self.prefs["channel_id"] = channels[0]["id"]
            self.prefs["channel_name"] = channels[0]["name"]
            await self._save_prefs(self.prefs)

    # ------------------------------------------------------------------
    # Discord API helpers
    # ------------------------------------------------------------------

    def _discord_request(
        self, method: str, endpoint: str, json_data: dict = None
    ) -> Optional[dict]:
        """Make an authenticated request to the Discord API."""
        url = f"{DISCORD_API_BASE}{endpoint}"
        headers = {
            "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
            "Content-Type": "application/json",
        }
        try:
            if method == "GET":
                resp = requests.get(url, headers=headers, timeout=10)
            elif method == "POST":
                resp = requests.post(
                    url, headers=headers, json=json_data, timeout=10
                )
            else:
                return None

            if resp.status_code in (200, 201):
                return resp.json()
            elif resp.status_code == 401:
                self._log("error", "Discord 401 — invalid bot token")
            elif resp.status_code == 403:
                self._log("error", "Discord 403 — missing permissions")
            elif resp.status_code == 429:
                self._log("error", "Discord 429 — rate limited")
            else:
                self._log(
                    "error",
                    f"Discord {resp.status_code}: {resp.text[:200]}",
                )
            return None
        except requests.exceptions.Timeout:
            self._log("error", "Discord request timed out")
            return None
        except Exception as e:
            self._log("error", f"Discord request failed: {e}")
            return None

    def _discord_get_guilds(self) -> list:
        """Get the bot's guilds (servers)."""
        result = self._discord_request("GET", "/users/@me/guilds")
        return result if isinstance(result, list) else []

    def _discord_get_channels(self, guild_id: str) -> list:
        """Get all channels in a guild."""
        result = self._discord_request(
            "GET", f"/guilds/{guild_id}/channels"
        )
        return result if isinstance(result, list) else []

    def _discord_get_messages(
        self, channel_id: str, limit: int = 15
    ) -> list:
        """Fetch recent messages from a channel."""
        result = self._discord_request(
            "GET", f"/channels/{channel_id}/messages?limit={limit}"
        )
        return result if isinstance(result, list) else []

    def _discord_send_message(
        self, channel_id: str, content: str
    ) -> bool:
        """Send a message to a channel."""
        result = self._discord_request(
            "POST",
            f"/channels/{channel_id}/messages",
            json_data={"content": content},
        )
        return result is not None

    def _get_text_channels(self) -> list:
        """Get text channels, using cache if available."""
        if self.channels_cache is not None:
            return self.channels_cache

        if not self.current_guild_id:
            return []

        all_channels = self._discord_get_channels(self.current_guild_id)
        # type 0 = text channel
        text_channels = [
            ch for ch in all_channels if ch.get("type") == 0
        ]
        # Sort by position
        text_channels.sort(key=lambda c: c.get("position", 0))
        self.channels_cache = text_channels
        return text_channels

    # ------------------------------------------------------------------
    # Message formatting
    # ------------------------------------------------------------------

    def _format_messages_for_llm(self, messages: list) -> str:
        """Format Discord messages as text for LLM processing."""
        lines = []
        # Messages come newest-first from Discord, reverse for chronological
        for msg in reversed(messages):
            author = msg.get("author", {}).get("username", "Unknown")
            content = msg.get("content", "")
            timestamp = msg.get("timestamp", "")

            # Skip empty messages (embeds-only, etc.)
            if not content:
                continue

            # Parse timestamp for readable time
            time_str = ""
            if timestamp:
                try:
                    dt = datetime.fromisoformat(
                        timestamp.replace("Z", "+00:00")
                    )
                    time_str = dt.strftime("%I:%M %p")
                except Exception:
                    time_str = ""

            lines.append(f"[{time_str}] {author}: {content}")

        return "\n".join(lines) if lines else "No text messages found."

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    def _is_exit(self, text: str) -> bool:
        """Check if user input contains exit intent."""
        if not text:
            return False
        lower = text.lower().strip()
        lower = re.sub(r"[^\w\s']", "", lower)
        for word in EXIT_WORDS:
            if word in lower:
                return True
        return False

    def _log(self, level: str, message: str):
        """Log to the editor logging handler."""
        handler = self.worker.editor_logging_handler
        if level == "error":
            handler.error(f"[DiscordConnector] {message}")
        elif level == "warning":
            handler.warning(f"[DiscordConnector] {message}")
        else:
            handler.info(f"[DiscordConnector] {message}")

    # ------------------------------------------------------------------
    # Persistence (delete + write pattern for JSON)
    # ------------------------------------------------------------------

    async def _load_prefs(self) -> dict:
        """Load user preferences or return defaults."""
        if await self.capability_worker.check_if_file_exists(
            PREFS_FILE, False
        ):
            try:
                raw = await self.capability_worker.read_file(
                    PREFS_FILE, False
                )
                return json.loads(raw)
            except (json.JSONDecodeError, Exception):
                self._log("error", "Corrupt prefs file, using defaults.")
        return {}

    async def _save_prefs(self, prefs: dict):
        """Save user preferences persistently (delete + write)."""
        if await self.capability_worker.check_if_file_exists(
            PREFS_FILE, False
        ):
            await self.capability_worker.delete_file(PREFS_FILE, False)
        await self.capability_worker.write_file(
            PREFS_FILE, json.dumps(prefs), False
        )
