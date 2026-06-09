"""HTTP transport: a thin wrapper over ``requests`` with retries and automatic auth.

The key responsibility is :meth:`Transport.request`'s ``auth`` argument, which maps
an endpoint's auth mode to the right credential. For ``"jwt"`` endpoints it uses the
configured JWT as a Bearer token when present (a browser session), otherwise it
authenticates with the api_key via ``X-API-KEY`` — the api_key is never sent as a
Bearer token (the server would reject it via SimpleJWT).
"""

from __future__ import annotations

import random
import time
from typing import Any, Literal

import requests

from .config import Config
from .errors import ApiError, NotAuthenticatedError, SessionExpiredError

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
        return {}

    def _used_jwt(self, auth: AuthMode) -> bool:
        return auth == "jwt" and bool(self.config.jwt)

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
        headers = self._auth_headers(auth)

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
                self._raise_for_response(resp, path, used_jwt=self._used_jwt(auth))

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
    def _raise_for_response(resp: requests.Response, path: str, *, used_jwt: bool) -> None:
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

        raise ApiError(str(resp.status_code), message or "Request failed")
