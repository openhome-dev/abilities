import hashlib
import hmac
import json
import random
import time
import uuid

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


class WyzeLockCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register_capability}}

    def _log(self, msg):
        try:
            self.worker.editor_logging_handler.info("%s: WyzeLock(main): %s" % (time.time(), msg))
        except Exception:
            pass

    async def _unlock(self):
        client = WyzeLockClient()
        if client.is_locked() is False:
            self._log("already unlocked")
            await self.capability_worker.speak("Door is already unlocked.")
            return
        client.unlock()
        self._log("unlock sent")
        await self.capability_worker.speak("Door unlocked.")

    async def _lock(self):
        client = WyzeLockClient()
        if client.is_locked() is True:
            self._log("already locked")
            await self.capability_worker.speak("Door is already locked.")
            return
        client.lock()
        self._log("lock sent")
        await self.capability_worker.speak("Door locked.")

    async def run(self):
        try:
            msg = await self.capability_worker.wait_for_complete_transcription()
            text = (msg or "").strip().lower()
            self._log("triggered with: %r" % text[:120])

            # Intent dispatch: "lock up" locks; any other trigger unlocks.
            # Lets the unlock trigger be anything the user configures (e.g. "banana").
            if not text:
                self._log("empty transcription, skipping")
            elif "lock up" in text:
                await self._lock()
            else:
                await self._unlock()
        except Exception as e:
            self._log("error: %s" % e)
            try:
                await self.capability_worker.speak("Sorry, the lock command failed.")
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())
