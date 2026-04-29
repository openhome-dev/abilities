# Sonos Controller — OpenHome Ability

**REQUIRES LOCALLINK TO WORK**

Voice-controlled Sonos speaker ability for [OpenHome](https://openhome.com). Say **"sonos"** to open a command session, issue commands, say an exit word to close.

## Architecture

```
OpenHome cloud
    └── sonos_ability.py   (this ability, runs in cloud)
            └── LocalLink (WebSocket → local_client_terminal.py)
                    └── soco-cli  (runs on local machine, same LAN as Sonos)
                            └── Sonos speakers (UPnP)
```

Spotify search uses the Spotify Web API (Client Credentials) via `curl`, also executed locally.

## Setup

### Dependencies

```bash
pip install soco-cli        # installs `sonos` and `sonos-discover` CLIs
```

### Speaker discovery (run once)

```bash
sonos-discover              # finds speakers, writes ~/.soco-cli/speakers_v2.pickle
```

Subsequent commands use `-l` flag to load from cache (fast, no re-scan).

### LocalLink

`local_client_terminal.py` must be running on the local machine and connected to OpenHome. It executes shell commands sent from the ability.

### Spotify (optional)

Client Credentials set in `sonos_ability.py`:

```python
SPOTIFY_CLIENT_ID     = "..."
SPOTIFY_CLIENT_SECRET = "..."
```

No user login required — token fetched automatically per search.

## Usage

Say **"sonos"** → ability opens session and announces ready state.

| Voice command | Action |
|---|---|
| play / pause / next / previous | Playback control |
| volume up / volume down / set volume 40 | Volume |
| mute / unmute | Mute toggle |
| shuffle on / repeat off / crossfade on | Play modes |
| play jazz | Search favorites → playlists → Spotify |
| play favorite Jazz 24 | Play named Sonos favorite |
| play playlist My Mix | Play named Sonos playlist |
| what's playing | Now-playing info + volume |
| list favorites | Read out saved favorites |
| list rooms | Read out discovered rooms |
| set default room Kitchen | Save room preference |
| pause all / resume all | All rooms at once |
| sleep timer | 30-min sleep (or specify minutes) |
| group rooms | Group two rooms together |
| ungroup | Remove room from group |
| done / exit / bye / quit | Close session |

## Play Search Fallback Order

1. Sonos favorites (`play_fav`)
2. Sonos playlists (`add_playlist_to_queue`)
3. Spotify playlist search → track search → `play_uri`

## Files

| File | Purpose |
|---|---|
| `sonos_ability.py` | Main ability — runs in OpenHome cloud |
| `local_client_terminal.py` | LocalLink agent — runs on local machine |
| `sonos_ability_prefs.json` | Persisted default room (auto-created) |

## Logging

All local command execution logged via `[SonosAbility]` prefix:

- `CMD →` full shell command sent
- `CMD OK / CMD FAIL` return code + stdout/stderr
- `SONOS [room] subcommand` before each soco-cli call
- Discovery, Spotify token, search results all logged
