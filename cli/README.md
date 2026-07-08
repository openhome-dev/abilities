# OpenHome Client + CLI

Link this abilities repo with your [app.openhome.com](https://app.openhome.com) account
and drive the same actions the dashboard live editor does — from code or the terminal:

1. **Create** an ability from a template (uses this repo's `templates/` + `official/`)
2. **Save / commit** an ability to your account (zips the folder, uploads it)
3. **Auto-install** it into an agent's voice call flow (pass an agent id on save)
4. **Set trigger words** (persisted in the OpenHome database)
5. **Voice-to-voice call** an agent directly, no dashboard needed
6. **Run a Local Link bridge** so an agent can execute requests on your own machine

It is a thin CLI over a reusable Python library (`openhome`).

## Install

Run these from the **abilities repo root**:

```bash
python3 -m venv cli/.venv && source cli/.venv/bin/activate
pip install -e cli
cp .env.example .env          # at the repo ROOT — then fill in OPENHOME_API_KEY
```

The `openhome` command then works from **any directory** (the repo root is the
natural place to run it). `.env` is discovered from the repo root automatically,
so you don't need to `cd cli`. New/synced abilities land in `user/` at the root.

For the **voice call** (`openhome call`) you also need the `mpv` player and PortAudio:

```bash
# macOS
brew install mpv portaudio
# Linux
sudo apt install mpv portaudio19-dev
```

## Authentication

Put your API key in `.env` (or run `openhome login`):

```
OPENHOME_API_KEY=...        # from app.openhome.com → Settings → API Keys
OPENHOME_JWT=...            # optional — only for a real browser session
```

**The API key alone is enough for everything** — create, push, list, sync, delete,
and the voice call. The client sends it the way each endpoint expects:

- `/api/sdk/*` (agents, verify) → api_key in the JSON body
- everything else → **`X-API-KEY: <api_key>`** header

`OPENHOME_JWT` is optional: if set, the capability endpoints use it as a
`Bearer` token (a browser session); if empty, they use `X-API-KEY`. Either works.
The api_key is **never** sent as a `Bearer` token (the server runs `Bearer` through
SimpleJWT and would reject it).

## CLI — full command reference

### Setup / account
```bash
openhome login --api-key <KEY> --jwt <JWT>   # verify + save credentials to ~/.openhome
openhome agents                              # list your agents (id + name)
openhome templates                           # list templates you can scaffold from
openhome list                                # list abilities on your account
```

### Create a new ability (auto-pushes to your account)
```bash
# interactive — prompts for trigger words + description:
openhome create myskill -t basic-template

# non-interactive:
openhome create myskill -t basic-template \
    --triggers "run my skill, my skill" \
    --description "what it does" \
    --agent <AGENT_ID>      # optional: install into an agent (omit = global)

openhome create myskill -t basic-template --no-push   # scaffold only, don't push
```
Scaffolds `user/myskill/`, then saves it to your account. `--name` is derived
alphanumeric (hyphens stripped — the backend requires it).

### Edit, then push (updates in place — same id, never delete+recreate)
```bash
# …edit user/myskill/main.py…
openhome push user/myskill                       # save a DRAFT update
openhome push user/myskill --commit -m "v2 fix"  # COMMIT a version (v1 → v2)
```

### Trigger words / enable / disable
```bash
openhome set-triggers myskill "weather, forecast"
openhome enable myskill
openhome disable myskill
```

### Voice (no dashboard)
```bash
openhome call                       # 🎙 real voice call to the DEFAULT agent (0) — mic in, speaker out
openhome call 238371                # voice call a specific agent
openhome call --say "run my skill"  # one-shot TEXT trigger to default agent, prints the reply
openhome call 238371 --say "hi"     # one-shot text to a specific agent
openhome chat 238371                # interactive TEXT chat (type, /quit to exit)
```
The real voice call streams your mic to the agent and plays its reply through `mpv`.
Speak after the greeting; Ctrl-C hangs up. Agent resolution: arg → `OPENHOME_AGENT_ID` → `0`.

It runs **half-duplex** — the mic is muted while the bot is speaking, because a
laptop has no hardware echo cancellation (an open mic would capture the speaker
audio and either falsely "interrupt" the bot or get its words transcribed back as
your input). `bot-speak-end` is sent only once mpv's IPC reports playback has
actually drained, so the mic re-opens at the right moment. (Hardware with echo
cancellation — e.g. a DevKit — can run full-duplex with mic barge-in.)

**Interrupt with SPACE:** press the spacebar while the bot is talking to cut it off
— this stops mpv instantly, sends `interrupt-event` + `bot-speak-end`, and discards
any remaining audio chunks until the next response begins. Server logs stream live,
colored by level (`coloredlogs`).

### Local Link (run requests on your own machine)

`openhome local` runs a small bridge on your computer that stays connected to your
OpenHome agent. When the agent needs something done locally, it sends the request to
the bridge, the bridge runs it, and the reply goes back to the agent — so a voice
agent can reach your machine without the cloud sandbox. Each request is routed to
whichever local agent is available:

- **local-link** — a raw shell executor (first-class on macOS/Linux, best-effort on Windows). Always available.
- **hermes** — used when Hermes is installed and configured.
- **openclaw** — used when OpenClaw is installed and its gateway is running.

The bridge detects which of these are ready and tells the agent. Anything installed
but not yet usable comes back with a short hint on how to enable it (e.g. start the
OpenClaw gateway).

```bash
openhome local start        # start the bridge in the background
openhome local status       # is it running?
openhome local logs         # stream requests and responses live (Ctrl-C to stop)
openhome local stop         # stop it

openhome local run          # run in the foreground for debugging (Ctrl-C to quit)
```

Options for `start` / `run`:

| Flag | Default | Meaning |
|---|---|---|
| `--client-id` | `laptop` | a name for this device |
| `--role` | `agent` | connection role |
| `--timeout` | `30` | per-request timeout, in seconds |

`openhome local logs` shows recent history and then live-tails; add `--no-follow` to
print and exit, or `-n/--lines N` to change how much history it shows first. The
background bridge reconnects on its own if the connection drops; `openhome local run
--once` connects a single time without reconnecting (handy while debugging).

### Sync (account → local) and delete
```bash
openhome sync                  # download code + effective triggers into user/ (keeps local edits)
openhome sync --force          # overwrite local code with the account version
openhome sync --prune          # also delete local folders for abilities removed on the account
openhome delete myskill        # remove from the account AND delete the local user/ folder
openhome delete myskill --keep-local   # remove from the account only
```

### Contribute an ability to the community
```bash
openhome push_to_community myskill            # copy user/myskill → community/myskill
openhome push_to_community myskill --overwrite # replace an existing community/ copy
```
Copies your finished ability from `user/` into the repo's `community/` folder
(stripping the personal `.openhome.json` manifest + build junk), runs the repo
validator, and prints the git/PR steps. Community folder names must use hyphens
(not underscores/spaces). This is separate from your account — it stages the
ability for a pull request; it does not touch app.openhome.com.

### Direction at a glance
| Direction | Command |
|---|---|
| account → local | `sync` · `sync --force` · `sync --prune` |
| local → account (new) | `create` (auto-push) · `push` (first time) |
| local → account (edit, same id) | `push` (draft) · `push --commit -m "…"` (version) |
| voice | `call` (real voice, mic+speaker) · `call --say "…"` (one-shot text) · `chat` (interactive text) |
| remove | `delete` (account + local folder) · `delete --keep-local` |
| contribute | `push_to_community <name>` (user/ → community/ for a PR) |
| local bridge | `local start` · `local status` · `local logs` · `local stop` (run agent requests on your machine) |

### The `user/` workspace

Your own abilities live in **`user/`** (gitignored — never committed). Each folder
carries a `.openhome.json` manifest linking it to the remote ability (capability id,
effective trigger words, release history), so `push` works from the folder without
re-typing flags. The manifest is excluded from the upload zip.

`openhome sync` downloads the source of every ability on your account into `user/`
and records its effective (overridden) trigger words. Local code is preserved unless
you pass `--force`. Sync only *adds/updates* — it never deletes on its own. To mirror
deletions (remove local folders whose ability was deleted on the account), add
`--prune`; folders never pushed (no `capability_id`) are always kept.

### Create vs. update (push is smart)

`push` looks at the folder's manifest and does the right thing — it **never**
deletes + re-creates:

- **New ability** (no `capability_id` yet) → creates it via `add-capability`.
- **Existing ability** → updates the code **in place** via `validate/release-code`,
  keeping the same `capability_id`.

```bash
openhome push user/myhelper                 # existing → saves a draft update
openhome push user/myhelper --commit -m "v2: fix triggers"   # commit a version
```

Committing bumps the release (`v1 → v2`) and the manifest auto-refreshes to the new
editable release. Saving a draft (default) updates the current release in place.

## Library

```python
from openhome import OpenHomeClient

oh = OpenHomeClient.from_env()

# 1. create from template
folder = oh.create_from_template("my-weather", "api-template")

# 2–4. save + install + trigger words
agents = oh.list_agents()
result = oh.save_ability(
    folder,
    name="my-weather",
    description="Current weather by city",
    category="skill",
    trigger_words=["what's the weather", "weather"],
    personality_id=agents[0].id,     # auto-installs into the call flow
)

# 5. voice-to-voice
print(oh.call(agents[0].id, "what's the weather in Tokyo"))
```

## API contract

See [`openhome/endpoints.py`](openhome/endpoints.py) for the endpoint registry and
[`openhome/transport.py`](openhome/transport.py) for the auth-mode handling. These
capability/release endpoints accept **`X-API-KEY: <api_key>`** (or a `Bearer` JWT
for a browser session):

| Action | Method + Path |
|--------|---------------|
| Create ability | `POST /api/capabilities/add-capability/` (multipart, **nested** zip) |
| Update ability in place (save/commit) | `POST /api/capabilities/validate/release-code/{release_id}/` (multipart, **flat** zip, `committed`, `commit_message`) |
| List user abilities | `GET /api/capabilities/get-all-capabilities/` |
| Download ability source (zip) | `GET /api/capabilities/get/template-file/{capability_id}/` |
| Installed detail (effective triggers + releases) | `GET /api/capabilities/get/installed-capability/by-capability/{capability_id}/` |
| Delete ability(ies) | `POST /api/capabilities/delete-capability/` (JSON `{"capability_ids": [...]}`, batch) |

Also api-key based: `verify_apikey` & `get_personalities` (api_key in body),
`edit-installed-capability` & `edit-personality` (X-API-KEY), and the voice
`voice-stream` WebSocket (api_key in the URL).

> Note: the download endpoint returns a **flat** zip (files at the root). The
> installed-detail endpoint also exposes per-version `zip_file` media paths and
> `is_committed` / `commit_message` — the basis for the in-place *commit* flow.

### Voice WebSocket (`openhome call`)

`wss://app.openhome.com/websocket/voice-stream/<api_key>/<agent_id>`

- **Use the api-key-in-URL path**, not the dashboard's `web/0` path — the latter is
  browser-only (authenticates via session cookies) and rejects scripts with `1008`.
- A **browser-like `User-Agent`** header is **required** on the handshake, or the
  server closes with `1008 (policy violation)`.
- Client → server: `{"type":"audio","data":<b64 16-bit PCM 16kHz>}`, `ack`/`audio-received`,
  `bot-speaking` / `bot-speak-end`, `interrupt-event`, `ping`.
- Server → client: `{"type":"message","data":{role,content,live,final}}`, `text`
  (`audio-init` / `audio-end` / `interrupt`), and `{"type":"audio",...}` — the audio is
  **MP3** (piped into `mpv`), despite PCM being the *input* format.

## Known limitations

- Templates must follow the backend's import policy (e.g. no `import os` outside the
  allowed block) or the upload validator rejects them.
- Updating **code** keeps the same `capability_id`; there is no separate "update
  metadata only" beyond `set-triggers` / `enable` / `disable`.
- `openhome call` (real voice) needs `mpv` + PortAudio installed (see Install).
