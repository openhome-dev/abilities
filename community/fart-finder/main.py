"""Fart Finder voice skill.

Trigger words: "fart finder", "fart detector", "flatulence".
Intents: status / how many today / biggest, arm, disarm, sensitivity low|medium|high.
The always-on detection itself runs in background.py; this skill only reads
and adjusts it.
"""
import json

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

DEVICE_TIMEOUT_S = 8
LOCAL_TIMEOUT_S = 6.0
SETTINGS_FILE = "settings.local.json"
CONTEXT_KEY = "fartfinder"
ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]

INTENT_PROMPT = (
    "You interpret one short spoken request to a device called Fart Finder, an acoustic fart "
    "detector. Reply with ONLY a JSON object, no markdown, with fields: "
    '"intent": one of "status", "arm", "disarm", "sensitivity", "help", "exit"; '
    '"level": for sensitivity, one of "low", "medium", "high", else null. '
    'Status covers questions like how many today, what was the biggest, is it on. '
    'Exit is for stop, never mind, cancel, thanks. Anything unclear is "help".'
)

HELP = ("I can tell you today's count and the biggest event, arm or disarm the detector, "
        "or set sensitivity to low, medium, or high.")


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


def status_line(status):
    today = status.get("today") or {}
    n = int(today.get("count") or 0)
    if n == 0:
        base = "No events detected today."
    else:
        base = "%s event%s detected today." % (say_number(n).capitalize(), "" if n == 1 else "s")
        mx = today.get("max_magnitude")
        if mx:
            base += " The largest was magnitude %s, %s." % (say_number(mx), today.get("max_class", "notable"))
    armed = "Armed" if status.get("armed") else "Disarmed"
    return "%s %s, sensitivity %s." % (base, armed, status.get("sensitivity", "medium"))


class FartFinderCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    #{{register capability}}

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
        return unwrap_reply(raw)

    # --- consent / state (shared with background.py through the KV store)
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
                self.capability_worker.update_key(CONTEXT_KEY, state)
            else:
                self.capability_worker.create_key(CONTEXT_KEY, state)
        except Exception as e:
            self._log("state save failed: %r" % (e,))

    def _intent(self, text):
        try:
            raw = self.capability_worker.text_to_text_response(text, [], INTENT_PROMPT)
            start, end = raw.find("{"), raw.rfind("}")
            data = json.loads(raw[start:end + 1]) if start >= 0 else {}
        except Exception:
            data = {}
        intent = data.get("intent") if data.get("intent") in ("status", "arm", "disarm", "sensitivity", "help", "exit") else "help"
        level = data.get("level") if data.get("level") in ("low", "medium", "high") else None
        return intent, level

    async def _handle(self, intent, level):
        if intent == "status":
            r = await self._call_device("status")
            if not r.get("ok"):
                return "I can't reach the listener right now. It may not be running."
            return status_line(r)
        if intent == "arm":
            state = self._state()
            if state.get("consent") != "yes":
                self._save_state({**state, "consent": "yes"})   # the daemon picks this up and starts
            r = await self._call_device("start_listener", [json.dumps({"armed": True})])
            return "Fart Finder armed. Be on smell lookout." if r.get("ok") else \
                "Fart Finder armed. The listener will start shortly."
        if intent == "disarm":
            r = await self._call_device("set_config", [json.dumps({"armed": False})])
            return "Fart Finder disarmed." if r.get("ok") else "I couldn't reach the listener."
        if intent == "sensitivity":
            if not level:
                return "Which sensitivity: low, medium, or high?"
            r = await self._call_device("set_config", [json.dumps({"sensitivity": level})])
            return "Sensitivity set to %s." % level if r.get("ok") else "I couldn't reach the listener."
        return HELP

    async def _trigger_utterance(self):
        """The sentence that triggered us. History is only appended after the
        ability finishes, so use the transcription wait, then worker fields."""
        try:
            text = await self.capability_worker.wait_for_complete_transcription()
            if text and text.strip():
                return text.strip()
        except Exception as e:
            self._log("wait_for_complete_transcription: %r" % (e,))
        try:
            if self.worker.transcription and str(self.worker.transcription).strip():
                return str(self.worker.transcription).strip()
        except Exception:
            pass
        try:
            if self.worker.last_transcription and str(self.worker.last_transcription).strip():
                return str(self.worker.last_transcription).strip()
        except Exception:
            pass
        return ""

    async def run(self):
        try:
            await self._load_file_settings()
            text = await self._trigger_utterance()
            self._log("trigger=%r" % (text,))
            intent, level = self._intent(text) if text else ("help", None)
            if intent == "help":
                # Trigger phrase alone ("fart finder"): ask once.
                text = await self.capability_worker.run_io_loop(
                    "Fart Finder here. Ask for today's count, say arm or disarm, "
                    "or set sensitivity low, medium or high.")
                intent, level = self._intent(text) if text else ("exit", None)
            self._log("intent=%s level=%s" % (intent, level))
            if intent != "exit":
                await self.capability_worker.speak(await self._handle(intent, level))
        except Exception as e:
            self._log("error: %r" % (e,))
            await self.capability_worker.speak("Something went wrong with Fart Finder.")
        finally:
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())
