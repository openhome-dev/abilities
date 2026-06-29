# YouTube OAuth is not currently integrated with OpenHome Linked Accounts.
# This Ability version uses manual credentials as a temporary workaround.
#
# OpenHome Cloud / Ability Editor reads these values directly from config.py.
# Keep committed values as placeholders. Replace them only in your private
# OpenHome Ability Editor copy.
#
# Local development note:
# Do not read environment variables in this file. Local tests may load .env
# and patch these module values from the test harness, but the uploaded Ability
# should use config.py as the source of truth.
#
# Required for private or unlisted YouTube Live streams.
YOUTUBE_CLIENT_ID = "YOUR_YOUTUBE_CLIENT_ID"
YOUTUBE_CLIENT_SECRET = "YOUR_YOUTUBE_CLIENT_SECRET"
YOUTUBE_REFRESH_TOKEN = "YOUR_YOUTUBE_REFRESH_TOKEN"

# Output language for generated comment summaries and quiet prompts.
# Supported values: "ja", "日本語", "en", or "english".
ASSISTANT_LANGUAGE = "ja"

# Polling and assistant behavior.
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


# Prompts are editable so you can tune the assistant's tone without changing
# main.py or background.py. Add another language here if you need one later.
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

# -- Do not edit below this line. --

# Values in this set are examples, not usable credentials. main.py and
# background.py treat them as empty so placeholders are never sent to YouTube.
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



MAIN_SPEECH_MESSAGES = {
    "ja": {
        "setup_error": "YouTube 配信アシスタントの設定中にエラーが発生しました。",
        "missing_credentials": (
            "YouTube の認証情報がまだ足りません。不足しているキーは {missing_keys} です。"
            "Ability の config.py に YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, "
            "YOUTUBE_REFRESH_TOKEN を設定して、Agent を再起動してください。"
        ),
        "missing_credentials_state_error": (
            "config.py に YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, "
            "YOUTUBE_REFRESH_TOKEN を設定してください。YouTube Live の追跡には OAuth 認証情報が必要です。"
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
        "reset_nothing": "削除する永続状態はありませんでした。config.py の設定は手動で編集してください。",
        "state_read_failed": "状態ファイルを読み取れませんでした。Background Daemon のログを確認してください。",
        "oauth_refresh_error": (
            "Google OAuth token refresh failed. Re-create YOUTUBE_REFRESH_TOKEN with "
            "the same YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in OAuth Playground. "
            "Also confirm the OAuth client is a Web application and the streaming "
            "Google account is added as a test user. Original error: {error}"
        ),
        "unknown_value": "未取得",
        "missing_value": "未設定",
    },
    "en": {
        "setup_error": "An error occurred while setting up the YouTube Live assistant.",
        "missing_credentials": (
            "YouTube credentials are still missing. Missing keys: {missing_keys}. "
            "Set YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, and YOUTUBE_REFRESH_TOKEN "
            "in the Ability config.py file, then restart the Agent."
        ),
        "missing_credentials_state_error": (
            "Set YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, and YOUTUBE_REFRESH_TOKEN "
            "in config.py. YouTube Live tracking requires OAuth credentials."
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
        "reset_nothing": "There was no saved state to delete. Edit config.py manually for setup changes.",
        "state_read_failed": "The state file could not be read. Check the Background Daemon logs.",
        "oauth_refresh_error": (
            "Google OAuth token refresh failed. Re-create YOUTUBE_REFRESH_TOKEN with "
            "the same YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in OAuth Playground. "
            "Also confirm the OAuth client is a Web application and the streaming "
            "Google account is added as a test user. Original error: {error}"
        ),
        "unknown_value": "not available",
        "missing_value": "not set",
    },
}


def get_assistant_language():
    language = str(ASSISTANT_LANGUAGE or "ja").strip().lower()
    return LANGUAGE_ALIASES.get(language, "ja")


def get_summary_system_prompt():
    return SUMMARY_SYSTEM_PROMPTS[get_assistant_language()]


def get_quiet_system_prompt():
    return QUIET_SYSTEM_PROMPTS[get_assistant_language()]


def get_speech_message(message_key):
    messages = MAIN_SPEECH_MESSAGES[get_assistant_language()]
    return messages.get(message_key, MAIN_SPEECH_MESSAGES["ja"][message_key])


def format_speech_message(message_key, **values):
    return get_speech_message(message_key).format(**values)


# Advanced API endpoints. Normally do not change these.
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
LIVE_BROADCASTS_URL = "https://www.googleapis.com/youtube/v3/liveBroadcasts"
LIVE_CHAT_MESSAGES_URL = "https://www.googleapis.com/youtube/v3/liveChat/messages"
