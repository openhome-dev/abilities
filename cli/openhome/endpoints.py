"""Endpoint registry for the OpenHome backend.

Paths are relative to ``Config.api_base`` (REST) or ``Config.ws_base`` (WebSocket).
The ``AUTH`` map records how each endpoint authenticates today, so the transport
layer can pick the right credential automatically. See the README for the full
contract table.
"""

from __future__ import annotations

# Auth modes understood by transport.request():
#   "apikey_body" — api_key passed in the JSON body (the /api/sdk/* endpoints)
#   "xapikey"     — X-API-KEY: <api_key> header
#   "jwt"         — Authorization: Bearer <jwt>, falling back to the api_key
#                   when no jwt is configured (forward-compatible with the
#                   planned backend change to accept the api key here too)
GET_PERSONALITIES = "/api/sdk/get_personalities"
VERIFY_API_KEY = "/api/sdk/verify_apikey"

ADD_CAPABILITY = "/api/capabilities/add-capability/"
LIST_CAPABILITIES = "/api/capabilities/get-all-capabilities/"
LIST_INSTALLED_CAPABILITIES = "/api/capabilities/get-installed-capabilities/"
EDIT_PERSONALITY = "/api/personalities/edit-personality/"
# Batch delete: POST with JSON body {"capability_ids": [<id>, ...]} (JWT auth).
DELETE_CAPABILITY = "/api/capabilities/delete-capability/"


def uninstall_capability(capability_id: str | int) -> str:
    return f"/api/capabilities/uninstall-capability/{capability_id}/"


def edit_installed_capability(capability_id: str | int) -> str:
    return f"/api/capabilities/edit-installed-capability/{capability_id}/"


def download_capability(capability_id: str | int) -> str:
    """Returns the ability's current source as an application/zip (JWT auth)."""
    return f"/api/capabilities/get/template-file/{capability_id}/"


def installed_capability_by_capability(capability_id: str | int) -> str:
    """Installed-capability detail: effective (overridden) trigger words +
    version/release history for a given capability id (JWT auth)."""
    return f"/api/capabilities/get/installed-capability/by-capability/{capability_id}/"


def validate_release_code(release_id: str | int) -> str:
    """In-place update of an existing release's code (JWT auth, multipart, flat zip).
    ``committed=false`` saves a draft; ``committed=true`` + ``commit_message``
    commits a version."""
    return f"/api/capabilities/validate/release-code/{release_id}/"


def voice_stream(api_key: str, agent_id: str) -> str:
    return f"/websocket/voice-stream/{api_key}/{agent_id}"