# YouTube Live Companion

An OpenHome Ability that watches YouTube Live chat, summarizes recent comments, and suggests topics to the streamer when chat is quiet.

It uses a YouTube OAuth refresh token so it can work with private and unlisted live streams.

## What It Does

- Finds your active YouTube Live stream through OAuth.
- Reads the stream `liveChatId`.
- Polls live chat at a configurable interval.
- Uses the stream title and description as context for summaries and suggestions.
- Summarizes the flow of recent comments as a cohost assistant instead of reading every comment aloud.
- Suggests low-pressure topics when chat has been quiet for a while.
- Uses `main.py` for user-triggered setup/status/summary actions and `background.py` for long-running chat monitoring.

## Speaking Style

This Ability does not pretend to be the streamer. OpenHome speech is written as assistant guidance directed to the streamer.

Examples:

```text
In the chat, more people are asking about the next segment. It may be good to mention that topic briefly.
The chat is a little quiet. This topic may invite responses based on today's stream.
```

When the live title or description is available, the Ability uses it as context. For example, a gaming stream should get suggestions related to game progress or next actions, while a creative stream should get suggestions related to the current work and process.

Avoided style:

```text
Everyone, what do you want to see next?
I think this is what I should do now.
```

## Ability Type

| Item | Recommended Value |
| --- | --- |
| Name | `YouTube Live Companion` |
| Category | `Background Daemon` |
| Agent / System | Start with `Agent Ability` |
| Image | `icon.png` |
| Trigger words | `youtube`, `youtube live setup`, `youtube live status`, `youtube live summary`, `youtube live reset`, `youtube reset`, `コメント要約`, `配信ステータス`, `設定リセット` |
| Required credentials | Replace the OAuth placeholders in `main.py` and `background.py` in the OpenHome Editor |

## Authentication

OpenHome Linked Accounts does not currently provide a YouTube OAuth connection for this Ability. This version therefore reads OAuth credentials from constants in `main.py` and `background.py`.

- Private and unlisted streams require `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, and `YOUTUBE_REFRESH_TOKEN`.
- In the OpenHome Ability Editor, replace the placeholder values in both `main.py` and `background.py`.
- Do not commit real OAuth client secrets or refresh tokens to GitHub. The committed `main.py`, `background.py`, and `config.py` files must keep placeholder values only.
- `config.py` is included for comparison and review. The runtime `main.py` and `background.py` files do not import `config.py`.

This is a temporary setup path until OpenHome Linked Accounts supports YouTube OAuth for this Ability.

## Recommended Trigger Words

Register the following trigger words in the OpenHome Dashboard. The English word `YouTube` can be transcribed by STT as `U two` or `you two`, so those variants are included.

```text
youtube
youtube live setup
youtube live status
youtube status
youtube live summary
youtube summary
u two live status
you two live status
u two live summary
you two live summary
youtube live reset
youtube reset
reset
配信設定
配信ステータス
ライブステータス
コメント要約
コメントまとめ
チャット要約
チャットまとめ
設定リセット
```

Using `status` by itself is not recommended because other Abilities or normal conversation may capture it.

## Trigger Behavior Table

Register the recommended trigger words above in the OpenHome Dashboard. After the Ability starts, `main.py` classifies the utterance in this order:

```text
reset -> summary -> status -> setup/default
```

If the utterance does not clearly match any intent, it falls back to `setup`. This means the simple `youtube` trigger also behaves as a setup/credential check.

| Dashboard Trigger | Expressions Caught By Code | Intent | Called Method | User-Visible Behavior |
| --- | --- | --- | --- | --- |
| `youtube` | Any utterance that does not match another intent | `setup` | `_save_config_from_user()` in `main.py` | Checks whether the three OAuth values are present in `main.py`. If they are present, the editor log shows `YouTube credentials are available from main.py...` and the Ability usually does not speak. If values are missing, it speaks the missing keys. |
| `youtube live setup`, `配信設定` | `youtube setup`, `youtube設定`, `設定`, `設定確認` | `setup` | `_save_config_from_user()` in `main.py` | Same as `youtube`: checks whether credentials exist in `main.py`. Actual YouTube connection work is done by `background.py`. |
| `youtube live status`, `youtube status`, `u two live status`, `you two live status`, `配信ステータス`, `ライブステータス` | `you tube live status`, `状態確認`, `ライブの状態`, `状態`, `ステータス`, `接続` | `status` | `_speak_status()` in `main.py` | Reads `youtube_live_companion_state.json` and speaks the current status, config source, credential source, target live stream, live chat ID, last error, and queued comments. |
| `youtube live summary`, `youtube summary`, `u two live summary`, `you two live summary`, `コメント要約`, `コメントまとめ`, `チャット要約`, `チャットまとめ` | `you tube live summary`, `comment summary`, `chat summary`, `要約`, `まとめ` | `summary` | `_speak_comment_summary()` in `main.py` | Summarizes recent comments saved by `background.py` together with the live title and description. If not connected, errored, or comment-free, it speaks that state instead. |
| `youtube live reset`, `youtube reset`, `reset`, `設定リセット` | `配信設定リセット`, `リセット` | `reset` | `_reset_config()` in `main.py` | Deletes the saved `youtube_live_companion_state.json`. It does not change OAuth values in `main.py` or `background.py`. |
| No speech trigger | Starts automatically from the Ability `Background Daemon` setting | Background process | `watch_live_chat()` in `background.py` | Logs `YouTube live companion watcher started`, looks for your active YouTube Live through OAuth, monitors live chat when found, and updates state. If no active stream exists, the state becomes `waiting_for_active_live`. |

## Required OAuth Values

This Ability uses OAuth to find your own YouTube Live stream. Set credentials in both `main.py` and `background.py` in the OpenHome Editor. YouTube connection is handled by the background daemon, so setting only `main.py` is not enough.

Required variables:

| Variable | Source | Purpose |
| --- | --- | --- |
| `YOUTUBE_CLIENT_ID` | `https://console.cloud.google.com/apis/credentials` | Google OAuth client ID |
| `YOUTUBE_CLIENT_SECRET` | `https://console.cloud.google.com/apis/credentials` | Google OAuth client secret |
| `YOUTUBE_REFRESH_TOKEN` | `https://developers.google.com/oauthplayground` | Refresh token issued with the YouTube readonly scope |

Required OAuth scope:

```text
https://www.googleapis.com/auth/youtube.readonly
```

Only safe placeholder values are committed to the public repository. Replace the following values only in your own OpenHome Ability Editor when testing:

```python
YOUTUBE_CLIENT_ID = "YOUR_YOUTUBE_CLIENT_ID"
YOUTUBE_CLIENT_SECRET = "YOUR_YOUTUBE_CLIENT_SECRET"
YOUTUBE_REFRESH_TOKEN = "YOUR_YOUTUBE_REFRESH_TOKEN"
```

## Preparing an OAuth Refresh Token

For private stream testing, do not try to copy a token directly from the YouTube account page. Create a Google Cloud OAuth client, authorize your own YouTube account with that client, and issue a `refresh_token`.

The final values you need are:

| Variable | Source |
| --- | --- |
| `YOUTUBE_CLIENT_ID` | OAuth client ID in Google Cloud Console |
| `YOUTUBE_CLIENT_SECRET` | OAuth client secret in Google Cloud Console |
| `YOUTUBE_REFRESH_TOKEN` | Refresh token from OAuth 2.0 Playground |

### 1. Create an OAuth Client in Google Cloud

1. Create a project in Google Cloud Console.
2. Enable YouTube Data API v3.
3. Open `APIs & Services` -> `OAuth consent screen`.
4. For personal testing, choose `External` as the user type.
5. Enter the app name, support email, and developer contact email.
6. If the app is in testing mode, add your YouTube streaming Google account as a test user.
7. Open `APIs & Services` -> `Credentials`.
8. Choose `Create credentials` -> `OAuth client ID`.
9. Choose `Web application` as the application type.
10. Add the following authorized redirect URI:

```text
https://developers.google.com/oauthplayground
```

11. Save the displayed client ID as `YOUTUBE_CLIENT_ID`.
12. Save the displayed client secret as `YOUTUBE_CLIENT_SECRET`.

This must be an `OAuth client ID`. It is not an API key or a service account. To access private streams, the OAuth authorization must be done with the streamer's own YouTube account.

### 2. Issue a Refresh Token in OAuth Playground

1. Open [OAuth 2.0 Playground](https://developers.google.com/oauthplayground/).
2. Open the gear icon in the upper-right corner.
3. Configure it as follows:

| Item | Value |
| --- | --- |
| Use your own OAuth credentials | ON |
| OAuth Client ID | `YOUTUBE_CLIENT_ID` |
| OAuth Client secret | `YOUTUBE_CLIENT_SECRET` |
| OAuth flow | `Server-side` |
| Access type | `Offline` |
| Prompt | `Consent Screen` |

4. In the Step 1 scope field, enter only this line:

```text
https://www.googleapis.com/auth/youtube.readonly
```

If selecting from the list, expand `YouTube Data API v3` and choose the `youtube.readonly` scope. Do not use YouTube Analytics API or YouTube Reporting API.

5. Click `Authorize APIs`.
6. Sign in with your YouTube streaming Google account and allow access.
7. When you return to Step 2, exchange the authorization code for tokens.
8. Save the value shown in the refresh token field as `YOUTUBE_REFRESH_TOKEN`.

The value starting with `4/...` in the authorization code field is temporary. It is not the value to put in OpenHome. Access tokens also expire quickly, so do not use an access token as the OpenHome value.

### 3. Set Both main.py and background.py in the OpenHome Ability Editor

The Ability zip contains placeholder values in both `main.py` and `background.py`. Open both files in your own OpenHome Ability Editor and replace them with the same real values.

```python
YOUTUBE_CLIENT_ID = "your_google_oauth_client_id"
YOUTUBE_CLIENT_SECRET = "your_google_oauth_client_secret"
YOUTUBE_REFRESH_TOKEN = "your_google_oauth_refresh_token"
```

After saving, restart the Agent. Existing processes may not pick up the new values until restart.

Value mapping:

| Variable | Value To Enter |
| --- | --- |
| `YOUTUBE_CLIENT_ID` | OAuth client ID from Google Cloud |
| `YOUTUBE_CLIENT_SECRET` | OAuth client secret from Google Cloud |
| `YOUTUBE_REFRESH_TOKEN` | Refresh token field from OAuth Playground |

### 4. Restart the Agent

After saving `main.py` and `background.py`, restart the Agent and try `配信設定` or `youtube live status` again. The Ability automatically finds your own stream through OAuth `mine=true`, so you do not manually configure a video ID, channel ID, or live chat ID.

### Common Issues

If `invalid_scope` reports `invalid=[youtube]`, the OAuth Playground scope field contains only the word `youtube`. Clear the scope field and enter only:

```text
https://www.googleapis.com/auth/youtube.readonly
```

If no `Refresh token` appears, open the OAuth Playground gear settings and set access type to `Offline` and prompt to `Consent Screen`, then authorize again. If it still does not appear, revoke the existing app permission in your Google account and authorize again.

When using OAuth Playground, make sure `Use your own OAuth credentials` is ON before issuing the refresh token. Do not put refresh tokens in the Ability zip or GitHub repository.

If `YouTube API HTTP 401` and `unauthorized_client` appear, Google OAuth is rejecting the `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, and `YOUTUBE_REFRESH_TOKEN` combination. Check the following:

- Did you enable `Use your own OAuth credentials` in OAuth Playground before authorization?
- Are `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET` from the same Google Cloud OAuth client?
- Did you recreate `YOUTUBE_REFRESH_TOKEN` with that same client ID and client secret?
- Is the Google Cloud OAuth client type `Web application`?
- Is `https://developers.google.com/oauthplayground` included in authorized redirect URIs?
- If the OAuth consent screen is in testing mode, is the streaming Google account added as a test user?

After fixing the issue, confirm that OAuth Playground can refresh an access token successfully. Then update the same three values in both `main.py` and `background.py`, and restart the Agent.

## Runtime Settings

Monitoring settings such as `POLL_INTERVAL_SECONDS` are edited in `background.py` in the OpenHome Live Editor.

The output language for comment summaries, status checks, setup checks, and reset results is controlled by `ASSISTANT_LANGUAGE` in both `main.py` and `background.py`.

```python
# Use "ja" for Japanese or "en" for English.
ASSISTANT_LANGUAGE = "en"
```

To adjust the speaking style, edit the `ja` / `en` entries in `SUMMARY_SYSTEM_PROMPTS`, `QUIET_SYSTEM_PROMPTS`, and `MAIN_SPEECH_MESSAGES`. `config.py` is a reference file for comparison and review; the runtime does not import it.

Steps:

1. Upload this Ability zip to OpenHome.
2. Open `main.py` and `background.py` in the Ability Live Editor.
3. Set `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, and `YOUTUBE_REFRESH_TOKEN` in both files.
4. If needed, set `ASSISTANT_LANGUAGE` to `ja` or `en` in both files.
5. If needed, adjust polling settings in `background.py`.
6. Save the files.
7. Restart the Agent.

The `配信設定` / `youtube live setup` trigger is not for speaking secrets aloud. It only checks whether credentials are already present in `main.py`. The actual YouTube connection is done by `background.py`, so `background.py` also needs the same credentials.

Runtime constants look like this:

```python
YOUTUBE_CLIENT_ID = "YOUR_YOUTUBE_CLIENT_ID"
YOUTUBE_CLIENT_SECRET = "YOUR_YOUTUBE_CLIENT_SECRET"
YOUTUBE_REFRESH_TOKEN = "YOUR_YOUTUBE_REFRESH_TOKEN"

ASSISTANT_LANGUAGE = "en"

GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
LIVE_BROADCASTS_URL = "https://www.googleapis.com/youtube/v3/liveBroadcasts"
LIVE_CHAT_MESSAGES_URL = "https://www.googleapis.com/youtube/v3/liveChat/messages"

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

SUMMARY_SYSTEM_PROMPTS = {
    "ja": """Japanese assistant prompt for summarizing the chat flow...
    ...
    """,
    "en": """English assistant prompt for summarizing the chat flow...
    ...
    """,
}

QUIET_SYSTEM_PROMPTS = {
    "ja": """Japanese assistant prompt for suggesting a topic when chat is quiet...
    ...
    """,
    "en": """English assistant prompt for suggesting a topic when chat is quiet...
    ...
    """,
}

MAIN_SPEECH_MESSAGES = {
    "ja": {
        "status_not_recorded": "...",
        "summary_no_messages": "...",
    },
    "en": {
        "status_not_recorded": "...",
        "summary_no_messages": "...",
    },
}
```

Reference file:

```text
config.py
```

`config.py` is included so reviewers can compare against the earlier centralized config style. `main.py` and `background.py` do not import `config.py`. Keep real values out of GitHub and replace them only in your own OpenHome Ability Editor.

## Local Test .env

The Ability runtime does not directly read `.env` files or OS environment variables, matching the OpenHome Cloud / Ability Editor behavior.

For local development only, the test harness can read `.env` and temporarily inject values into the imported `main.py` / `background.py` module variables. This `.env` is only for local development and is not read by OpenHome Cloud.

The test harness is not included in the Ability zip. It lives in [`tests/youtube-live-companion/`](https://github.com/yossitv/openhome_abilities/tree/main/tests/youtube-live-companion) in the GitHub repository. `example.env` and `test_local_config_env.py` are managed there.

```bash
cp tests/youtube-live-companion/example.env tests/youtube-live-companion/.env
python3 tests/youtube-live-companion/test_local_config_env.py \
  --env-file tests/youtube-live-companion/.env
```

`tests/youtube-live-companion/example.env` is only a local development sample. Do not commit a `.env` file containing real values, and do not include it in the Ability zip.

## Live Chat Discovery

This Ability finds live chat in this order:

1. Uses the OAuth refresh token to get an access token.
2. Calls `liveBroadcasts.list` with `mine=true` to list only your broadcasts.
3. Selects a broadcast where `status.lifeCycleStatus == "live"`.
4. If `snippet.liveChatId` exists, starts reading comments with `liveChatMessages.list`.

YouTube API does not allow `mine` and `broadcastStatus` to be used together, so the Ability filters for `status.lifeCycleStatus == "live"` after fetching broadcasts.

## Status Check

Trigger words:

```text
配信ステータス
youtube live status
u two live status
you two live status
```

State file:

```text
youtube_live_companion_state.json
```

This can report the connected `live_chat_id`, live title, last error, and related state.

## Comment Summary

Trigger words:

```text
コメント要約
チャット要約
youtube live summary
u two live summary
you two live summary
```

The user-triggered summary uses recent comments saved by the background daemon, plus the live title and description.

If you do not want automatic speech from the daemon, set these values in `background.py`:

```python
SPEAK_SUMMARIES = False
SPEAK_QUIET_PROMPTS = False
```

Then summaries are only spoken when triggered manually.

## Reset State

Trigger words:

```text
youtube live reset
youtube reset
reset
設定リセット
```

This deletes the saved state file. It does not change OAuth values in `main.py` or `background.py`.

## Notes

- OAuth refresh tokens are secrets. Do not put them in a public repository or upload zip.
- Google OAuth consent screen or test-user setup may prevent refresh tokens from working if incomplete.
- YouTube API has quota limits. Avoid overly short polling intervals.
- This Ability tracks chat. Understanding the streamer's spoken audio would require a separate speech recognition integration.

## Upload Zip

The zip must contain a single top-level directory. In this README, `youtube-live-companion/` is the Ability root.

```text
youtube-live-companion/
  __init__.py
  README.md
  README.en.md
  README.ja.md
  config.py          # reference file; not imported at runtime
  main.py
  background.py
  icon.png
```

The OpenHome Ability Editor expects `main.py`, `background.py`, and `icon.png` to be in the same directory. `config.py` remains included only to make review against the older centralized config easier.

Use the PNG icon file for the Ability image:

```text
icon.png
```

If the Dashboard requires a separate image file selection, choose this Ability's `icon.png`.

Using `icon.svg` causes OpenHome to reject the image with `Unsupported file format image/svg+xml in image_file`. Always use PNG or JPEG for upload.
