import asyncio
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

# ── Wyze constants (not credentials) ──
BASE_URL = "https://app.wyzecam.com"
AUTH_URL = "https://auth-prod.api.wyze.com/api/user/login"
SIGNING_SECRET = "wyze_app_secret_key_132"
APP_ID = "9319141212m2ik"
APP_INFO = "wyze_android_3.11.0.758"
APP_VERSION = "3.11.0.758"
TOKEN_TTL_SECONDS = 1800


class WyzlockCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Runtime credential holders (populated in call())
    _email: str = ""
    _password: str = ""
    _key_id: str = ""
    _api_key: str = ""
    _device_mac: str = ""

    # Token cache
    _phone_id: str = ""
    _token_val: str = None
    _token_ts: float = 0.0

    #{{register capability}}

    # ── Logging ───────────────────────────────────────────────────────────────

    def _log(self, msg):
        try:
            self.worker.editor_logging_handler.info("WyzeLock(main): %s" % msg)
        except Exception:
            pass

    # ── Wyze API ──────────────────────────────────────────────────────────────

    def _md5(self, value: str) -> str:
        """MD5 is required by the Wyze IoT3 signing scheme."""
        return hashlib.new("md5", value.encode()).hexdigest()

    def _login_sync(self):
        pw = self._password
        for _ in range(3):
            pw = self._md5(pw)
        resp = requests.post(
            AUTH_URL,
            headers={"keyid": self._key_id, "apikey": self._api_key},
            json={"email": self._email, "password": pw},
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

    def _get_token_sync(self):
        if not self._token_val or (time.time() - self._token_ts) > TOKEN_TTL_SECONDS:
            self._token_val = self._login_sync()
            self._token_ts = time.time()
        return self._token_val

    def _sign(self, token: str, body: str) -> str:
        secret = self._md5(token + SIGNING_SECRET)
        return hmac.new(secret.encode(), body.encode(), lambda: hashlib.new("md5")).hexdigest()

    def _headers(self, token: str, body: str) -> dict:
        return {
            "access_token": token,
            "appid": APP_ID,
            "appinfo": APP_INFO,
            "appversion": APP_VERSION,
            "env": "Prod",
            "phoneid": self._phone_id,
            "requestid": uuid.uuid4().hex,
            "Signature2": self._sign(token, body),
            "Content-Type": "application/json; charset=utf-8",
        }

    def _target(self) -> dict:
        parts = self._device_mac.split("_")
        return {"id": self._device_mac, "model": "_".join(parts[:2])}

    def _call_sync(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload)
        token = self._get_token_sync()
        resp = requests.post(
            f"{BASE_URL}{path}",
            headers=self._headers(token, body),
            data=body,
            timeout=15,
        )
        return resp.json()

    def _get_status_sync(self) -> dict:
        ts = int(time.time() * 1000)
        return self._call_sync("/app/v4/iot3/get-property", {
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

    def _run_action_sync(self, action: str) -> dict:
        ts = int(time.time() * 1000)
        return self._call_sync("/app/v4/iot3/run-action", {
            "nonce": str(ts),
            "payload": {
                "action": f"lock::{action}",
                "cmd": "run_action",
                "params": {
                    "action_id": random.randint(10000, 99999),
                    "type": 1,
                    "username": self._email,
                },
                "tid": random.randint(1000, 99999),
                "ts": ts,
                "ver": 1,
            },
            "targetInfo": self._target(),
        })

    def _is_locked_sync(self):
        """Returns True if locked, False if unlocked, None if unknown."""
        try:
            resp = self._get_status_sync()
            val = resp.get("data", {}).get("props", {}).get("lock::lock-status")
        except Exception:
            return None
        if isinstance(val, bool):
            return val
        return None

    # ── Lock / Unlock ─────────────────────────────────────────────────────────

    async def _unlock(self):
        locked = await asyncio.to_thread(self._is_locked_sync)
        if locked is False:
            self._log("already unlocked")
            await self.capability_worker.speak("Door is already unlocked.")
            return
        await asyncio.to_thread(self._run_action_sync, "unlock")
        self._log("unlock sent")
        await self.capability_worker.speak("Door unlocked.")

    async def _lock(self):
        locked = await asyncio.to_thread(self._is_locked_sync)
        if locked is True:
            self._log("already locked")
            await self.capability_worker.speak("Door is already locked.")
            return
        await asyncio.to_thread(self._run_action_sync, "lock")
        self._log("lock sent")
        await self.capability_worker.speak("Door locked.")

    # ── Main flow ─────────────────────────────────────────────────────────────

    async def run(self):
        try:
            # Load credentials at runtime
            self._email = self.capability_worker.get_api_keys("wyze_email") or ""
            self._password = self.capability_worker.get_api_keys("wyze_password") or ""
            self._key_id = self.capability_worker.get_api_keys("wyze_key_id") or ""
            self._api_key = self.capability_worker.get_api_keys("wyze_api_key") or ""
            self._device_mac = self.capability_worker.get_api_keys("wyze_device_mac") or ""

            # Validate — speak helpful error if anything is missing
            missing = [k for k, v in {
                "wyze_email": self._email,
                "wyze_password": self._password,
                "wyze_key_id": self._key_id,
                "wyze_api_key": self._api_key,
                "wyze_device_mac": self._device_mac,
            }.items() if not v]
            if missing:
                await self.capability_worker.speak(
                    "Wyze is not fully configured. Please add the following in API Keys settings: %s."
                    % ", ".join(missing)
                )
                return

            msg = await self.capability_worker.wait_for_complete_transcription()
            text = (msg or "").strip().lower()
            self._log("triggered with: %r" % text[:120])

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
        self._phone_id = str(uuid.uuid4())
        self._token_val = None
        self._token_ts = 0.0
        self.worker.session_tasks.create(self.run())
