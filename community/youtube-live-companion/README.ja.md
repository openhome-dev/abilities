# YouTube Live Companion

YouTube Live のチャットを追跡し、最近のコメントを要約したり、コメントが静かな時に配信者へ話題の提案をする OpenHome Ability です。

非公開ライブや限定公開ライブも扱えるように、OAuth リフレッシュトークン前提で動作します。

## できること

- 自分のアクティブな YouTube Live を OAuth で探します。
- `liveChatId` を取得し、ライブチャットを定期的に取得します。
- ライブのタイトルと説明欄を取得し、要約や話題提案の文脈として使います。
- 新しいコメントが一定数たまったら、読み上げではなく流れを助手として要約します。
- 一定時間コメントがない場合、視聴者が反応しやすい話題を配信者へ提案します。
- 設定用 `main.py` と、常駐監視用 `background.py` の組み合わせで動きます。

## 話し方

この Ability は配信者本人になりきりません。OpenHome の発話は、配信者に向けた助手のコメントとして出します。

例:

```text
コメントでは次の企画についての質問が増えています。この話題に少し触れるとよさそうです。
少し静かなので、今日の配信で試していることを聞いてみると反応しやすそうです。
```

ライブタイトルや説明欄が取得できる場合は、それを文脈として使います。たとえばゲーム配信ならゲーム内の進行や次に試すこと、制作配信なら作業内容やこだわりに寄せた提案を出す想定です。

避ける話し方:

```text
みんな、次は何が見たい？
僕は今こう思っています。
```

## Ability 種別

| 項目 | 推奨値 |
| --- | --- |
| 名前 | `YouTube Live Companion` |
| カテゴリ | `Background Daemon` |
| Agent / System | まずは `Agent Ability` |
| 画像 | `icon.png` |
| トリガーワード | `youtube`, `youtube live setup`, `youtube live status`, `youtube live summary`, `youtube live reset`, `youtube reset`, `コメント要約`, `配信ステータス`, `設定リセット` |
| 必要な認証情報 | OpenHome Editor 上で `main.py` と `background.py` の OAuth 用 placeholder を置き換える |

## 認証

OpenHome の Linked Accounts には、現時点でこの Ability 用の YouTube OAuth 連携がありません。そのため、このバージョンでは `main.py` と `background.py` に置いた OAuth 認証情報を使います。

- 非公開ライブや限定公開ライブを扱うには、`YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` が必要です。
- OpenHome Ability Editor で、この Ability の `main.py` と `background.py` にある仮の値を自分の値へ置き換えます。
- OAuth クライアントシークレットやリフレッシュトークンの実値は GitHub にコミットしないでください。コミットする `main.py`, `background.py`, `config.py` には仮の値だけを残します。
- `config.py` は比較・レビュー用に残しています。runtime の `main.py` / `background.py` は `config.py` を import しません。

これは、OpenHome の Linked Accounts で YouTube OAuth が使えるようになるまでの一時的な設定方法です。

## 推奨トリガーワード

OpenHome Dashboard のトリガーワードには、次を登録してください。英語の `YouTube` は STT で `U two` や `you two` に誤変換されることがあるため、その表記ゆれも入れます。

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

`status` 単体は他の Ability や通常会話に取られやすいので、トリガーワードとしては推奨しません。

## トリガー対応表

OpenHome Dashboard には上の推奨トリガーワードを登録します。Ability 起動後、`main.py` は発話内容を次の順で判定します。

```text
reset -> summary -> status -> setup/default
```

どれにも明確に当たらない場合は `setup` 扱いになります。そのため、`youtube` 単体で起動した場合も設定確認として処理されます。

| Dashboard に登録するトリガー | コードが拾う表現 | 判定 intent | 呼ばれる処理 | ユーザーに見える反応 |
| --- | --- | --- | --- | --- |
| `youtube` | どの intent にも当たらない発話 | `setup` | `main.py` の `_save_config_from_user()` | `main.py` の OAuth 3 値を確認します。揃っていれば editor log に `YouTube credentials are available from main.py...` を出し、会話では基本的に読み上げません。不足していれば不足キーを読み上げます。 |
| `youtube live setup`, `配信設定` | `youtube setup`, `youtube設定`, `設定`, `設定確認` | `setup` | `main.py` の `_save_config_from_user()` | `youtube` 単体と同じく、`main.py` 側の認証情報が入っているか確認します。YouTube への実接続は `background.py` が担当します。 |
| `youtube live status`, `youtube status`, `u two live status`, `you two live status`, `配信ステータス`, `ライブステータス` | `you tube live status`, `状態確認`, `ライブの状態`, `状態`, `ステータス`, `接続` | `status` | `main.py` の `_speak_status()` | `youtube_live_companion_state.json` を読み、現在の状態、設定元、認証情報の取得元、対象ライブ、live chat ID、最後のエラー、要約待ちコメント数などを読み上げます。 |
| `youtube live summary`, `youtube summary`, `u two live summary`, `you two live summary`, `コメント要約`, `コメントまとめ`, `チャット要約`, `チャットまとめ` | `you tube live summary`, `comment summary`, `chat summary`, `要約`, `まとめ` | `summary` | `main.py` の `_speak_comment_summary()` | `background.py` が保存した直近コメントを、ライブタイトル・説明欄と合わせて要約します。未接続、エラー、コメントなしの場合はその状態を読み上げます。 |
| `youtube live reset`, `youtube reset`, `reset`, `設定リセット` | `配信設定リセット`, `リセット` | `reset` | `main.py` の `_reset_config()` | 保存済みの `youtube_live_companion_state.json` を削除します。`main.py` / `background.py` に入れた OAuth 値は変更しません。 |
| 発話トリガーなし | Ability の `Background Daemon` 設定で自動起動 | 常駐処理 | `background.py` の `watch_live_chat()` | `YouTube live companion watcher started` をログに出し、OAuth で自分のアクティブな YouTube Live を探します。見つかれば live chat を監視して state を更新し、配信中でない場合は `waiting_for_active_live` になります。 |

## OAuth で必要な値

この Ability は OAuth で自分の YouTube Live を探します。認証情報は、OpenHome Editor 上で `main.py` と `background.py` の両方に設定します。YouTube 接続は background daemon が行うため、`main.py` だけに値を入れても接続できません。

必要な変数:

| 変数 | 取得元 | 用途 |
| --- | --- | --- |
| `YOUTUBE_CLIENT_ID` | `https://console.cloud.google.com/apis/credentials` | Google OAuth クライアント ID |
| `YOUTUBE_CLIENT_SECRET` | `https://console.cloud.google.com/apis/credentials` | Google OAuth クライアントシークレット |
| `YOUTUBE_REFRESH_TOKEN` | `https://developers.google.com/oauthplayground` | YouTube 読み取り専用スコープで発行したリフレッシュトークン |

必要な OAuth スコープ:

```text
https://www.googleapis.com/auth/youtube.readonly
```

公開 repo には安全な仮の値だけをコミットします。OpenHome の Live Editor で自分用の Ability を編集するときだけ、`main.py` と `background.py` の次の値を実値に置き換えます。実値を GitHub にコミットしないでください。

```python
YOUTUBE_CLIENT_ID = "YOUR_YOUTUBE_CLIENT_ID"
YOUTUBE_CLIENT_SECRET = "YOUR_YOUTUBE_CLIENT_SECRET"
YOUTUBE_REFRESH_TOKEN = "YOUR_YOUTUBE_REFRESH_TOKEN"
```

## OAuth リフレッシュトークンの用意

非公開ライブで試す場合は、YouTube アカウント画面から直接 token を取得するのではなく、Google Cloud の OAuth クライアントを作り、そのクライアントで自分の YouTube アカウントを認可して `refresh_token` を発行します。

最終的に必要な値は次の 3 つです。

| 変数 | 取得元 |
| --- | --- |
| `YOUTUBE_CLIENT_ID` | Google Cloud Console の OAuth クライアント ID |
| `YOUTUBE_CLIENT_SECRET` | Google Cloud Console の OAuth クライアントシークレット |
| `YOUTUBE_REFRESH_TOKEN` | OAuth 2.0 Playground で発行したリフレッシュトークン |

### 1. Google Cloud で OAuth クライアントを作る

1. Google Cloud Console でプロジェクトを作る。
2. YouTube Data API v3 を有効化する。
3. `API とサービス` -> `OAuth 同意画面` を開く。
4. ユーザータイプは個人検証なら `External` を選ぶ。
5. アプリ名、サポートメール、デベロッパー連絡先メールを入力する。
6. テスト状態の場合は、テストユーザーに自分の YouTube 配信用 Google アカウントを追加する。
7. `API とサービス` -> `認証情報` を開く。
8. `認証情報を作成` -> `OAuth クライアント ID` を選ぶ。
9. アプリケーションの種類は `Web application` を選ぶ。
10. 承認済みリダイレクト URI に次を追加する。

```text
https://developers.google.com/oauthplayground
```

11. 作成後に表示される `クライアント ID` を `YOUTUBE_CLIENT_ID` として控える。
12. 作成後に表示される `クライアント シークレット` を `YOUTUBE_CLIENT_SECRET` として控える。

ここで作るのは `OAuth クライアント ID` です。`API キー` でも `サービス アカウント` でもありません。非公開ライブを扱うには、配信者本人の YouTube アカウントで OAuth 認可する必要があります。

### 2. OAuth Playground でリフレッシュトークンを発行する

1. [OAuth 2.0 Playground](https://developers.google.com/oauthplayground/) を開く。
2. 右上の歯車アイコンを開く。
3. 次のように設定する。

| 項目 | 値 |
| --- | --- |
| 自分の OAuth 認証情報を使う | ON |
| OAuth クライアント ID | `YOUTUBE_CLIENT_ID` |
| OAuth クライアントシークレット | `YOUTUBE_CLIENT_SECRET` |
| OAuth フロー | `Server-side` |
| アクセスタイプ | `Offline` |
| 同意画面の再表示 | `Consent Screen` |

4. ステップ 1 のスコープ入力欄に次を 1 行だけ入れる。

```text
https://www.googleapis.com/auth/youtube.readonly
```

一覧から選ぶ場合は、`YouTube Data API v3` を展開し、`youtube.readonly` スコープを選びます。`YouTube Analytics API` や `YouTube Reporting API` ではありません。

5. `Authorize APIs` を押す。
6. 自分の YouTube 配信用 Google アカウントでログインして許可する。
7. ステップ 2 に戻ったら、認可コードをトークンに交換するボタンを押す。
8. リフレッシュトークン欄に出た値を `YOUTUBE_REFRESH_TOKEN` として控える。

認可コード欄の `4/...` で始まる値は一時コードです。OpenHome に入れる値ではありません。アクセストークンも短時間で期限切れになるため、OpenHome に入れる値ではありません。

### 3. OpenHome Ability Editor の main.py と background.py に設定する

Ability の zip に含まれる `main.py` と `background.py` には仮の値だけを置いています。自分の OpenHome Ability Editor 上で両方のファイルを開き、同じ実値に差し替えます。

```python
YOUTUBE_CLIENT_ID = "your_google_oauth_client_id"
YOUTUBE_CLIENT_SECRET = "your_google_oauth_client_secret"
YOUTUBE_REFRESH_TOKEN = "your_google_oauth_refresh_token"
```

保存後は Agent を再起動してください。再起動しないと、既存プロセスには新しい値が反映されないことがあります。

保存先の対応は次のとおりです。

| 変数 | 入れる値 |
| --- | --- |
| `YOUTUBE_CLIENT_ID` | Google Cloud の OAuth クライアント ID |
| `YOUTUBE_CLIENT_SECRET` | Google Cloud の OAuth クライアント シークレット |
| `YOUTUBE_REFRESH_TOKEN` | OAuth Playground のリフレッシュトークン欄の値 |

### 4. Agent を再起動する

`main.py` と `background.py` を保存したら、Agent を再起動してから `配信設定` または `配信ステータス` をもう一度試します。OAuth で `mine=true` の配信を自動取得するため、手動の動画 ID、チャンネル ID、ライブチャット ID は設定しません。

### よくある詰まりどころ

`invalid_scope` で `invalid=[youtube]` と出る場合は、OAuth Playground のスコープ欄に `youtube` という文字だけが入っています。スコープ欄を空にして、次だけを入れ直してください。

```text
https://www.googleapis.com/auth/youtube.readonly
```

`Refresh token` が表示されない場合は、OAuth Playground の歯車でアクセスタイプを `Offline`、同意画面の再表示を `Consent Screen` に設定してから、再度 API 認可を実行します。それでも出ない場合は、Google アカウント側の既存アプリ許可を取り消してから再認可します。

OAuth Playground を使う場合は、自分の OAuth クライアントを使う設定にしてからリフレッシュトークンを発行してください。OpenHome の Ability zip や GitHub リポジトリにはリフレッシュトークンを入れないでください。

`YouTube API HTTP 401` と `unauthorized_client` が出る場合は、OpenHome ではなく Google OAuth 側で `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` の組み合わせが拒否されています。次を確認してください。

- OAuth Playground の歯車で自分の OAuth 認証情報を使う設定を ON にしてから認可したか。
- `YOUTUBE_CLIENT_ID` と `YOUTUBE_CLIENT_SECRET` が同じ Google Cloud の OAuth クライアントから取得したペアか。
- `YOUTUBE_REFRESH_TOKEN` を、その同じ `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` で作り直したか。
- Google Cloud の OAuth クライアントの種類が `Web application` になっているか。
- 承認済みリダイレクト URI に `https://developers.google.com/oauthplayground` が入っているか。
- OAuth 同意画面がテスト状態の場合、配信用 Google アカウントがテストユーザーに入っているか。

修正したら OAuth Playground でアクセストークンの再発行が成功することを確認し、その後 `main.py` と `background.py` の 3 値を同じ組み合わせで更新して Agent を再起動してください。

## runtime 設定

`POLL_INTERVAL_SECONDS` などの監視調整値は、OpenHome の Live Editor で `background.py` を編集します。
コメント要約、ステータス確認、設定確認、リセット結果などの出力言語は、`main.py` と `background.py` の `ASSISTANT_LANGUAGE` で設定します。

```python
# 日本語なら "ja"、英語なら "en" を指定します。
ASSISTANT_LANGUAGE = "en"
```

話し方を調整したい場合は、`SUMMARY_SYSTEM_PROMPTS`、`QUIET_SYSTEM_PROMPTS`、`MAIN_SPEECH_MESSAGES` の `ja` / `en` の文面を編集します。`config.py` は比較・レビュー用の reference file で、runtime からは読みません。

手順:

1. OpenHome にこの Ability の zip をアップロードする。
2. Ability の Live Editor で `main.py` と `background.py` を開く。
3. 両方のファイルで `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` を設定する。
4. 必要なら両方のファイルで `ASSISTANT_LANGUAGE` を `ja` または `en` に設定する。
5. 必要なら `background.py` のポーリング設定を調整する。
6. 保存する。
7. Agent を再起動する。

`配信設定` / `youtube live setup` のトリガーワードは、秘密情報を音声入力するためではなく、`main.py` の認証情報が設定済みか確認するための案内用です。実際の YouTube 接続は `background.py` が行うため、`background.py` にも同じ認証情報が必要です。

runtime ファイル内の設定は次の形です。

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
    "ja": """日本語で、配信者に向けた助手としてコメントの流れを要約する...
    ...
    """,
    "en": """英語で、配信者に向けた助手としてコメントの流れを要約する...
    ...
    """,
}

QUIET_SYSTEM_PROMPTS = {
    "ja": """日本語で、コメントが静かな時に配信者へ話題を提案する...
    ...
    """,
    "en": """英語で、コメントが静かな時に配信者へ話題を提案する...
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

参考ファイル:

```text
config.py
```

`config.py` は以前の centralized config との差分比較用に同梱しています。`main.py` / `background.py` は `config.py` を import しません。実値は GitHub に入れず、自分の OpenHome Ability Editor 上でだけ置き換えてください。

## ローカルテスト用 .env

Ability の runtime は、OpenHome Cloud / Ability Editor と同じく `.env` や OS 環境変数を直接読みません。

ローカル開発で OAuth 認証情報を使って確認したい場合だけ、repo のテスト harness から `.env` を読み、import 済みの `main.py` / `background.py` モジュール変数へ一時的に差し込みます。この `.env` は開発環境専用で、OpenHome Cloud では読まれません。

テスト harness は Ability zip に含めず、GitHub repo 側の [`tests/youtube-live-companion/`](https://github.com/yossitv/openhome_abilities/tree/main/tests/youtube-live-companion) に置いています。`example.env` と `test_local_config_env.py` はこのディレクトリで管理します。

```bash
cp tests/youtube-live-companion/example.env tests/youtube-live-companion/.env
python3 tests/youtube-live-companion/test_local_config_env.py \
  --env-file tests/youtube-live-companion/.env
```

`tests/youtube-live-companion/example.env` はローカルテスト用のサンプルです。実値を入れた `.env` は GitHub や Ability zip に含めないでください。

## ライブチャットの特定方法

この Ability は OAuth 設定で、次の順にライブチャットを探します。

1. OAuth リフレッシュトークンからアクセストークンを取得する。
2. `liveBroadcasts.list` の `mine=true` を呼び、自分の配信だけを取得する。
3. `status.lifeCycleStatus == "live"` の配信を選ぶ。
4. `snippet.liveChatId` が見つかったら、`liveChatMessages.list` でコメント取得を開始する。

YouTube API は `mine` と `broadcastStatus` を同時指定できないため、取得後に `status.lifeCycleStatus == "live"` の配信だけを Ability 側で選びます。

## 状態確認

トリガーワード:

```text
配信ステータス
youtube live status
u two live status
you two live status
```

状態ファイル:

```text
youtube_live_companion_state.json
```

接続中の `live_chat_id`、ライブタイトル、最後のエラーなどを確認できます。

## コメント要約

トリガーワード:

```text
コメント要約
チャット要約
youtube live summary
u two live summary
you two live summary
```

バックグラウンドデーモンが保存している直近コメントを、配信タイトル・説明欄と合わせて要約します。

自動で話してほしくない場合は、`background.py` で次を `False` にしておくと、トリガーした時だけ要約できます。

```python
SPEAK_SUMMARIES = False
SPEAK_QUIET_PROMPTS = False
```

## 設定リセット

トリガーワード:

```text
youtube live reset
youtube reset
reset
設定リセット
```

保存済みの state を削除します。`main.py` / `background.py` に入れた OAuth 値は変更しません。

## 注意

- OAuth リフレッシュトークンは秘密情報です。公開リポジトリや zip に入れないでください。
- Google 側の OAuth 同意画面やテストユーザー設定が未完了だと、リフレッシュトークンが使えないことがあります。
- YouTube API には利用量制限があります。短すぎるポーリングは避けてください。
- この Ability はチャット追跡用です。配信者の音声内容そのものを理解するには、別途音声認識連携が必要です。

## アップロード用 zip

zip は単一トップレベルディレクトリ構造にしてください。この README では、次の `youtube-live-companion/` ディレクトリ内を Ability のルートとして説明しています。

```text
youtube-live-companion/
  __init__.py
  README.md
  README.en.md
  README.ja.md
  config.py          # runtime では読まない reference file
  main.py
  background.py
  icon.png
```

OpenHome Ability Editor でも、`main.py`, `background.py`, `icon.png` が同じ階層にある前提です。`config.py` は PR review で旧 centralized config と比較しやすくするために残しています。

Ability の画像設定には、SVG ではなく画像ファイルを指定します。この Ability のアイコン PNG は Ability ルートに置いています。

```text
icon.png
```

Dashboard の画像欄に別途ファイル指定が必要な場合は、この Ability の `icon.png` を選んでください。

`icon.svg` を指定すると、OpenHome 側で `Unsupported file format image/svg+xml in image_file` になります。アップロード時は必ず PNG または JPEG を選んでください。
