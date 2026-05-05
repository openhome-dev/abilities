import asyncio
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

# ── Wyze constants (not credentials) ──
BASE_URL = "https://app.wyzecam.com"
AUTH_URL = "https://auth-prod.api.wyze.com/api/user/login"
SIGNING_SECRET = "wyze_app_secret_key_132"
APP_ID = "9319141212m2ik"
APP_INFO = "wyze_android_3.11.0.758"
APP_VERSION = "3.11.0.758"
TOKEN_TTL_SECONDS = 1800

# ── Daemon tunables ──
POLL_SECONDS = 4.0
STARTUP_GRACE_SEC = 60.0
SEEN_SID_CAP = 500

# ── Password config defaults ──
PREFS_FILENAME = "lockpreferences.json"
DEFAULT_UNLOCK_PASSWORD = "open up"
DEFAULT_LOCK_PASSWORD = "lock up"


class WyzlockCapabilityBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # Runtime credential holders (populated in call())
    _email: str = ""
    _password: str = ""
    _key_id: str = ""
    _api_key: str = ""
    _device_mac: str = ""
    _twilio_account_sid: str = ""
    _twilio_auth_token: str = ""
    _twilio_sandbox_whatsapp: str = ""
    _allowed_whatsapp_sender: str = ""
    _twilio_messages_url: str = ""

    # Token cache
    _phone_id: str = ""
    _token_val: str = None
    _token_ts: float = 0.0

    # {{register capability}}

    # ── Logging ───────────────────────────────────────────────────────────────

    def _log(self, msg):
        try:
            self.worker.editor_logging_handler.info("TwilioLock: %s" % msg)
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

    # ── Twilio helpers ────────────────────────────────────────────────────────

    def _fetch_recent_messages_sync(self):
        """Fetch the most recent inbound WhatsApp messages from the allowed sender."""
        try:
            resp = requests.get(
                self._twilio_messages_url,
                params={
                    "From": self._allowed_whatsapp_sender,
                    "To": self._twilio_sandbox_whatsapp,
                    "PageSize": "10",
                },
                auth=(self._twilio_account_sid, self._twilio_auth_token),
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

    def _reply_sync(self, body: str):
        try:
            requests.post(
                self._twilio_messages_url,
                data={
                    "From": self._twilio_sandbox_whatsapp,
                    "To": self._allowed_whatsapp_sender,
                    "Body": body,
                },
                auth=(self._twilio_account_sid, self._twilio_auth_token),
                timeout=15,
            )
        except Exception as e:
            self._log("reply err: %s" % e)

    def _unlock_sync(self):
        try:
            locked = self._is_locked_sync()
            if locked is False:
                self._log("already unlocked")
                self._reply_sync("Door is already unlocked.")
                return
            self._run_action_sync("unlock")
            self._log("unlock sent")
            self._reply_sync("Door unlocked.")
        except Exception as e:
            self._log("unlock failed: %s" % e)
            self._reply_sync("Sorry, unlock failed.")

    def _lock_sync(self):
        try:
            locked = self._is_locked_sync()
            if locked is True:
                self._log("already locked")
                self._reply_sync("Door is already locked.")
                return
            self._run_action_sync("lock")
            self._log("lock sent")
            self._reply_sync("Door locked.")
        except Exception as e:
            self._log("lock failed: %s" % e)
            self._reply_sync("Sorry, lock failed.")

    # ── Prefs ─────────────────────────────────────────────────────────────────

    async def _load_passwords(self):
        """Read passwords from lockpreferences.json in the ability bundle."""
        unlock_pw = DEFAULT_UNLOCK_PASSWORD
        lock_pw = DEFAULT_LOCK_PASSWORD
        try:
            exists = await self.capability_worker.check_if_file_exists(PREFS_FILENAME, in_ability_directory=True)
            if not exists:
                self._log("prefs file not found, using defaults")
                return unlock_pw.lower(), lock_pw.lower()
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

    # ── Watcher loop ──────────────────────────────────────────────────────────

    async def _watcher_loop(self):
        self._log("watcher started")

        # Load credentials at runtime
        self._email = self.capability_worker.get_api_keys("wyze_email") or ""
        self._password = self.capability_worker.get_api_keys("wyze_password") or ""
        self._key_id = self.capability_worker.get_api_keys("wyze_key_id") or ""
        self._api_key = self.capability_worker.get_api_keys("wyze_api_key") or ""
        self._device_mac = self.capability_worker.get_api_keys("wyze_device_mac") or ""
        self._twilio_account_sid = self.capability_worker.get_api_keys("twilio_account_sid") or ""
        self._twilio_auth_token = self.capability_worker.get_api_keys("twilio_auth_token") or ""
        self._twilio_sandbox_whatsapp = self.capability_worker.get_api_keys("twilio_sandbox_whatsapp") or ""
        self._allowed_whatsapp_sender = self.capability_worker.get_api_keys("twilio_allowed_sender") or ""
        self._twilio_messages_url = (
            "https://api.twilio.com/2010-04-01/Accounts/%s/Messages.json" % self._twilio_account_sid
        )

        # Validate Wyze credentials
        missing_wyze = [k for k, v in {
            "wyze_email": self._email,
            "wyze_password": self._password,
            "wyze_key_id": self._key_id,
            "wyze_api_key": self._api_key,
            "wyze_device_mac": self._device_mac,
        }.items() if not v]
        if missing_wyze:
            self._log("Wyze credentials missing, daemon will not start: %s" % ", ".join(missing_wyze))
            return

        # Validate Twilio credentials
        missing_twilio = [k for k, v in {
            "twilio_account_sid": self._twilio_account_sid,
            "twilio_auth_token": self._twilio_auth_token,
            "twilio_sandbox_whatsapp": self._twilio_sandbox_whatsapp,
            "twilio_allowed_sender": self._allowed_whatsapp_sender,
        }.items() if not v]
        if missing_twilio:
            self._log("Twilio credentials missing, daemon will not start: %s" % ", ".join(missing_twilio))
            return
        unlock_pw, lock_pw = await self._load_passwords()
        self._log("passwords loaded (unlock=%d chars, lock=%d chars)" % (len(unlock_pw), len(lock_pw)))
        min_epoch = time.time() - STARTUP_GRACE_SEC
        seen_sids = set()

        while True:
            try:
                messages = await asyncio.to_thread(self._fetch_recent_messages_sync)
                messages.sort(key=lambda m: m.get("date_sent") or "")

                for m in messages:
                    sid = m.get("sid")
                    if not sid or sid in seen_sids:
                        continue

                    if str(m.get("direction", "")).lower() != "inbound":
                        seen_sids.add(sid)
                        continue

                    if str(m.get("from", "")) != self._allowed_whatsapp_sender:
                        seen_sids.add(sid)
                        continue

                    msg_epoch = _twilio_date_to_epoch(m.get("date_sent", ""))
                    if msg_epoch is not None and msg_epoch < min_epoch:
                        seen_sids.add(sid)
                        continue

                    seen_sids.add(sid)
                    body = (m.get("body") or "").strip().lower()
                    if not body:
                        continue

                    self._log("msg sid=%s body=%r" % (sid[:10], body[:80]))

                    if lock_pw and lock_pw in body:
                        await asyncio.to_thread(self._lock_sync)
                    elif unlock_pw and unlock_pw in body:
                        await asyncio.to_thread(self._unlock_sync)
                    else:
                        self._log("no password match, ignoring")

                if len(seen_sids) > SEEN_SID_CAP:
                    seen_sids = set(list(seen_sids)[-(SEEN_SID_CAP // 2):])

            except Exception as e:
                self._log("loop err: %s" % e)

            await self.worker.session_tasks.sleep(POLL_SECONDS)

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.background_daemon_mode = background_daemon_mode
        self.capability_worker = CapabilityWorker(self)
        self._phone_id = str(uuid.uuid4())
        self._token_val = None
        self._token_ts = 0.0
        self.worker.session_tasks.create(self._watcher_loop())


def _twilio_date_to_epoch(s):
    try:
        return parsedate_to_datetime(s).timestamp()
    except Exception:
        return None
