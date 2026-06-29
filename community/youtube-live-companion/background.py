import asyncio
import json
import time

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


STATE_FILE = "youtube_live_companion_state.json"
LIVE_CHAT_UNAVAILABLE_STATUS_CODES = {400, 403, 404, 410}
AUTHENTICATION_STATUS_CODES = {401}

# YouTube OAuth setup is handled outside this public Ability package.
# Keep committed values as placeholders. OpenHome operators can replace these
# constants in their private runtime copy when manual OAuth credentials are used.
# Do not commit real client secrets or refresh tokens.
YOUTUBE_CLIENT_ID = "YOUR_YOUTUBE_CLIENT_ID"
YOUTUBE_CLIENT_SECRET = "YOUR_YOUTUBE_CLIENT_SECRET"
YOUTUBE_REFRESH_TOKEN = "YOUR_YOUTUBE_REFRESH_TOKEN"
ASSISTANT_LANGUAGE = "en"

CREDENTIAL_NAMES = {
    "client_id": "YOUTUBE_CLIENT_ID",
    "client_secret": "YOUTUBE_CLIENT_SECRET",
    "refresh_token": "YOUTUBE_REFRESH_TOKEN",
}

POLL_INTERVAL_SECONDS = 15
SUMMARY_INTERVAL_SECONDS = 60
QUIET_AFTER_SECONDS = 120
QUIET_COOLDOWN_SECONDS = 180
MIN_MESSAGES_TO_SUMMARIZE = 3
MAX_MESSAGES_PER_SUMMARY = 12
IGNORE_EXISTING_MESSAGES_ON_START = True
SPEAK_CONNECTION_STATUS = True
SPEAK_SUMMARIES = True
SPEAK_QUIET_PROMPTS = True

GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
LIVE_BROADCASTS_URL = "https://www.googleapis.com/youtube/v3/liveBroadcasts"
LIVE_CHAT_MESSAGES_URL = "https://www.googleapis.com/youtube/v3/liveChat/messages"

PLACEHOLDER_VALUES = {
    "",
    "YOUR_YOUTUBE_CLIENT_ID",
    "your_youtube_client_id_here",
    "YOUR_YOUTUBE_CLIENT_SECRET",
    "your_youtube_client_secret_here",
    "YOUR_YOUTUBE_REFRESH_TOKEN",
    "your_youtube_refresh_token_here",
}

LANGUAGE_ALIASES = {
    "ja": "ja",
    "jp": "ja",
    "japanese": "ja",
    "日本語": "ja",
    "en": "en",
    "english": "en",
    "英語": "en",
}

SUMMARY_SYSTEM_PROMPTS = {
    "ja": """You are a Japanese live-stream cohost assistant.

Speak to the streamer as an assistant, not as the streamer.
Summarize recent live chat so the streamer can quickly understand what is happening.
Use the live title and description as context, and prefer suggestions that fit the stream topic.
Do not read every comment. Capture the main trend, questions, mood, and useful cue.
Use phrases like "コメントでは", "今は", "この話題に触れるとよさそうです".
Do not say lines that pretend to be the streamer, such as "僕は", "私は", "みんな", or direct audience greetings.
Return only Japanese speech text. No markdown, no labels.
Keep it natural and concise: 2 or 3 short sentences.
Do not invent viewer counts, usernames, facts, sponsors, or promises.
""",
    "en": """You are an English live-stream cohost assistant.

Speak to the streamer as an assistant, not as the streamer.
Summarize recent live chat so the streamer can quickly understand what is happening.
Use the live title and description as context, and prefer suggestions that fit the stream topic.
Do not read every comment. Capture the main trend, questions, mood, and useful cue.
Use phrases like "In the chat", "Right now", or "It may be good to mention".
Do not say lines that pretend to be the streamer, such as "I", "we", "everyone", or direct audience greetings.
Return only English speech text. No markdown, no labels.
Keep it natural and concise: 2 or 3 short sentences.
Do not invent viewer counts, usernames, facts, sponsors, or promises.
""",
}

QUIET_SYSTEM_PROMPTS = {
    "ja": """You are a Japanese live-stream cohost assistant.

Speak to the streamer as an assistant, not as the streamer.
The live chat has been quiet. Suggest a warm, low-pressure topic the streamer could bring up.
Use the live title and description as context, and avoid generic topics that ignore the stream topic.
Use assistant-style guidance like "少し静かなので", "この話題を振ると反応しやすそうです".
Do not produce a first-person line for the streamer to say directly.
Return only Japanese speech text. No markdown, no labels.
Keep it to 1 or 2 short sentences.
Do not invent viewer counts, usernames, facts, sponsors, or promises.
""",
    "en": """You are an English live-stream cohost assistant.

Speak to the streamer as an assistant, not as the streamer.
The live chat has been quiet. Suggest a warm, low-pressure topic the streamer could bring up.
Use the live title and description as context, and avoid generic topics that ignore the stream topic.
Use assistant-style guidance like "The chat is a little quiet" or "This topic may invite responses".
Do not produce a first-person line for the streamer to say directly.
Return only English speech text. No markdown, no labels.
Keep it to 1 or 2 short sentences.
Do not invent viewer counts, usernames, facts, sponsors, or promises.
""",
}

BACKGROUND_SPEECH_MESSAGES = {
    "ja": {
        "missing_credentials_state_error": (
            "YouTube OAuth 認証情報がまだ runtime に設定されていません。"
            "OpenHome 側の OAuth 設定または Ability runtime の認証情報を確認してください。"
        ),
        "oauth_refresh_error": (
            "Google OAuth token refresh failed. Confirm the OpenHome-managed OAuth "
            "setup or refresh the manual runtime credentials. Original error: {error}"
        ),
    },
    "en": {
        "missing_credentials_state_error": (
            "YouTube OAuth credentials are not configured in the runtime yet. "
            "Check the OpenHome OAuth setup or the Ability runtime credentials."
        ),
        "oauth_refresh_error": (
            "Google OAuth token refresh failed. Confirm the OpenHome-managed OAuth "
            "setup or refresh the manual runtime credentials. Original error: {error}"
        ),
    },
}

DEFAULT_CONFIG = {
    "poll_interval_seconds": POLL_INTERVAL_SECONDS,
    "summary_interval_seconds": SUMMARY_INTERVAL_SECONDS,
    "quiet_after_seconds": QUIET_AFTER_SECONDS,
    "quiet_cooldown_seconds": QUIET_COOLDOWN_SECONDS,
    "min_messages_to_summarize": MIN_MESSAGES_TO_SUMMARIZE,
    "max_messages_per_summary": MAX_MESSAGES_PER_SUMMARY,
    "ignore_existing_messages_on_start": IGNORE_EXISTING_MESSAGES_ON_START,
    "speak_connection_status": SPEAK_CONNECTION_STATUS,
    "speak_summaries": SPEAK_SUMMARIES,
    "speak_quiet_prompts": SPEAK_QUIET_PROMPTS,
}


def get_assistant_language():
    language = str(ASSISTANT_LANGUAGE or "ja").strip().lower()
    return LANGUAGE_ALIASES.get(language, "ja")


def get_summary_system_prompt():
    return SUMMARY_SYSTEM_PROMPTS[get_assistant_language()]


def get_quiet_system_prompt():
    return QUIET_SYSTEM_PROMPTS[get_assistant_language()]


def get_background_speech_message(message_key):
    messages = BACKGROUND_SPEECH_MESSAGES[get_assistant_language()]
    return messages.get(message_key, BACKGROUND_SPEECH_MESSAGES["ja"][message_key])


def format_background_speech_message(message_key, **values):
    return get_background_speech_message(message_key).format(**values)


class YoutubeLiveCompanionBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    _access_token = None
    _access_token_expires_at = 0
    _live_chat_id = ""
    _live_title = ""
    _live_description = ""
    _next_page_token = ""
    _chat_initialized = False
    _last_message_at = 0
    _last_spoken_at = 0
    _last_quiet_prompt_at = 0
    _next_sleep_seconds = 15
    _message_buffer = None
    _recent_messages = None
    _seen_message_ids = None
    _announced_connection = False

    #{{register capability}}

    async def watch_live_chat(self):
        self._message_buffer = []
        self._recent_messages = []
        self._seen_message_ids = []
        self.worker.editor_logging_handler.info("YouTube live companion watcher started")

        while True:
            try:
                config = await self._load_config()
                if not config:
                    await self.worker.session_tasks.sleep(30.0)
                    continue

                await self._tick(config)
                await self.worker.session_tasks.sleep(float(self._next_sleep_seconds))
            except Exception as error:
                self.worker.editor_logging_handler.error(
                    f"YouTube live companion watcher failed: {error}"
                )
                await self._write_state(self._error_state(error))
                await self.worker.session_tasks.sleep(30.0)

    async def _tick(self, config):
        self._next_sleep_seconds = float(config["poll_interval_seconds"])

        if not self._live_chat_id:
            live = await self._resolve_live_chat_from_owned_broadcast(config)
            if not live:
                await self._write_state(self._waiting_state(config))
                return

            self._remember_live_chat(live)

            await self._write_state(self._connected_state(config))

            if config["speak_connection_status"] and not self._announced_connection:
                await self._speak(
                    f"YouTube ライブチャットに接続しました。対象は {self._live_title} です。"
                )
                self._announced_connection = True

        try:
            messages_response = await self._list_live_chat_messages(
                config, self._live_chat_id
            )
        except YouTubeApiError as error:
            if self._is_live_chat_unavailable(error):
                self.worker.editor_logging_handler.info(
                    "YouTube live chat became unavailable; resetting chat state"
                )
                self._reset_live_chat_state()
                await self._write_state(
                    self._waiting_state(
                        config,
                        last_error=str(error),
                        error_type="live_chat_unavailable",
                    )
                )
                return
            raise

        self._next_page_token = (
            messages_response.get("nextPageToken") or self._next_page_token
        )

        polling_interval = messages_response.get("pollingIntervalMillis")
        if polling_interval:
            self._next_sleep_seconds = max(
                float(config["poll_interval_seconds"]),
                float(polling_interval) / 1000.0,
            )

        new_messages = self._extract_new_messages(messages_response)
        if not self._chat_initialized:
            self._chat_initialized = True
            if config["ignore_existing_messages_on_start"]:
                return

        if new_messages:
            self._last_message_at = time.time()
            self._message_buffer.extend(new_messages)
            self._recent_messages.extend(new_messages)
            self._recent_messages = self._recent_messages[-20:]

        await self._maybe_summarize(config)
        await self._maybe_prompt_when_quiet(config)

        await self._write_state(self._connected_state(config))

    async def _maybe_summarize(self, config):
        now = time.time()
        if not config["speak_summaries"]:
            return
        if len(self._message_buffer) < int(config["min_messages_to_summarize"]):
            return
        if now - self._last_spoken_at < float(config["summary_interval_seconds"]):
            return

        messages = self._message_buffer[-int(config["max_messages_per_summary"]) :]
        prompt_lines = [
            f"- {message['author']}: {message['text']}" for message in messages
        ]
        prompt = (
            self._live_context_prompt()
            + "\n\nRecent YouTube live chat messages:\n"
            + "\n".join(prompt_lines)
        )
        response = self.capability_worker.text_to_text_response(
            prompt,
            [],
            system_prompt=get_summary_system_prompt(),
        )
        response = self._clean_response(response)
        if response:
            await self._speak(response)
            self._last_spoken_at = now
            self._message_buffer = []

    async def _maybe_prompt_when_quiet(self, config):
        now = time.time()
        if not config["speak_quiet_prompts"]:
            return
        if self._message_buffer:
            return
        if now - self._last_message_at < float(config["quiet_after_seconds"]):
            return
        if now - self._last_quiet_prompt_at < float(config["quiet_cooldown_seconds"]):
            return

        prompt = (
            self._live_context_prompt()
            + "\n"
            f"No new chat messages for about {round(now - self._last_message_at)} seconds."
        )
        response = self.capability_worker.text_to_text_response(
            prompt,
            [],
            system_prompt=get_quiet_system_prompt(),
        )
        response = self._clean_response(response)
        if response:
            await self._speak(response)
            self._last_spoken_at = now
            self._last_quiet_prompt_at = now

    async def _speak(self, text):
        await self.capability_worker.send_interrupt_signal()
        await self.capability_worker.speak(text)

    async def _load_config(self):
        merged = dict(DEFAULT_CONFIG)
        merged.update(self._read_config_py_settings())
        credential_source = self._apply_manual_credentials(merged)
        merged["config_source"] = "background.py"
        merged["credential_source"] = self._credential_source(merged, credential_source)

        if not self._has_oauth(merged):
            await self._write_state(
                {
                    "status": "missing_config_values",
                    "config_source": "background.py",
                    "credential_source": "missing",
                    "last_error": format_background_speech_message(
                        "missing_credentials_state_error"
                    ),
                    "updated_at_epoch": round(time.time()),
                }
            )
            return None

        return merged

    def _read_config_py_settings(self):
        return {
            "poll_interval_seconds": POLL_INTERVAL_SECONDS,
            "summary_interval_seconds": SUMMARY_INTERVAL_SECONDS,
            "quiet_after_seconds": QUIET_AFTER_SECONDS,
            "quiet_cooldown_seconds": QUIET_COOLDOWN_SECONDS,
            "min_messages_to_summarize": MIN_MESSAGES_TO_SUMMARIZE,
            "max_messages_per_summary": MAX_MESSAGES_PER_SUMMARY,
            "ignore_existing_messages_on_start": (
                IGNORE_EXISTING_MESSAGES_ON_START
            ),
            "speak_connection_status": SPEAK_CONNECTION_STATUS,
            "speak_summaries": SPEAK_SUMMARIES,
            "speak_quiet_prompts": SPEAK_QUIET_PROMPTS,
        }

    def _apply_manual_credentials(self, config):
        applied = []
        for config_key, variable_name in CREDENTIAL_NAMES.items():
            if config.get(config_key):
                continue
            value, source = self._read_credential(variable_name)
            if value:
                config[config_key] = value
                applied.append(source)
        return ", ".join(dict.fromkeys(applied))

    def _read_credential(self, variable_name):
        value = ""
        if variable_name == "YOUTUBE_CLIENT_ID":
            value = YOUTUBE_CLIENT_ID
        elif variable_name == "YOUTUBE_CLIENT_SECRET":
            value = YOUTUBE_CLIENT_SECRET
        elif variable_name == "YOUTUBE_REFRESH_TOKEN":
            value = YOUTUBE_REFRESH_TOKEN

        value = self._clean_credential_value(value)
        if value:
            return value, "background.py"
        return "", ""

    def _credential_source(self, config, credential_source):
        if credential_source and self._has_oauth(config):
            return credential_source
        return "background.py"

    def _clean_credential_value(self, value):
        value = str(value or "").strip()
        if value in PLACEHOLDER_VALUES:
            return ""
        return value

    async def _write_state(self, state):
        content = json.dumps(state, ensure_ascii=False, indent=2)
        try:
            await self.capability_worker.write_file(STATE_FILE, content, False, "w")
            return
        except TypeError:
            pass

        if await self.capability_worker.check_if_file_exists(STATE_FILE, False):
            await self.capability_worker.delete_file(STATE_FILE, False)
        await self.capability_worker.write_file(
            STATE_FILE,
            content,
            False,
        )

    async def _resolve_live_chat_from_owned_broadcast(self, config):
        data = await self._youtube_get(
            LIVE_BROADCASTS_URL,
            {
                "part": "id,snippet,status",
                "broadcastType": "all",
                "maxResults": "50",
                "mine": "true",
            },
            config,
        )
        return self._live_chat_from_broadcasts(data.get("items", []))

    def _live_chat_from_broadcasts(self, items):
        for item in items:
            snippet = item.get("snippet") or {}
            status = item.get("status") or {}
            if status.get("lifeCycleStatus") != "live":
                continue

            live_chat_id = snippet.get("liveChatId")
            if live_chat_id:
                return {
                    "live_chat_id": live_chat_id,
                    "live_title": snippet.get("title") or "YouTube Live",
                    "live_description": snippet.get("description") or "",
                }
        return None

    async def _list_live_chat_messages(self, config, live_chat_id):
        params = {
            "liveChatId": live_chat_id,
            "part": "snippet,authorDetails",
            "maxResults": "200",
        }
        if self._next_page_token:
            params["pageToken"] = self._next_page_token

        return await self._youtube_get(
            LIVE_CHAT_MESSAGES_URL,
            params,
            config,
        )

    def _extract_new_messages(self, messages_response):
        new_messages = []
        for item in messages_response.get("items", []):
            message_id = item.get("id")
            if message_id and message_id in self._seen_message_ids:
                continue

            if message_id:
                self._seen_message_ids.append(message_id)
                self._seen_message_ids = self._seen_message_ids[-500:]

            snippet = item.get("snippet") or {}
            author_details = item.get("authorDetails") or {}
            text = snippet.get("displayMessage") or ""
            if not text.strip():
                continue

            new_messages.append(
                {
                    "author": author_details.get("displayName") or "viewer",
                    "text": text.strip(),
                }
            )

        return new_messages

    async def _youtube_get(self, url, params, config):
        request_params = dict(params)
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {await self._get_access_token(config)}",
        }

        return await self._http_json(url, headers=headers, params=request_params)

    async def _get_access_token(self, config):
        now = time.time()
        if self._access_token and now < self._access_token_expires_at - 60:
            return self._access_token

        try:
            payload = await self._http_json(
                GOOGLE_OAUTH_TOKEN_URL,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                method="POST",
                data={
                    "client_id": config["client_id"],
                    "client_secret": config["client_secret"],
                    "refresh_token": config["refresh_token"],
                    "grant_type": "refresh_token",
                },
            )
        except YouTubeApiError as error:
            raise OAuthRefreshError(
                format_background_speech_message(
                    "oauth_refresh_error",
                    error=error,
                )
            ) from error

        self._access_token = (
            payload.get("access_token") if isinstance(payload, dict) else ""
        )
        if not self._access_token:
            raise OAuthRefreshError(
                "Google OAuth token refresh returned no access token"
            )
        self._access_token_expires_at = now + int(payload.get("expires_in", 3600))
        return self._access_token

    async def _http_json(
        self, url, headers=None, method="GET", data=None, params=None
    ):
        return await asyncio.to_thread(
            self._http_json_sync,
            url,
            headers=headers,
            method=method,
            data=data,
            params=params,
        )

    def _http_json_sync(
        self, url, headers=None, method="GET", data=None, params=None
    ):
        try:
            response = requests.request(
                method,
                url,
                headers=headers or {"Accept": "application/json"},
                data=data,
                params=params,
                timeout=12,
            )
        except requests.exceptions.Timeout as error:
            raise YouTubeApiError(
                None,
                f"YouTube API request timed out: {error}",
                error_type="transient_api_error",
            ) from error
        except requests.exceptions.RequestException as error:
            raise YouTubeApiError(
                None,
                f"YouTube API request failed: {error}",
                error_type="transient_api_error",
            ) from error

        if response.status_code >= 400:
            raise YouTubeApiError(response.status_code, response.text)
        try:
            return response.json()
        except ValueError as error:
            raise YouTubeApiError(
                response.status_code,
                f"YouTube API returned invalid JSON: {error}",
                error_type="invalid_json",
            ) from error

    def _has_oauth(self, config):
        return bool(
            config.get("client_id")
            and config.get("client_secret")
            and config.get("refresh_token")
        )

    def _remember_live_chat(self, live):
        self._live_chat_id = live["live_chat_id"]
        self._live_title = live.get("live_title") or "YouTube Live"
        self._live_description = live.get("live_description") or ""
        self._recent_messages = []
        self._message_buffer = []
        self._seen_message_ids = []
        self._chat_initialized = False
        self._next_page_token = ""
        self._last_message_at = time.time()

    def _reset_live_chat_state(self):
        self._live_chat_id = ""
        self._live_title = ""
        self._live_description = ""
        self._next_page_token = ""
        self._chat_initialized = False
        self._last_message_at = 0
        self._message_buffer = []
        self._recent_messages = []
        self._seen_message_ids = []
        self._announced_connection = False

    def _is_live_chat_unavailable(self, error):
        return error.status_code in LIVE_CHAT_UNAVAILABLE_STATUS_CODES

    def _waiting_state(self, config, last_error=None, error_type=None):
        return {
            "status": "waiting_for_active_live",
            "config_source": config.get("config_source"),
            "credential_source": config.get("credential_source"),
            "live_chat_id": "",
            "live_title": "",
            "live_description": "",
            "recent_messages": [],
            "recent_messages_count": 0,
            "last_error": last_error,
            "error_type": error_type,
            "updated_at_epoch": round(time.time()),
        }

    def _connected_state(self, config):
        return {
            "status": "connected",
            "config_source": config.get("config_source"),
            "credential_source": config.get("credential_source"),
            "live_chat_id": self._live_chat_id,
            "live_title": self._live_title,
            "live_description": self._truncate_text(self._live_description, 500),
            "buffered_messages": len(self._message_buffer or []),
            "recent_messages": self._messages_for_state(config),
            "recent_messages_count": len(self._recent_messages or []),
            "last_message_at_epoch": round(self._last_message_at),
            "next_sleep_seconds": self._next_sleep_seconds,
            "last_error": None,
            "error_type": None,
            "updated_at_epoch": round(time.time()),
        }

    def _error_state(self, error):
        status = "error"
        error_type = "unexpected_error"
        if isinstance(error, OAuthRefreshError):
            status = "authentication_error"
            error_type = "oauth_refresh_error"
        elif isinstance(error, YouTubeApiError):
            error_type = error.error_type
            if error.status_code in AUTHENTICATION_STATUS_CODES:
                status = "authentication_error"
                error_type = "youtube_authentication_error"
            else:
                status = "api_error"

        return {
            "status": status,
            "live_chat_id": self._live_chat_id,
            "live_title": self._live_title,
            "last_error": str(error),
            "error_type": error_type,
            "updated_at_epoch": round(time.time()),
        }

    def _live_context_prompt(self):
        description = self._truncate_text(self._live_description, 1200)
        if not description:
            description = "No live description is available."
        return f"Live title: {self._live_title}\nLive description:\n{description}"

    def _truncate_text(self, text, max_length):
        text = " ".join((text or "").split())
        if len(text) <= max_length:
            return text
        return text[: max_length - 1].rstrip() + "…"

    def _messages_for_state(self, config):
        limit = int(config.get("max_messages_per_summary", 12))
        messages = self._recent_messages[-limit:]
        return [
            {
                "author": self._truncate_text(message.get("author") or "viewer", 80),
                "text": self._truncate_text(message.get("text") or "", 300),
            }
            for message in messages
            if (message.get("text") or "").strip()
        ]

    def _clean_response(self, response):
        if not response:
            return ""
        return response.strip().strip("`").strip()

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.background_daemon_mode = background_daemon_mode
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.watch_live_chat())


class YouTubeApiError(RuntimeError):
    def __init__(self, status_code, message, error_type="api_error"):
        self.status_code = status_code
        self.error_type = error_type
        if status_code is None:
            super().__init__(message)
        else:
            super().__init__(f"YouTube API HTTP {status_code}: {message}")


class OAuthRefreshError(RuntimeError):
    pass
