import json
import time

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


STATE_FILE = "youtube_live_companion_state.json"

# YouTube OAuth setup is handled outside this public Ability package.
# Keep committed values as placeholders. OpenHome operators can replace these
# constants in their private runtime copy when manual OAuth credentials are used.
# Do not commit real client secrets or refresh tokens.
YOUTUBE_CLIENT_ID = "YOUR_YOUTUBE_CLIENT_ID"
YOUTUBE_CLIENT_SECRET = "YOUR_YOUTUBE_CLIENT_SECRET"
YOUTUBE_REFRESH_TOKEN = "YOUR_YOUTUBE_REFRESH_TOKEN"
ASSISTANT_LANGUAGE = "en"

CREDENTIAL_NAMES = (
    "YOUTUBE_CLIENT_ID",
    "YOUTUBE_CLIENT_SECRET",
    "YOUTUBE_REFRESH_TOKEN",
)

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

MAIN_SPEECH_MESSAGES = {
    "ja": {
        "setup_error": "YouTube 配信アシスタントの設定中にエラーが発生しました。",
        "missing_credentials": (
            "YouTube の認証情報がまだ足りません。不足しているキーは {missing_keys} です。"
            "OpenHome 側の OAuth 設定または Ability runtime の認証情報を確認してください。"
        ),
        "status_not_recorded": (
            "まだ YouTube 配信アシスタントの状態は記録されていません。"
            "設定後、少し待ってからもう一度確認してください。"
        ),
        "status_with_error": (
            "現在の状態は {status} です。設定元は {config_source}、"
            "認証情報は {credential_source} です。最後のエラーは {last_error} です。"
        ),
        "status_base": (
            "現在の状態は {status} です。設定元は {config_source}、"
            "認証情報は {credential_source} です。対象ライブは {live_title}、"
            "ライブチャット ID は {live_chat_id} です。"
        ),
        "status_buffered_messages": " 要約待ちの新着コメントは {buffered_messages} 件です。",
        "status_last_message": " 最後の新着コメントは約 {seconds_ago} 秒前です。",
        "summary_state_not_recorded": (
            "まだライブチャットの状態が記録されていません。少し待ってからもう一度試してください。"
        ),
        "summary_error": "ライブチャットの取得でエラーが出ています。最後のエラーは {last_error} です。",
        "summary_not_connected": "まだライブチャットに接続できていません。配信が開始されているか確認してください。",
        "summary_no_messages": (
            "まだ要約できる新着コメントがありません。ライブチャットに新しいコメントが来てからもう一度試してください。"
        ),
        "summary_failed": "コメント要約を作れませんでした。少し待ってからもう一度試してください。",
        "reset_removed": "YouTube 配信アシスタントの状態を削除しました。",
        "reset_nothing": "削除する永続状態はありませんでした。OAuth 設定は OpenHome 側の管理設定を確認してください。",
        "state_read_failed": "状態ファイルを読み取れませんでした。Background Daemon のログを確認してください。",
        "unknown_value": "未取得",
        "missing_value": "未設定",
    },
    "en": {
        "setup_error": "An error occurred while setting up the YouTube Live assistant.",
        "missing_credentials": (
            "YouTube credentials are still missing. Missing keys: {missing_keys}. "
            "Check the OpenHome OAuth setup or the Ability runtime credentials."
        ),
        "status_not_recorded": (
            "The YouTube Live assistant has not recorded any state yet. "
            "After setup, wait a moment and check again."
        ),
        "status_with_error": (
            "The current status is {status}. The config source is {config_source}, "
            "and the credential source is {credential_source}. The last error is {last_error}."
        ),
        "status_base": (
            "The current status is {status}. The config source is {config_source}, "
            "and the credential source is {credential_source}. The target live stream is "
            "{live_title}, and the live chat ID is {live_chat_id}."
        ),
        "status_buffered_messages": " There are {buffered_messages} new comments waiting for summary.",
        "status_last_message": " The last new comment arrived about {seconds_ago} seconds ago.",
        "summary_state_not_recorded": (
            "The live chat state has not been recorded yet. Wait a moment and try again."
        ),
        "summary_error": "Live chat retrieval has an error. The last error is {last_error}.",
        "summary_not_connected": "The assistant is not connected to live chat yet. Check whether the stream has started.",
        "summary_no_messages": (
            "There are no new comments to summarize yet. Try again after new live chat messages arrive."
        ),
        "summary_failed": "I could not create a comment summary. Wait a moment and try again.",
        "reset_removed": "The YouTube Live assistant state has been deleted.",
        "reset_nothing": "There was no saved state to delete. Check the OpenHome-managed OAuth setup for credential changes.",
        "state_read_failed": "The state file could not be read. Check the Background Daemon logs.",
        "unknown_value": "not available",
        "missing_value": "not set",
    },
}


def get_assistant_language():
    language = str(ASSISTANT_LANGUAGE or "ja").strip().lower()
    return LANGUAGE_ALIASES.get(language, "ja")


def get_summary_system_prompt():
    return SUMMARY_SYSTEM_PROMPTS[get_assistant_language()]


def get_speech_message(message_key):
    messages = MAIN_SPEECH_MESSAGES[get_assistant_language()]
    return messages.get(message_key, MAIN_SPEECH_MESSAGES["ja"][message_key])


def format_speech_message(message_key, **values):
    return get_speech_message(message_key).format(**values)

SETUP_WORDS = {
    "youtube live setup",
    "youtube setup",
    "配信設定",
    "youtube設定",
    "設定",
}

STATUS_WORDS = {
    "youtube live status",
    "youtube status",
    "you tube live status",
    "you two live status",
    "u two live status",
    "配信ステータス",
    "ライブステータス",
    "状態確認",
    "status",
}

SUMMARY_WORDS = {
    "youtube live summary",
    "youtube summary",
    "you tube live summary",
    "you two live summary",
    "u two live summary",
    "comment summary",
    "chat summary",
    "コメント要約",
    "コメントまとめ",
    "チャット要約",
    "チャットまとめ",
}

RESET_WORDS = {
    "youtube live reset",
    "配信設定リセット",
    "設定リセット",
    "reset",
}

SUMMARY_PATTERNS = (
    "youtube live summary",
    "youtube summary",
    "comment summary",
    "chat summary",
    "コメント要約",
    "コメントまとめ",
    "チャット要約",
    "チャットまとめ",
    "要約",
    "まとめ",
)

STATUS_PATTERNS = (
    "youtube live status",
    "youtube status",
    "配信ステータス",
    "ライブステータス",
    "ライブの状態",
    "状態",
    "ステータス",
    "接続",
)

SETUP_PATTERNS = (
    "youtube live setup",
    "youtube setup",
    "youtube設定",
    "配信設定",
    "設定確認",
)

RESET_PATTERNS = (
    "youtube live reset",
    "youtube reset",
    "配信設定リセット",
    "設定リセット",
    "リセット",
)


class YoutubeLiveCompanionCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register capability}}

    async def run(self):
        try:
            request_text = await self.capability_worker.wait_for_complete_transcription()
            request_text = self._normalize(request_text)
            intent = self._intent_for_text(request_text)

            if intent == "summary":
                await self._speak_comment_summary()
            elif intent == "status":
                await self._speak_status()
            elif intent == "reset":
                await self._reset_config()
            else:
                await self._save_config_from_user()
        except Exception as error:
            self.worker.editor_logging_handler.error(
                f"YoutubeLiveCompanionCapability failed: {error}"
            )
            await self.capability_worker.speak(self._speech("setup_error"))
        finally:
            self.capability_worker.resume_normal_flow()

    async def _save_config_from_user(self):
        missing_keys, credential_source = await self._missing_credentials()
        if not missing_keys:
            self.worker.editor_logging_handler.info(
                "YouTube credentials are available from "
                f"{credential_source}. The background daemon will keep tracking live chat."
            )
            return

        await self.capability_worker.speak(
            self._speech("missing_credentials", missing_keys=", ".join(missing_keys))
        )

    async def _speak_status(self):
        if not await self.capability_worker.check_if_file_exists(STATE_FILE, False):
            await self.capability_worker.speak(self._speech("status_not_recorded"))
            return

        state = await self._read_state()
        if not state:
            return

        status = state.get("status") or "unknown"
        unknown_value = self._speech("unknown_value")
        config_source = state.get("config_source") or unknown_value
        credential_source = state.get("credential_source") or unknown_value
        live_title = state.get("live_title") or unknown_value
        live_chat_id = state.get("live_chat_id") or unknown_value
        buffered_messages = state.get("buffered_messages")
        last_message_at = state.get("last_message_at_epoch")
        last_error = state.get("last_error")

        if last_error:
            await self.capability_worker.speak(
                self._speech(
                    "status_with_error",
                    status=status,
                    config_source=config_source,
                    credential_source=credential_source,
                    last_error=last_error,
                )
            )
            return

        message = self._speech(
            "status_base",
            status=status,
            config_source=config_source,
            credential_source=credential_source,
            live_title=live_title,
            live_chat_id=live_chat_id,
        )
        if buffered_messages is not None:
            message += self._speech(
                "status_buffered_messages",
                buffered_messages=buffered_messages,
            )
        if last_message_at:
            seconds_ago = max(0, round(time.time() - float(last_message_at)))
            message += self._speech(
                "status_last_message",
                seconds_ago=seconds_ago,
            )

        await self.capability_worker.speak(message)

    async def _speak_comment_summary(self):
        if not await self.capability_worker.check_if_file_exists(STATE_FILE, False):
            await self.capability_worker.speak(self._speech("summary_state_not_recorded"))
            return

        state = await self._read_state()
        if not state:
            return

        last_error = state.get("last_error")
        if last_error:
            await self.capability_worker.speak(
                self._speech("summary_error", last_error=last_error)
            )
            return

        if state.get("status") != "connected":
            await self.capability_worker.speak(self._speech("summary_not_connected"))
            return

        messages = state.get("recent_messages") or []
        if not messages:
            await self.capability_worker.speak(self._speech("summary_no_messages"))
            return

        prompt_lines = [
            f"- {message.get('author') or 'viewer'}: {message.get('text') or ''}"
            for message in messages
            if (message.get("text") or "").strip()
        ]
        prompt = (
            f"Live title: {state.get('live_title') or 'YouTube Live'}\n"
            f"Live description:\n{self._truncate_text(state.get('live_description') or '', 1200)}\n\n"
            "Recent YouTube live chat messages:\n"
            + "\n".join(prompt_lines)
        )
        response = self.capability_worker.text_to_text_response(
            prompt,
            [],
            system_prompt=get_summary_system_prompt(),
        )
        response = self._clean_response(response)
        if response:
            await self.capability_worker.speak(response)
            return

        await self.capability_worker.speak(self._speech("summary_failed"))

    async def _reset_config(self):
        removed = False
        for filename in (STATE_FILE,):
            if await self.capability_worker.check_if_file_exists(filename, False):
                await self.capability_worker.delete_file(filename, False)
                removed = True

        if removed:
            await self.capability_worker.speak(self._speech("reset_removed"))
        else:
            await self.capability_worker.speak(self._speech("reset_nothing"))

    def _normalize(self, text):
        if not text:
            return ""
        return " ".join(text.strip().split())

    async def _read_state(self):
        state_text = await self.capability_worker.read_file(STATE_FILE, False)
        try:
            return json.loads(state_text)
        except (TypeError, ValueError):
            await self.capability_worker.speak(self._speech("state_read_failed"))
            return None

    async def _missing_credentials(self):
        credential_values, credential_source = self._read_manual_credentials()
        if all(credential_values.get(config_name) for config_name in CREDENTIAL_NAMES):
            return [], credential_source or "main.py"

        missing = []
        for config_name in CREDENTIAL_NAMES:
            if credential_values.get(config_name):
                continue
            missing.append(config_name)

        if missing:
            return missing, self._speech("missing_value")

        return [], credential_source or "main.py"

    def _read_manual_credentials(self):
        values = {}
        sources = []
        for config_name in CREDENTIAL_NAMES:
            value = self._read_credential(config_name)
            if value:
                values[config_name] = value
                sources.append(self._credential_source_label(config_name))
        return values, ", ".join(dict.fromkeys(sources))

    def _read_credential(self, config_name):
        if config_name == "YOUTUBE_CLIENT_ID":
            return self._clean_credential_value(YOUTUBE_CLIENT_ID)
        if config_name == "YOUTUBE_CLIENT_SECRET":
            return self._clean_credential_value(YOUTUBE_CLIENT_SECRET)
        if config_name == "YOUTUBE_REFRESH_TOKEN":
            return self._clean_credential_value(YOUTUBE_REFRESH_TOKEN)
        return ""

    def _credential_source_label(self, config_name):
        return "main.py"

    def _clean_credential_value(self, value):
        value = str(value or "").strip()
        if value in PLACEHOLDER_VALUES:
            return ""
        return value

    def _matches(self, text, words):
        lowered = text.lower().strip(" 　。、,.!?！？")
        return lowered in {word.lower() for word in words}

    def _intent_for_text(self, text):
        lowered = self._match_text(text)
        if self._matches(text, RESET_WORDS) or self._contains_any(
            lowered, RESET_PATTERNS
        ):
            return "reset"
        if self._matches(text, SUMMARY_WORDS) or self._contains_any(
            lowered, SUMMARY_PATTERNS
        ):
            return "summary"
        if self._matches(text, STATUS_WORDS) or self._contains_any(
            lowered, STATUS_PATTERNS
        ):
            return "status"
        if self._matches(text, SETUP_WORDS) or self._contains_any(
            lowered, SETUP_PATTERNS
        ):
            return "setup"
        return "setup"

    def _match_text(self, text):
        return self._normalize(text).lower().strip(" 　。、,.!?！？")

    def _contains_any(self, text, patterns):
        return any(pattern.lower() in text for pattern in patterns)

    def _truncate_text(self, text, max_length):
        text = " ".join((text or "").split())
        if len(text) <= max_length:
            return text
        return text[: max_length - 1].rstrip() + "…"

    def _clean_response(self, response):
        if not response:
            return ""
        return response.strip().strip("`").strip()

    def _speech(self, message_key, **values):
        return format_speech_message(message_key, **values)

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run())
