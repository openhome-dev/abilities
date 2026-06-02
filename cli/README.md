# OpenHome Client + CLI

Link this abilities repo with your [app.openhome.com](https://app.openhome.com) account
and drive the same actions the dashboard live editor does — from code or the terminal:

1. **Create** an ability from a template (uses this repo's `templates/` + `official/`)
2. **Save / commit** an ability to your account (zips the folder, uploads it)
3. **Auto-install** it into an agent's voice call flow (pass an agent id on save)
4. **Set trigger words** (persisted in the OpenHome database)
5. **Voice-to-voice call** an agent directly, no dashboard needed

It is a thin CLI over a reusable Python library (`openhome`).

## Install

```bash
cd cli
pip install -e .
cp .env.example .env   # then fill in OPENHOME_API_KEY
```

## Authentication

Put your API key in `.env` (or run `openhome login`):

```
OPENHOME_API_KEY=...        # from app.openhome.com → Settings → API Keys
OPENHOME_JWT=...            # (optional, for now) browser access_token
```

Most endpoints use the **API key**. The save/upload, list, and delete capability
endpoints currently require a **JWT** (the browser `access_token` —
`copy(localStorage.getItem('access_token'))` in the console on app.openhome.com).

The client picks the credential automatically: JWT-gated calls use `OPENHOME_JWT`
if set, otherwise they fall back to sending the API key — so once the backend
accepts the API key on those routes, **nothing in the client changes**.

## CLI

```bash
openhome login                                  # verify + save credentials
openhome agents                                 # list your agents
openhome templates                              # list templates
openhome sync                                   # pull your account's abilities → user/
openhome create my-weather -t api-template      # scaffold locally → user/my-weather
# …edit user/my-weather/main.py…
openhome push user/my-weather \
    --description "Current weather by city" \
    --triggers "what's the weather, weather" \
    --agent <AGENT_ID>                          # save + install into that agent
openhome set-triggers my-weather "weather, forecast"
openhome list
openhome call <AGENT_ID> "what's the weather in Tokyo"   # direct voice trigger
openhome chat <AGENT_ID>                        # interactive session
```

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
[`openhome/transport.py`](openhome/transport.py) for the auth-mode handling. Endpoints
that currently require a JWT (and are candidates for accepting the API key):

| Action | Method + Path |
|--------|---------------|
| Create ability | `POST /api/capabilities/add-capability/` (multipart, **nested** zip) |
| Update ability in place (save/commit) | `POST /api/capabilities/validate/release-code/{release_id}/` (multipart, **flat** zip, `committed`, `commit_message`) |
| List user abilities | `GET /api/capabilities/get-all-capabilities/` |
| Download ability source (zip) | `GET /api/capabilities/get/template-file/{capability_id}/` |
| Installed detail (effective triggers + releases) | `GET /api/capabilities/get/installed-capability/by-capability/{capability_id}/` |
| Delete ability | `DELETE /api/capabilities/delete-capability/{id}` |
| Uninstall ability | `DELETE /api/capabilities/uninstall-capability/{id}/` |

Already API-key based: `verify_apikey`, `get_personalities`,
`edit-installed-capability` (X-API-KEY), `edit-personality` (X-API-KEY), and the
voice `voice-stream` WebSocket.

> Note: the download endpoint returns a **flat** zip (files at the root). The
> installed-detail endpoint also exposes per-version `zip_file` media paths and
> `is_committed` / `commit_message` — the basis for a future in-place *commit*
> (versioned update) flow.
