# Fart Finder

Seismic-grade flatulence detection for the OpenHome DevKit.

It listens to the room, recognises the sound, grades it on the Ripter scale,
and warns everyone in range:

> "Warning. Room-clearing event detected. Magnitude six point two. Duration
> one point four seconds. Open a window and be on smell lookout."

Audio never leaves the device. Only the event metadata does.

## Trigger words

`fart finder`, `fart detector`, `flatulence`

"How many today?", "what was the biggest?", "arm", "disarm", "set sensitivity
to high". Detection itself runs in the background with no wake word.

## How it works

| Stage | What |
|---|---|
| Gate | Adaptive noise floor. Opens at +12 dB, closes at +6 dB, 150 ms to 4 s. |
| Classify | YAMNet (Google AudioSet, 521 classes, has a literal Fart class) on the segment. |
| Verify | Optional logistic head on the YAMNet embedding, trained against raspberries, burps and chairs. Ships off until there is data for it. |
| Grade | `M = 2 log10(peak/floor) + 0.6 log10(duration/0.25 s)`, 1 to 10. Whisper, squeak, standard-issue, notable, room-clearing, structural, evacuate, biblical. |

The device runs the detector and logs events. The cloud daemon polls it,
interrupts, and speaks. The skill answers questions.

## Files

| File | Runs on | Does |
|---|---|---|
| `main.py` | cloud | Voice commands |
| `background.py` | cloud | Poll, announce, hooks |
| `devkit_functions.py` | device | Listener daemon and RPC. The only file the upload scan exempts, so all OS and file access lives here. |
| `listener/` | device | Pure signal processing. `listener/models/` ships YAMNet (`yamnet.tflite`, 16 MB, Apache 2.0) and its class map, so nothing is downloaded at install time. |
| `pi/` | device | Install script, systemd unit, ALSA shared-capture config |

## Setup

1. Install the ability and say "fart finder, arm" once. That records consent and starts the listener.
2. Optional settings, in Settings → API Keys by name:

| Name | Values | Default |
|---|---|---|
| `fartfinder_hooks` | `speak`, `led`, `webhook`, comma separated | `speak` |
| `fartfinder_webhook_url` | POST target for each event | |
| `fartfinder_transport` | `devkit` or `local` | `devkit` |

On the Pi, `bash pi/install.sh` creates the venv, installs `requirements.txt`, and checks the mic.

## Device commands

```bash
python devkit_functions.py start_listener '{"sensitivity":"medium"}'
python devkit_functions.py status
python devkit_functions.py poll_events 0
python devkit_functions.py set_config '{"sensitivity":"high"}'
python devkit_functions.py inject clip.wav       # feed a file through the live detector
python devkit_functions.py replay clip.wav       # run the detector on a file, no daemon
python devkit_functions.py record 30 room.wav    # capture training audio
python devkit_functions.py selftest              # mic, model, timing
python devkit_functions.py stop_listener
```

State lives in `~/.fartfinder/`: `events.jsonl`, `listener.json`, `daemon.log`.

## Developing without a DevKit

The cloud side can drive a Mac instead. Copy `settings.local.json.example` to
`settings.local.json` with your absolute paths, run `openhome local start
--role local-link`, push the ability, and open a session. `tests/live/e2e.sh`
in the project repo scripts the whole thing.

## Status

Verified end to end with a Mac standing in for the DevKit. Not yet run on DevKit
hardware. Detector: 88% recall on public clips, zero false alarms so far,
YAMNet alone.
