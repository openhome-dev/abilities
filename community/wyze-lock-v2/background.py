import hashlib
import hmac
import json
import random
import time
import uuid
from email.utils import parsedate_to_datetime

import requests

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


# ── Wyze credentials / device ──
EMAIL = ""
PASSWORD = ""
KEY_ID = ""
API_KEY = ""

DEVICE_MAC = "DX_LB2_xxxxxxxxxxxx"
BASE_URL = "https://app.wyzecam.com"
AUTH_URL = "https://auth-prod.api.wyze.com/api/user/login"
SIGNING_SECRET = "wyze_app_secret_key_132"
APP_ID = "9319141212m2ik"
APP_INFO = "wyze_android_3.11.0.758"
APP_VERSION = "3.11.0.758"
TOKEN_TTL_SECONDS = 1800

# ── Twilio (WhatsApp Sandbox) ──
TWILIO_ACCOUNT_SID = ""
TWILIO_AUTH_TOKEN = ""
TWILIO_SANDBOX_WHATSAPP = "whatsapp:+1xxxxxxxxxx"
ALLOWED_WHATSAPP_SENDER = "whatsapp:+1xxxxxxxxxx"
TWILIO_MESSAGES_URL = (
    f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
)

# ── Daemon tunables ──
POLL_SECONDS = 4.0
STARTUP_GRACE_SEC = 60.0   # process messages from up to N seconds before daemon start
SEEN_SID_CAP = 500          # bound the in-memory dedup set

# ── Password config (loaded from lockpreferences.json bundled with the ability) ──
PREFS_FILENAME = "lockpreferences.json"
DEFAULT_UNLOCK_PASSWORD = "open up"
DEFAULT_LOCK_PASSWORD = "lock up"


class WyzeLockClient:
    def __init__(self):
        self.phone_id = str(uuid.uuid4())
        self._token_val = None
        self._token_ts = 0.0

    def _login(self):
        pw = PASSWORD
        for _ in range(3):
            pw = hashlib.md5(pw.encode()).hexdigest()
        resp = requests.post(
            AUTH_URL,
            headers={"keyid": KEY_ID, "apikey": API_KEY},
            json={"email": EMAIL, "password": pw},
            timeout=15,
        )
        try:
            data = resp.json()
        except Exception:
            raise RuntimeError("login: status=%d non-json body=%s" % (resp.status_code, resp.text[:200]))
        token = data.get("access_token")
        if not token:
            raise RuntimeError("login: status=%d body=%s" % (resp.status_code, str(data)[:200]))
        return token

    def _token(self):
        if not self._token_val or (time.time() - self._token_ts) > TOKEN_TTL_SECONDS:
            self._token_val = self._login()
            self._token_ts = time.time()
        return self._token_val

    def _sign(self, token, body):
        secret = hashlib.md5((token + SIGNING_SECRET).encode()).hexdigest()
        return hmac.new(secret.encode(), body.encode(), hashlib.md5).hexdigest()

    def _headers(self, token, body):
        return {
            "access_token": token,
            "appid": APP_ID,
            "appinfo": APP_INFO,
            "appversion": APP_VERSION,
            "env": "Prod",
            "phoneid": self.phone_id,
            "requestid": uuid.uuid4().hex,
            "Signature2": self._sign(token, body),
            "Content-Type": "application/json; charset=utf-8",
        }

    def _target(self):
        parts = DEVICE_MAC.split("_")
        return {"id": DEVICE_MAC, "model": "_".join(parts[:2])}

    def _call(self, path, payload):
        body = json.dumps(payload)
        token = self._token()
        resp = requests.post(
            f"{BASE_URL}{path}",
            headers=self._headers(token, body),
            data=body,
            timeout=15,
        )
        return resp.json()

    def get_status(self):
        ts = int(time.time() * 1000)
        return self._call("/app/v4/iot3/get-property", {
            "nonce": str(ts),
            "payload": {
                "cmd": "get_property",
                "props": [
                    "lock::lock-status", "lock::door-status",
                    "iot-device::iot-state", "battery::battery-level",
                    "battery::power-source", "device-info::firmware-ver",
                ],
                "tid": random.randint(1000, 99999),
                "ts": ts,
                "ver": 1,
            },
            "targetInfo": self._target(),
        })

    def _run_action(self, action):
        ts = int(time.time() * 1000)
        return self._call("/app/v4/iot3/run-action", {
            "nonce": str(ts),
            "payload": {
                "action": f"lock::{action}",
                "cmd": "run_action",
                "params": {
                    "action_id": random.randint(10000, 99999),
                    "type": 1,
                    "username": EMAIL,
                },
                "tid": random.randint(1000, 99999),
                "ts": ts,
                "ver": 1,
            },
            "targetInfo": self._target(),
        })

    def lock(self):
        return self._run_action("lock")

    def unlock(self):
        return self._run_action("unlock")

    def is_locked(self):
        """True if locked, False if unlocked, None if unknown."""
        try:
            resp = self.get_status()
            val = resp.get("data", {}).get("props", {}).get("lock::lock-status")
        except Exception:
            return None
        if isinstance(val, bool):
            return val
        return None


def _twilio_date_to_epoch(s):
    try:
        return parsedate_to_datetime(s).timestamp()
    except Exception:
        return None


class TwilioLockWatcherCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    #{{register capability}}

    def _log(self, msg):
        try:
            self.worker.editor_logging_handler.info("%s: TwilioLock: %s" % (time.time(), msg))
        except Exception:
            pass

    async def _load_passwords(self):
        """Read passwords from lockpreferences.json in the ability bundle. Falls back to defaults."""
        unlock_pw = DEFAULT_UNLOCK_PASSWORD
        lock_pw = DEFAULT_LOCK_PASSWORD
        try:
            raw = await self.capability_worker.read_file(PREFS_FILENAME, in_ability_directory=True)
        except Exception as e:
            self._log("prefs read failed (using defaults): %s" % e)
            return unlock_pw.lower(), lock_pw.lower()
        if not raw:
            self._log("prefs empty (using defaults)")
            return unlock_pw.lower(), lock_pw.lower()
        try:
            data = json.loads(raw)
        except Exception as e:
            self._log("prefs invalid json (using defaults): %s" % e)
            return unlock_pw.lower(), lock_pw.lower()

        v = data.get("unlock_password")
        if isinstance(v, str) and v.strip():
            unlock_pw = v
        v = data.get("lock_password")
        if isinstance(v, str) and v.strip():
            lock_pw = v
        return unlock_pw.strip().lower(), lock_pw.strip().lower()

    def _fetch_recent_messages(self):
        """Fetch the most recent inbound WhatsApp messages from the allowed sender."""
        try:
            resp = requests.get(
                TWILIO_MESSAGES_URL,
                params={
                    "From": ALLOWED_WHATSAPP_SENDER,
                    "To": TWILIO_SANDBOX_WHATSAPP,
                    "PageSize": "10",
                },
                auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
                timeout=15,
            )
        except Exception as e:
            self._log("fetch err: %s" % e)
            return []
        if not resp.ok:
            self._log("fetch status=%d body=%s" % (resp.status_code, resp.text[:200]))
            return []
        try:
            return resp.json().get("messages", [])
        except Exception as e:
            self._log("fetch json err: %s" % e)
            return []

    def _reply(self, body):
        try:
            requests.post(
                TWILIO_MESSAGES_URL,
                data={
                    "From": TWILIO_SANDBOX_WHATSAPP,
                    "To": ALLOWED_WHATSAPP_SENDER,
                    "Body": body,
                },
                auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
                timeout=15,
            )
        except Exception as e:
            self._log("reply err: %s" % e)

    def _unlock(self):
        try:
            client = WyzeLockClient()
            if client.is_locked() is False:
                self._log("already unlocked")
                self._reply("Door is already unlocked.")
                return
            client.unlock()
            self._log("unlock sent")
            self._reply("Door unlocked.")
        except Exception as e:
            self._log("unlock failed: %s" % e)
            self._reply("Sorry, unlock failed.")

    def _lock(self):
        try:
            client = WyzeLockClient()
            if client.is_locked() is True:
                self._log("already locked")
                self._reply("Door is already locked.")
                return
            client.lock()
            self._log("lock sent")
            self._reply("Door locked.")
        except Exception as e:
            self._log("lock failed: %s" % e)
            self._reply("Sorry, lock failed.")

    async def _watcher_loop(self):
        self._log("watcher started")
        unlock_pw, lock_pw = await self._load_passwords()
        self._log("passwords loaded (unlock=%d chars, lock=%d chars)" % (len(unlock_pw), len(lock_pw)))
        min_epoch = time.time() - STARTUP_GRACE_SEC
        seen_sids = set()

        while True:
            try:
                messages = self._fetch_recent_messages()
                # Process oldest-first so confirmations stay in order
                messages.sort(key=lambda m: m.get("date_sent") or "")

                for m in messages:
                    sid = m.get("sid")
                    if not sid or sid in seen_sids:
                        continue

                    # Inbound only
                    if str(m.get("direction", "")).lower() != "inbound":
                        seen_sids.add(sid)
                        continue

                    # Allowlist (defense in depth — already filtered in fetch params)
                    if str(m.get("from", "")) != ALLOWED_WHATSAPP_SENDER:
                        seen_sids.add(sid)
                        continue

                    # Skip anything older than daemon startup grace window
                    msg_epoch = _twilio_date_to_epoch(m.get("date_sent", ""))
                    if msg_epoch is not None and msg_epoch < min_epoch:
                        seen_sids.add(sid)
                        continue

                    seen_sids.add(sid)
                    body = (m.get("body") or "").strip().lower()
                    if not body:
                        continue

                    self._log("msg sid=%s body=%r" % (sid[:10], body[:80]))

                    # Password-gated dispatch: lock_password locks, unlock_password unlocks,
                    # anything else is silently ignored (don't tip off probers).
                    if lock_pw and lock_pw in body:
                        self._lock()
                    elif unlock_pw and unlock_pw in body:
                        self._unlock()
                    else:
                        self._log("no password match, ignoring")

                # Bound dedup set
                if len(seen_sids) > SEEN_SID_CAP:
                    seen_sids = set(list(seen_sids)[-(SEEN_SID_CAP // 2):])
            except Exception as e:
                self._log("loop err: %s" % e)

            await self.worker.session_tasks.sleep(POLL_SECONDS)

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.background_daemon_mode = background_daemon_mode
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self._watcher_loop())
