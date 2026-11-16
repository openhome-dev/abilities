"""HTTP transport: a thin wrapper over ``requests`` with retries and automatic auth.

The key responsibility is :meth:`Transport.request`'s ``auth`` argument, which maps
an endpoint's auth mode to the right credential. For ``"jwt"`` endpoints it uses the
configured JWT as a Bearer token when present (a browser session), otherwise it
authenticates with the api_key via ``X-API-KEY`` — the api_key is never sent as a
Bearer token (the server would reject it via SimpleJWT).

Whenever the api_key is sent, this terminal's CLI session id goes with it as
``X-Session-Id``, so logging the terminal out from the dashboard stops it.
"""

from __future__ import annotations

import platform
import random
import time
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Literal

import requests

from . import endpoints
from .config import Config
from .errors import (
    ApiError,
    NotAuthenticatedError,
    OpenHomeError,
    SessionExpiredError,
    SessionRevokedError,
)

AuthMode = Literal["apikey_body", "xapikey", "jwt"]

_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3
_BASE_DELAY = 1.0
_MAX_DELAY = 10.0
_DEFAULT_TIMEOUT = 30.0

_SESSION_EXPIRED_HINTS = (
    "token not valid",
    "token is invalid",
    "not valid for any token",
)


def _user_agent() -> str:
    """Names the CLI session in the dashboard ("CLI on Linux", "CLI on macOS")."""
    try:
        ver = "/" + version("openhome-client")
    except PackageNotFoundError:  # run from a source checkout
        ver = ""
    return f"openhome-cli{ver} ({platform.system()})"


def _retry_delay(attempt: int, retry_after: str | None = None) -> float:
    if retry_after:
        try:
            return min(float(int(retry_after)), 30.0)
        except ValueError:
            pass
    jitter = random.random() * 0.5
    return min(_BASE_DELAY * (2**attempt) + jitter, _MAX_DELAY)


class Transport:
    def __init__(self, config: Config, session: requests.Session | None = None):
        self.config = config
        self._session = session or requests.Session()
        self._user_agent = _user_agent()

    # ── auth ────────────────────────────────────────────────────────────
    def _auth_headers(self, auth: AuthMode) -> dict[str, str]:
        cfg = self.config
        if auth == "xapikey":
            if not cfg.api_key:
                raise NotAuthenticatedError(
                    "This action needs an API key. Set OPENHOME_API_KEY."
                )
            return {"X-API-KEY": cfg.api_key}

        if auth == "jwt":
            # A browser session token goes as Bearer; otherwise authenticate with
            # the api_key via X-API-KEY. The api_key must NOT be sent as a Bearer
            # token — the server runs Bearer through SimpleJWT and rejects it
            # ("token_not_valid"); these endpoints accept X-API-KEY instead.
            if cfg.jwt:
                return {"Authorization": f"Bearer {cfg.jwt}"}
            if cfg.api_key:
                return {"X-API-KEY": cfg.api_key}
            raise NotAuthenticatedError(
                "This action needs an API key (or a JWT session token). "
                "Set OPENHOME_API_KEY."
            )

        # apikey_body — credential travels in the JSON body, no auth header.
        if not cfg.api_key:
            raise NotAuthenticatedError(
                "This action needs an API key. Set OPENHOME_API_KEY."
            )
        return {}

    def _used_jwt(self, auth: AuthMode) -> bool:
        return auth == "jwt" and bool(self.config.jwt)

    def _used_sid(self, auth: AuthMode) -> bool:
        # A browser JWT carries the browser's own session, so no CLI sid with it.
        return bool(self.config.sid) and not self._used_jwt(auth)

    # ── CLI session ─────────────────────────────────────────────────────
    def create_session(self) -> str:
        """Create this terminal's CLI session for the configured api_key.

        Replaces any earlier session from this machine. Raises ``ApiError``
        (403) when the key is wrong or the account is disabled.
        """
        cfg = self.config
        cfg.sid, cfg.needs_session = None, False  # never send a stale sid here
        result = self.request(
            "POST",
            endpoints.CREATE_SESSION,
            auth="apikey_body",
            json={
                "api_key": cfg.api_key,
                "mac_address": cfg.ensure_machine_id(),
                "client_type": "cli",
            },
        )
        sid = result.get("sid") if isinstance(result, dict) else None
        if not sid:
            raise ApiError("bad_response", "OpenHome didn't return a session.")
        cfg.sid = str(sid)
        return cfg.sid

    def _open_saved_session(self) -> None:
        """Give a key saved before sessions existed its session, once.

        Best effort: if it fails, this request goes out on the key alone.
        """
        try:
            self.create_session()
        except OpenHomeError:
            return
        self.config.save_sid()

    # ── request ─────────────────────────────────────────────────────────
    def request(
        self,
        method: str,
        path: str,
        *,
        auth: AuthMode = "apikey_body",
        json: Any = None,
        data: Any = None,
        files: Any = None,
        timeout: float = _DEFAULT_TIMEOUT,
        parse_json: bool = True,
    ) -> Any:
        url = f"{self.config.api_base}{path}"
        if self.config.needs_session and not self._used_jwt(auth):
            self._open_saved_session()
        headers = self._auth_headers(auth)
        headers["User-Agent"] = self._user_agent
        if self._used_sid(auth):
            headers["X-Session-Id"] = self.config.sid

        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            if attempt:
                time.sleep(_retry_delay(attempt))

            try:
                resp = self._session.request(
                    method,
                    url,
                    headers=headers,
                    json=json,
                    data=data,
                    files=files,
                    timeout=timeout,
                )
            except requests.Timeout:
                last_error = ApiError("TIMEOUT", f"Request timed out after {timeout}s")
                continue
            except requests.ConnectionError as exc:
                last_error = ApiError("NETWORK_ERROR", str(exc))
                continue

            if resp.status_code in _RETRYABLE_STATUSES:
                last_error = ApiError(
                    str(resp.status_code), f"Server error {resp.status_code}"
                )
                time.sleep(_retry_delay(attempt, resp.headers.get("Retry-After")))
                continue

            if not resp.ok:
                self._raise_for_response(
                    resp,
                    path,
                    used_jwt=self._used_jwt(auth),
                    used_sid=self.config.sid if self._used_sid(auth) else None,
                )

            if not parse_json:
                return resp.content
            if not resp.content:
                return {}
            try:
                return resp.json()
            except ValueError:
                return {"raw": resp.text}

        raise last_error or ApiError(
            "NETWORK_ERROR", f"Request to {path} failed after {_MAX_ATTEMPTS} attempts"
        )

    @staticmethod
    def _raise_for_response(
        resp: requests.Response,
        path: str,
        *,
        used_jwt: bool,
        used_sid: str | None = None,
    ) -> None:
        body: dict | None = None
        try:
            body = resp.json()
        except ValueError:
            pass

        message = resp.reason
        if isinstance(body, dict):
            message = (
                body.get("detail")
                or (body.get("error") or {}).get("message")
                or message
            )

        lowered = (message or "").lower()
        if used_jwt and (
            resp.status_code == 401 or any(h in lowered for h in _SESSION_EXPIRED_HINTS)
        ):
            raise SessionExpiredError()

        if (
            used_sid
            and resp.status_code == 401
            and isinstance(body, dict)
            and body.get("code") == "session_revoked"
        ):
            raise SessionRevokedError(used_sid)

        raise ApiError(str(resp.status_code), message or "Request failed")
