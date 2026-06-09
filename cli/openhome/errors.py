"""Exception hierarchy for the OpenHome client."""

from __future__ import annotations


class OpenHomeError(Exception):
    """Base class for every error raised by this package."""


class NotAuthenticatedError(OpenHomeError):
    """No usable credentials were found for the requested operation."""


class SessionExpiredError(OpenHomeError):
    """The JWT session token is expired or invalid — re-grab it from the browser."""

    def __init__(self, message: str = "Session token expired or invalid"):
        super().__init__(message)


class ApiError(OpenHomeError):
    """A non-2xx HTTP response from the OpenHome API."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.details = details or {}
