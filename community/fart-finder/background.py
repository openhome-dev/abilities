"""Fart Finder background daemon (cloud side).

Starts at session begin. Runs the consent check once, starts the device
listener, then polls it every POLL_INTERVAL_S. Each new event is announced in
the emergency-broadcast voice after send_interrupt_signal(), then hooks run.

Device transport is selected by the `fartfinder_transport` setting:
    devkit  (default)  send_devkit_capability_action -> devkit_functions.py on the Pi
    local              exec_local_command -> devkit_functions.py on a Mac via `openhome local`
For local, `fartfinder_local_cmd` must be the absolute command prefix, e.g.
    /Users/me/openhome-fartfinder/.venv/bin/python /Users/me/openhome-fartfinder/abilities/user/fart-finder/devkit_functions.py
"""
import json
from time import time

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

POLL_INTERVAL_S = 1.5
DEVICE_TIMEOUT_S = 8
LOCAL_TIMEOUT_S = 6.0
SETTINGS_FILE = "settings.local.json"
RESTART_BACKOFF_S = 15.0
CONTEXT_KEY = "fartfinder"

ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]

CLASS_LINES = {
    "whisper": ("Minor event detected.", "Probably deniable."),
    "squeak": ("Localised event detected.", "No action required."),
    "standard-issue": ("Warning. Fart detected.", "Be on smell lookout."),
    "notable": ("Warning. Notable event detected.", "Be on smell lookout."),
    "room-clearing": ("Warning. Room-clearing event detected.", "Open a window and be on smell lookout."),
    "structural": ("Warning. Structural event detected.", "Check on the dog."),
    "evacuate": ("Warning. Evacuate the vicinity.", "This is not a drill."),
    "biblical": ("Warning. A magnitude nine event.", "Records have been kept."),
}

NOT_ARMED_NOTICE = ("Fart Finder is installed but not armed. It listens to this room continuously; audio "
                    "never leaves the device and nothing is stored. Say fart finder, arm, to turn it on.")
CONSENT_POLL_S = 10.0


def unwrap_reply(raw):
    """Device replies arrive in transport envelopes, e.g. Local Link:
    {'type':'response','data':{'status':'ok','data':'<json>'}}. Descend through
    'data' until a dict with 'ok' or a JSON string is found."""
    for _ in range(6):
        if isinstance(raw, dict):
            if "ok" in raw:
                return raw
            if "data" in raw:
                raw = raw["data"]
                continue
            if "result" in raw:
                raw = raw["result"]
                continue
            return {"ok": False, "error": "unrecognised device reply"}
        if isinstance(raw, str):
            text = raw.strip()
            for line in reversed(text.splitlines()):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        raw = json.loads(line)
                        break
                    except ValueError:
                        continue
            else:
                return {"ok": False, "error": "unparseable device reply: %s" % text[:200]}
            continue
        return {"ok": False, "error": "empty device reply"}
    return {"ok": False, "error": "device reply nested too deep"}


def say_number(x):
    x = round(float(x), 1)
    whole = int(x)
    tenth = int(round((x - whole) * 10))
    w = "ten" if whole == 10 else ONES[whole] if whole < 10 else str(whole)
    return w if tenth == 0 else "%s point %s" % (w, ONES[tenth])


def announcement(event):
    lead, advice = CLASS_LINES.get(event.get("class"), CLASS_LINES["standard-issue"])
    return " ".join([lead,
                     "Magnitude %s." % say_number(event.get("magnitude", 4.0)),
                     "Duration %s seconds." % say_number(event.get("duration_s", 0.5)),
                     advice])


class FartFinderBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # Do not change following tag of register capability
    #{{register capability}}

    # ------------------------------------------------------------ settings
    _file_settings = None

    async def _load_file_settings(self):
        """settings.local.json in the ability folder, for dev without the dashboard."""
        if self._file_settings is not None:
            return
        self._file_settings = {}
        try:
            if await self.capability_worker.check_if_file_exists(SETTINGS_FILE, True):
                raw = await self.capability_worker.read_file(SETTINGS_FILE, True)
                data = json.loads(raw or "{}")
                if isinstance(data, dict):
                    self._file_settings = data
        except Exception as e:
            self._log("settings file: %r" % (e,))

    def _setting(self, name, default=""):
        """Settings -> API Keys wins, then settings.local.json, then default."""
        try:
            v = self.capability_worker.get_api_keys(name)
            if v:
                return v
        except Exception:
            pass
        v = (self._file_settings or {}).get(name)
        return str(v) if v not in (None, "") else default

    def _log(self, msg):
        self.worker.editor_logging_handler.info("[FartFinder] %s" % msg)

    # ----------------------------------------------------------- transport
    async def _call_device(self, fn, args=None):
        args = [str(a) for a in (args or [])]
        transport = self._setting("fartfinder_transport", "devkit").strip().lower()
        try:
            if transport == "local":
                prefix = self._setting("fartfinder_local_cmd", "")
                if not prefix:
                    return {"ok": False, "error": "fartfinder_local_cmd not set"}
                cmd = " ".join([prefix, fn] + ["'%s'" % a.replace("'", "'\\''") for a in args])
                raw = await self.capability_worker.exec_local_command(cmd, timeout=LOCAL_TIMEOUT_S)
            else:
                raw = await self.capability_worker.send_devkit_capability_action(fn, args, DEVICE_TIMEOUT_S)
        except Exception as e:
            return {"ok": False, "error": "transport: %r" % (e,)}
        parsed = self._parse(raw)
        if not parsed.get("ok"):
            self._log("device %s failed: %r raw=%r" % (fn, parsed.get("error"), str(raw)[:160]))
        return parsed

    def _parse(self, raw):
        return unwrap_reply(raw)

    # ------------------------------------------------------------- consent
    def _state(self):
        try:
            v = self.capability_worker.get_single_key(CONTEXT_KEY)
            if isinstance(v, str):
                try:
                    v = json.loads(v)
                except ValueError:
                    return {}
            if isinstance(v, dict) and "value" in v:
                v = v["value"]            # {'key': ..., 'value': {...}} or value None when missing
            if isinstance(v, str):
                try:
                    v = json.loads(v)
                except ValueError:
                    return {}
            return v if isinstance(v, dict) else {}
        except Exception as e:
            self._log("state read failed: %r" % (e,))
            return {}

    def _save_state(self, state):
        try:
            if self._state():
                r = self.capability_worker.update_key(CONTEXT_KEY, state)
            else:
                r = self.capability_worker.create_key(CONTEXT_KEY, state)
            if not (isinstance(r, dict) and r.get("success", True)):
                self._log("state save rejected: %r" % (r,))
        except Exception as e:
            self._log("state save failed: %r" % (e,))

    async def _wait_for_consent(self):
        """A daemon must never await user input (it never gets control back),
        so consent is recorded by the skill's "arm" intent. Announce once,
        then poll the stored state."""
        state = self._state()
        if state.get("consent") == "yes":
            return
        if not state.get("notified"):
            await self.capability_worker.send_interrupt_signal()
            await self.capability_worker.speak(NOT_ARMED_NOTICE)
            self._save_state({**state, "notified": True})
        while self._state().get("consent") != "yes":
            await self.worker.session_tasks.sleep(CONSENT_POLL_S)
        self._log("consent recorded; starting")

    # --------------------------------------------------------------- hooks
    async def _run_hooks(self, event):
        hooks = [h.strip() for h in self._setting("fartfinder_hooks", "speak").split(",") if h.strip()]
        for h in hooks:
            try:
                if h == "speak":
                    await self._call_device("mute", [4])
                    await self.capability_worker.send_interrupt_signal()
                    await self.capability_worker.speak(announcement(event))
                elif h == "webhook":
                    url = self._setting("fartfinder_webhook_url", "")
                    if url:
                        import requests
                        requests.post(url, json=event, timeout=5)
                elif h == "led":
                    await self._call_device("led_flash", [event.get("class", "standard-issue")])
            except Exception as e:
                self._log("hook %s failed: %r" % (h, e))

    # ---------------------------------------------------------------- loop
    async def watch(self):
        self._log("daemon starting at %s" % time())
        await self._load_file_settings()
        self._log("transport=%s" % self._setting("fartfinder_transport", "devkit"))
        await self._wait_for_consent()
        since = "0"
        last_restart = 0.0
        first = True
        while True:
            try:
                if first:
                    self._log("calling start_listener via %s" % self._setting("fartfinder_transport", "devkit"))
                    r = await self._call_device("start_listener", ["{}"])
                    self._log("start_listener -> %s" % json.dumps(r)[:200])
                    first = False
                    last_restart = time()
                    # Fast-forward past anything logged before this session so
                    # old events are not announced at session start.
                    r = await self._call_device("poll_events", ["0"])
                    if r.get("ok") and r.get("events"):
                        since = r["events"][-1]["id"]
                        self._log("skipping %d earlier event(s) from today" % len(r["events"]))
                    await self.worker.session_tasks.sleep(POLL_INTERVAL_S)
                    continue
                r = await self._call_device("poll_events", [since])
                if not r.get("ok") or not r.get("daemon_alive", True):
                    if time() - last_restart > RESTART_BACKOFF_S:
                        self._log("listener down (%s); restarting" % r.get("error"))
                        await self._call_device("start_listener", ["{}"])
                        last_restart = time()
                else:
                    for ev in r.get("events", []):
                        if ev.get("id", "") <= since:
                            continue
                        since = ev["id"]
                        self._log("EVENT %s" % json.dumps(ev))
                        await self._run_hooks(ev)
                    since = max(since, r.get("last_id", since) or since)
            except Exception as e:
                self._log("loop error: %r" % (e,))
            await self.worker.session_tasks.sleep(POLL_INTERVAL_S)

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.background_daemon_mode = background_daemon_mode
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.watch())
