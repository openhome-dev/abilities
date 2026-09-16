#!/usr/bin/env bash
# Fart Finder DevKit install. Run on the Raspberry Pi from the ability folder:
#   bash pi/install.sh
# Creates a venv, installs requirements, checks the mic, and optionally
# installs the systemd unit (fallback if the OpenHome session does not stay
# open; by default the cloud daemon starts the listener itself).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

sudo apt-get install -y python3-venv libportaudio2 libsndfile1 ffmpeg >/dev/null
python3 -m venv .venv
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q -r requirements.txt

echo "--- input devices ---"
.venv/bin/python -m listener devices
echo "--- ALSA capture devices ---"
arecord -l || true

# Week 5 check: can we open the mic while the OpenHome agent is running?
if .venv/bin/python -m listener record 2 /tmp/ff_check.wav 2>/tmp/ff_check.err; then
  echo "mic OK: /tmp/ff_check.wav"
else
  echo "mic BUSY or missing. See /tmp/ff_check.err. Options:"
  echo "  1. ALSA dsnoop shared capture: copy pi/asound.conf to /etc/asound.conf and set device=fartfinder in listener.json"
  echo "  2. A second USB microphone dedicated to Fart Finder"
fi

if [[ "${1:-}" == "--systemd" ]]; then
  sed "s#__HERE__#$HERE#g; s#__USER__#$USER#g" pi/fartfinder.service | sudo tee /etc/systemd/system/fartfinder.service >/dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable --now fartfinder
  systemctl status fartfinder --no-pager | head -5
fi
