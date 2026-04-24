import hashlib
import json
import time

import requests  # for fire-and-forget Materios gateway upload from the daemon

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# ORYNQ AI AUDITABILITY — Background Daemon
#
# Passively captures every assistant and user turn into a SHA-256 rolling
# hash chain. Starts on session connect, polls get_full_message_history()
# every POLL_INTERVAL seconds, appends new entries to the chain, and
# persists the chain to a user-data JSON file so it survives session
# restarts. Also auto-uploads the chain to the Materios blob gateway
# after every polling cycle where the chain grew (rate-limited so we
# never post faster than AUTO_ANCHOR_MIN_INTERVAL_S per anchor). The
# gateway's sponsored-receipt submitter turns each upload into a
# certified on-chain receipt (Flux-Point-Studios/orynq-sdk PR #8 + the
# submitter service shipped 2026-04-23).
#
# No speaking, no user interaction, no prompts — this is pure silent
# capture + silent anchor. The interactive trigger handler (main.py)
# provides STATUS / VERIFY / ANCHOR_NOW for humans who want to query.
#
# Chain recurrence (per message):
#     h_i = SHA256( canonical_json( { seq, role, content_hash, prev, ts } ) )
# where content_hash = SHA256(content). Raw content is never stored or
# uploaded — only hashes. This is the privacy guarantee.
# =============================================================================

CHAIN_FILE = "orynq_audit_chain.json"
CHAIN_TMP_FILE = "orynq_audit_chain_tmp.json"   # journal file for crash-safe writes — must end in .json because the SDK's write_file appears to silently drop writes to unknown extensions (observed on DevKit 2026-04-23)
POLL_INTERVAL = 90.0            # seconds between polls (reviewer suggested 60-90)
SAVE_EVERY_N_POLLS = 10         # flush to disk at least every N polls even if nothing changed
ZERO_HASH = "0" * 64            # genesis prev-hash

# Auto-anchor config
MATERIOS_GATEWAY_URL = "https://materios.fluxpointstudios.com/preprod-blobs/blobs"
MATERIOS_GATEWAY_API_KEY_NAME = "materios_gateway_api_key"
AUTO_ANCHOR_MIN_INTERVAL_S = 60            # don't re-anchor faster than this
AUTO_ANCHOR_MAX_CONSECUTIVE_FAILURES = 3    # count before entering backoff
AUTO_ANCHOR_BACKOFF_S = 600                 # wait this long after N failures
AUTO_ANCHOR_HTTP_TIMEOUT_S = 30             # per HTTP call

# Rolling-window cap for on-disk history. When the number of real entries
# exceeds this, we compact by dropping the oldest entries and prepending a
# synthetic `compacted_head` marker so the chain stays linkable. The head
# hash is unchanged because every retained entry's `previous_hash` still
# chains backward correctly; only the ability to replay from genesis is
# lost. 10000 entries at ~400 bytes per entry ≈ 4 MB on disk, which covers
# many sessions of dense use before any compaction fires.
MAX_ENTRIES_ON_DISK = 10000


def _apply_gateway_auth(headers: dict, api_key: str) -> None:
    """Route the Materios gateway API key to the right header by shape.

    Post-PR-#6/#7 Bearer tokens live in Authorization; legacy per-operator
    keys (random hex or SS58 address) stay on x-api-key during the
    coexistence window. Duplicated here (and in main.py) because the
    OpenHome sandbox doesn't allow cross-file imports between ability
    files.
    """
    if not api_key:
        return
    if api_key.startswith("matra_"):
        headers["Authorization"] = "Bearer " + api_key
    else:
        headers["x-api-key"] = api_key


def _canonical_json(obj) -> str:
    """Deterministic JSON encoding used for hash inputs."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_str(data: str) -> str:
    return _hash_bytes(data.encode("utf-8"))


def _new_state() -> dict:
    """Mutable state held as a local dict (Pydantic blocks arbitrary self.*)."""
    return {
        "last_seen_index": 0,
        "chain": [],          # list of entry dicts
        "head": ZERO_HASH,    # current chain head (last entry's chain_hash)
        "last_anchor": None,  # {content_hash, status, sponsored, ts} or None
        "consent_granted_until": 0,  # epoch seconds; 0 = require consent each anchor
        "polls_since_save": 0,
    }


def _build_entry(role: str, content: str, prev: str, seq: int) -> dict:
    """Build one rolling-hash entry. Raw content is NOT stored — only its SHA-256."""
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    content_hash = _hash_str(content or "")
    payload = {
        "seq": seq,
        "role": role,
        "content_hash": content_hash,
        "prev": prev,
        "ts": timestamp,
    }
    chain_hash = _hash_str(_canonical_json(payload))
    return {
        "seq": seq,
        "role": role,
        "content_hash": content_hash,
        "chain_hash": chain_hash,
        "previous_hash": prev,
        "timestamp": timestamp,
    }


def _is_compacted_head(entry) -> bool:
    """True if entry is a synthetic compacted-head marker, not a real hash entry."""
    return isinstance(entry, dict) and entry.get("type") == "compacted_head"


def _split_chain(chain: list):
    """Separate the compacted_head marker (if any) from real hash entries.

    Returns ``(marker_or_None, real_entries)``. Duplicate of main.py's
    helper (cross-ability-file imports aren't supported by the OpenHome
    sandbox, and we need this locally for _build_trace_blob).
    """
    if chain and _is_compacted_head(chain[0]):
        return chain[0], chain[1:]
    return None, list(chain or [])


def _compact_if_needed(state: dict) -> None:
    """Enforce MAX_ENTRIES_ON_DISK by prepending a synthetic compacted_head.

    Mutates `state["chain"]` in place. The chain head (state["head"]) is
    unchanged — every retained entry's `previous_hash` still chains
    backward correctly; only the ability to replay from genesis is lost.
    The compacted_head record preserves the hash of the last discarded
    entry so external verifiers can confirm continuity from the
    compaction point forward.
    """
    chain = state.get("chain", []) or []
    # Only real entries count against the cap; an existing compacted_head
    # marker from a previous compaction sits at index 0 and is free.
    has_marker = bool(chain) and _is_compacted_head(chain[0])
    real_count = len(chain) - (1 if has_marker else 0)
    if real_count <= MAX_ENTRIES_ON_DISK:
        return

    real_entries = chain[1:] if has_marker else chain
    keep = real_entries[-MAX_ENTRIES_ON_DISK:]
    dropped = real_entries[:-MAX_ENTRIES_ON_DISK]

    # prev_head is the chain_hash of the last discarded entry — which is
    # exactly what keep[0]["previous_hash"] already points to.
    prev_head = dropped[-1]["chain_hash"] if dropped else ZERO_HASH

    # Accumulate across prior compactions.
    prior_compacted = int(chain[0].get("entries_compacted", 0)) if has_marker else 0

    marker = {
        "type": "compacted_head",
        "prev_head": prev_head,
        "entries_compacted": prior_compacted + len(dropped),
        "compacted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    state["chain"] = [marker] + keep


def _verify_chain(chain: list) -> dict:
    """Replay every hash link. Returns
    ``{"ok": bool, "checked": int, "error": str|None, "partial": bool}``.
    ``partial`` is True when history was compacted — replay starts from
    the compacted_head's ``prev_head`` rather than genesis.
    """
    marker, entries = _split_chain(chain)
    partial = marker is not None
    expected_prev = marker.get("prev_head", ZERO_HASH) if marker else ZERO_HASH

    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            return {"ok": False, "checked": i, "error": "non-dict entry",
                    "partial": partial}
        prev = entry.get("previous_hash")
        if prev != expected_prev:
            return {"ok": False, "checked": i,
                    "error": "previous_hash mismatch at index " + str(i),
                    "partial": partial}
        payload = {
            "seq": entry.get("seq"),
            "role": entry.get("role"),
            "content_hash": entry.get("content_hash"),
            "prev": prev,
            "ts": entry.get("timestamp"),
        }
        recomputed = _hash_str(_canonical_json(payload))
        if recomputed != entry.get("chain_hash"):
            return {"ok": False, "checked": i,
                    "error": "chain_hash mismatch at index " + str(i),
                    "partial": partial}
        expected_prev = entry["chain_hash"]

    return {"ok": True, "checked": len(entries), "error": None,
            "partial": partial}


class OrynqAuditabilityBackground(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    background_daemon_mode: bool = False

    # Do not change following tag of register capability
    # {{register_capability}}

    # ------------------------------------------------------------------
    # File I/O — crash-safe journal + recover-on-startup pattern
    #
    # The OpenHome SDK exposes `check_if_file_exists`, `read_file`,
    # `write_file` (mode "a+" default, or "w"), and `delete_file`. It does
    # NOT expose an atomic rename / replace primitive, so a delete-then-
    # write on the real chain file is not crash-safe: a power loss between
    # delete and write wipes the audit chain. We work around that by
    # treating `orynq_audit_chain.json.tmp` as a write-ahead journal:
    #
    #   save:
    #     1. write candidate contents to .tmp (mode="w", then read back to
    #        verify it round-trips and parses as valid JSON)
    #     2. delete real file
    #     3. write real file (mode="w")
    #     4. delete .tmp
    #
    #   load:
    #     - if real file is valid, use it (and clean up any stale .tmp)
    #     - if real file is missing/corrupt but .tmp is valid, recover
    #       from .tmp; the crash happened between step 2 and step 3, and
    #       the .tmp is authoritative
    #
    # This is not as strong as a true atomic rename — a crash between the
    # recover-read and the next save can still drop one batch of writes —
    # but it is strictly better than the previous delete-then-write,
    # which had a crash window that destroyed the entire audit chain.
    # ------------------------------------------------------------------

    async def _read_json_file(self, filename: str):
        """Return parsed JSON from filename, or None on any error."""
        try:
            exists = await self.capability_worker.check_if_file_exists(filename, False)
            if not exists:
                return None
            raw = await self.capability_worker.read_file(filename, False)
            if not raw or not raw.strip():
                return None
            return json.loads(raw)
        except Exception:
            return None

    async def _load_state(self) -> dict:
        try:
            data = await self._read_json_file(CHAIN_FILE)
            tmp_data = await self._read_json_file(CHAIN_TMP_FILE)

            # Recovery: real file is missing/corrupt but journal is valid.
            if data is None and tmp_data is not None:
                self.worker.editor_logging_handler.info(
                    "[OrynqAudit] recovered chain from "
                    + CHAIN_TMP_FILE + " (real file missing/corrupt)"
                )
                data = tmp_data
                # Promote the journal to the real file so subsequent reads
                # see the recovered copy even if we crash again before the
                # next scheduled save.
                try:
                    await self.capability_worker.write_file(
                        CHAIN_FILE, json.dumps(data, indent=2), False
                    )
                    tmp_still_there = await self.capability_worker.check_if_file_exists(
                        CHAIN_TMP_FILE, False
                    )
                    if tmp_still_there:
                        await self.capability_worker.delete_file(CHAIN_TMP_FILE, False)
                except Exception as promo_err:
                    # Recovery read still succeeded; a promotion failure is
                    # non-fatal — we'll try again on the next save.
                    self.worker.editor_logging_handler.error(
                        "[OrynqAudit] tmp promotion failed: " + str(promo_err)
                    )
            elif data is not None and tmp_data is not None:
                # Both present means a crash happened after the real file
                # was rewritten but before the journal was cleaned up. The
                # real file is authoritative — drop the stale journal.
                try:
                    await self.capability_worker.delete_file(CHAIN_TMP_FILE, False)
                except Exception:
                    pass

            if data is None:
                return _new_state()

            state = _new_state()
            state.update({
                "last_seen_index": int(data.get("last_seen_index", 0)),
                "chain": data.get("chain", []) or [],
                "head": data.get("head", ZERO_HASH),
                "last_anchor": data.get("last_anchor"),
                "consent_granted_until": int(data.get("consent_granted_until", 0) or 0),
            })
            return state
        except Exception as e:
            self.worker.editor_logging_handler.error(
                "[OrynqAudit] Load error: " + str(e)
            )
            return _new_state()

    async def _save_state(self, state: dict):
        """Persist current chain + metadata using the write-ahead journal.

        The OpenHome SDK has no atomic rename, so we write to the journal
        first, verify it round-trips, then overwrite the real file. A
        crash mid-save leaves the journal (which `_load_state` uses to
        recover) rather than destroying the whole chain.
        """
        # Enforce the rolling-window cap before writing anything.
        _compact_if_needed(state)

        data = {
            "last_seen_index": state["last_seen_index"],
            "chain": state["chain"],
            "head": state["head"],
            "last_anchor": state["last_anchor"],
            "consent_granted_until": state["consent_granted_until"],
            "chain_length": len(state["chain"]),
            "updated_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        serialized = json.dumps(data, indent=2)

        try:
            # Step 1: write candidate contents to the journal.
            # Using the SDK's default write mode (a+ per its docs). Earlier
            # versions of this code passed mode="w" explicitly, but on the
            # real DevKit we observed that write_file(mode="w") followed by
            # an immediate read_file returns empty even with bounded retries
            # over a 750ms window — suggesting the "w" mode either is not
            # routed to the same backend path as reads, or silently drops
            # the write. Default mode after a delete_file behaves
            # identically to a clean overwrite for our purposes.
            pre_tmp_exists = await self.capability_worker.check_if_file_exists(CHAIN_TMP_FILE, False)
            if pre_tmp_exists:
                await self.capability_worker.delete_file(CHAIN_TMP_FILE, False)
            self.worker.editor_logging_handler.info(
                "[OrynqAudit] save: writing .tmp (" + str(len(serialized)) + " bytes)"
            )
            await self.capability_worker.write_file(CHAIN_TMP_FILE, serialized, False)

            # Step 2: verify by reading back — with bounded retries because
            # even with the default mode we cannot assume strict read-after-
            # write ordering on the cloud file backend. 5 attempts with
            # exponential backoff give a 750ms settling window.
            verify_raw = None
            got_bytes = 0
            tmp_exists_after_write = await self.capability_worker.check_if_file_exists(
                CHAIN_TMP_FILE, False
            )
            self.worker.editor_logging_handler.info(
                "[OrynqAudit] save: .tmp exists after write = "
                + str(bool(tmp_exists_after_write))
            )
            for attempt in range(5):
                if attempt > 0:
                    await self.worker.session_tasks.sleep(0.05 * (2 ** (attempt - 1)))
                verify_raw = await self.capability_worker.read_file(CHAIN_TMP_FILE, False)
                got_bytes = len(verify_raw) if verify_raw else 0
                self.worker.editor_logging_handler.info(
                    "[OrynqAudit] save: verify attempt " + str(attempt)
                    + " got " + str(got_bytes) + " bytes"
                )
                if verify_raw and got_bytes == len(serialized):
                    break
            else:
                raise IOError(
                    "journal verify failed after 5 attempts (expected "
                    + str(len(serialized)) + " bytes, got "
                    + str(got_bytes) + ")"
                )
            # Parse check — if this throws, we never promote to real.
            json.loads(verify_raw)

            # Step 3: delete real, write real.
            if await self.capability_worker.check_if_file_exists(CHAIN_FILE, False):
                await self.capability_worker.delete_file(CHAIN_FILE, False)
            await self.capability_worker.write_file(CHAIN_FILE, serialized, False)

            # Step 4: clean up the journal.
            if await self.capability_worker.check_if_file_exists(CHAIN_TMP_FILE, False):
                await self.capability_worker.delete_file(CHAIN_TMP_FILE, False)
            self.worker.editor_logging_handler.info(
                "[OrynqAudit] save: success (chain_len=" + str(len(state["chain"])) + ")"
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                "[OrynqAudit] Save error: " + str(e)
            )

    # ------------------------------------------------------------------
    # Chain extension
    # ------------------------------------------------------------------

    def _extend_chain(self, state: dict, new_messages: list) -> int:
        """Append hash entries for each new message. Returns number appended."""
        added = 0
        # Determine the next sequence number. Using len(chain) would
        # collide with existing seqs once compaction has prepended a
        # synthetic marker or trimmed older entries, so we walk backward
        # to find the highest real seq and continue from there.
        next_seq = 0
        for existing in reversed(state["chain"]):
            if _is_compacted_head(existing):
                continue
            next_seq = int(existing.get("seq", -1)) + 1
            break

        for msg in new_messages:
            role = msg.get("role", "")
            if not role:
                # No label, no audit value. Skip.
                continue

            content = msg.get("content", "")

            # Normalize the content into a single string we can hash
            # deterministically. Strings pass through unchanged (so chains
            # built under the previous code still verify). Dicts / lists /
            # numbers / bools / null go through canonical JSON with sorted
            # keys — that guarantees the same tool-call produces the same
            # content_hash regardless of dict insertion order.
            if isinstance(content, str):
                normalized = content.strip()
                if not normalized:
                    continue
            else:
                try:
                    normalized = _canonical_json(content)
                except (TypeError, ValueError) as e:
                    # bytes, sets, non-string dict keys, custom classes, etc.
                    # Log and move on — the audit guarantee is "if it hashed,
                    # it's in the chain"; unhashable events are beyond scope.
                    self.worker.editor_logging_handler.warning(
                        "[OrynqAudit] skipping unserializable content for role "
                        + str(role) + ": " + str(e)
                    )
                    continue
                # Empty containers or null — no information to anchor.
                if normalized in ("", "{}", "[]", "null"):
                    continue

            entry = _build_entry(role, normalized, state["head"], next_seq)
            state["chain"].append(entry)
            state["head"] = entry["chain_hash"]
            next_seq += 1
            added += 1
        return added

    # ------------------------------------------------------------------
    # Watch loop — silent, no speaking
    # ------------------------------------------------------------------

    async def watch_loop(self):
        self.worker.editor_logging_handler.info(
            "[OrynqAudit] daemon started — silent capture every "
            + str(int(POLL_INTERVAL)) + "s"
        )

        state = await self._load_state()

        while True:
            try:
                history = self.capability_worker.get_full_message_history() or []
                current_length = len(history)
                prev_seen = state["last_seen_index"]

                # Pointer hygiene — if history was rewritten or trimmed, back off
                if state["last_seen_index"] > current_length:
                    self.worker.editor_logging_handler.info(
                        "[OrynqAudit] history shrunk, resetting pointer"
                    )
                    state["last_seen_index"] = current_length

                new_messages = history[state["last_seen_index"]:]
                state["last_seen_index"] = current_length

                added = self._extend_chain(state, new_messages)

                state["polls_since_save"] = state.get("polls_since_save", 0) + 1

                self.worker.editor_logging_handler.info(
                    "[OrynqAudit] poll: hist_len=" + str(current_length)
                    + " seen_prev=" + str(prev_seen)
                    + " new_msgs=" + str(len(new_messages))
                    + " added=" + str(added)
                    + " chain_len=" + str(len(state.get("chain", [])))
                )

                if added > 0:
                    self.worker.editor_logging_handler.info(
                        "[OrynqAudit] +" + str(added) + " entries, chain length="
                        + str(len(state["chain"])) + ", head=" + state["head"][:16]
                    )
                    await self._save_state(state)
                    state["polls_since_save"] = 0
                elif state["polls_since_save"] >= SAVE_EVERY_N_POLLS:
                    # Periodic flush catches consent TTL expiry / pointer updates
                    await self._save_state(state)
                    state["polls_since_save"] = 0

                # Passive on-chain anchoring. No-op if nothing new since
                # last anchor, if within the rate-limit window, if no
                # API key is configured, or if we're in post-failure
                # backoff. Never speaks.
                await self._maybe_auto_anchor(state)

            except Exception as e:
                self.worker.editor_logging_handler.error(
                    "[OrynqAudit] loop error: " + str(e)
                )

            await self.worker.session_tasks.sleep(POLL_INTERVAL)

    # ------------------------------------------------------------------
    # Auto-anchor — called from watch_loop after every poll
    # ------------------------------------------------------------------

    # HTTP seam — the test suite overrides ``_http`` with an in-memory
    # fake boundary. Production binds to the real ``requests`` module.
    _http = requests

    def _get_gateway_api_key(self) -> str:
        """Read the user-configured Materios gateway API key at runtime.

        Values are stored per-user via iOS Settings → API Keys →
        Third-party Keys. Returns empty string when unset — the caller
        falls back to a local-only audit trail (chain keeps growing; no
        on-chain anchor).
        """
        try:
            value = self.capability_worker.get_api_keys(
                MATERIOS_GATEWAY_API_KEY_NAME
            )
        except Exception as e:
            self.worker.editor_logging_handler.warning(
                "[OrynqAudit] get_api_keys error: " + str(e)
            )
            return ""
        return str(value or "")

    def _build_trace_blob(self, chain: list) -> bytes:
        """Wire format for the gateway upload. Same schema as main.py's
        _build_trace_blob (Materios cert-daemon indexes under label
        8746). The compacted_head marker (if present) is stripped out
        of ``chain`` and surfaced as an additive top-level field so
        v2-only consumers ignore it and compaction-aware consumers know
        replay from genesis is not possible.
        """
        marker, real_entries = _split_chain(chain)
        head = real_entries[-1]["chain_hash"] if real_entries else ZERO_HASH
        envelope = {
            "p": "materios",
            "v": 2,
            "chain": real_entries,
            "head": head,
        }
        if marker is not None:
            envelope["compacted_head"] = marker
        return _canonical_json(envelope).encode("utf-8")

    def _upload_chain_to_materios(self, chain: list, api_key: str):
        """Two-step manifest POST + chunk PUT. Returns a dict on success
        or None on failure. Never speaks. All exceptions are caught and
        turned into logged warnings.
        """
        try:
            content = self._build_trace_blob(chain)
            content_hash = hashlib.sha256(content).hexdigest()

            headers = {"Content-Type": "application/json"}
            _apply_gateway_auth(headers, api_key)
            manifest = {
                "chunks": [{"index": 0, "sha256": content_hash, "size": len(content)}],
                "total_size": len(content),
            }
            manifest_resp = self._http.post(
                MATERIOS_GATEWAY_URL + "/" + content_hash + "/manifest",
                headers=headers,
                json=manifest,
                timeout=AUTO_ANCHOR_HTTP_TIMEOUT_S,
            )
            if manifest_resp.status_code not in (200, 201, 409):
                self.worker.editor_logging_handler.error(
                    "[OrynqAudit] auto-anchor manifest failed: "
                    + str(manifest_resp.status_code)
                )
                return None

            chunk_headers = {"Content-Type": "application/octet-stream"}
            _apply_gateway_auth(chunk_headers, api_key)
            chunk_resp = self._http.put(
                MATERIOS_GATEWAY_URL + "/" + content_hash + "/chunks/0",
                headers=chunk_headers,
                data=content,
                timeout=AUTO_ANCHOR_HTTP_TIMEOUT_S,
            )
            if chunk_resp.status_code not in (200, 201, 409):
                self.worker.editor_logging_handler.error(
                    "[OrynqAudit] auto-anchor chunk failed: "
                    + str(chunk_resp.status_code)
                )
                return None

            now_epoch = int(time.time())
            self.worker.editor_logging_handler.info(
                "[OrynqAudit] auto-anchor OK hash=" + content_hash
                + " chain_len=" + str(len(chain))
                + " size=" + str(len(content))
            )
            return {
                "content_hash": content_hash,
                "chain_len": len(chain),
                "size_bytes": len(content),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_epoch)),
                "ts_epoch": now_epoch,
                "sponsored": bool(api_key),
            }
        except Exception as e:
            self.worker.editor_logging_handler.error(
                "[OrynqAudit] auto-anchor exception: " + str(e)
            )
            return None

    async def _maybe_auto_anchor(self, state: dict) -> None:
        """Conditional fire-and-forget anchor. Gates (in order):
          1. Skip if no new entries since last anchor.
          2. Skip if within AUTO_ANCHOR_MIN_INTERVAL_S of last anchor.
          3. Skip if in post-failure backoff window.
          4. Skip if no Materios gateway API key configured (local-only
             mode — the chain keeps growing on disk regardless).

        On success, updates state.last_anchor and resets the failure
        counter, then persists via _save_state. On failure, increments
        the counter and stamps last_upload_failure_at so subsequent
        ticks can evaluate the backoff gate.
        """
        chain = state.get("chain", []) or []
        current_len = len(chain)
        last_anchor = state.get("last_anchor") or {}
        last_len = int(last_anchor.get("chain_len") or 0)
        last_ts_epoch = int(last_anchor.get("ts_epoch") or 0)
        now = int(time.time())

        # Gate 1: no growth
        if current_len <= last_len:
            self.worker.editor_logging_handler.info(
                "[OrynqAudit] anchor skip: no_growth (chain=" + str(current_len)
                + " last=" + str(last_len) + ")"
            )
            return

        # Gate 2: rate limit
        if last_ts_epoch and (now - last_ts_epoch) < AUTO_ANCHOR_MIN_INTERVAL_S:
            self.worker.editor_logging_handler.info(
                "[OrynqAudit] anchor skip: rate_limit (age="
                + str(now - last_ts_epoch) + "s < "
                + str(AUTO_ANCHOR_MIN_INTERVAL_S) + "s)"
            )
            return

        # Gate 3: backoff
        consec_failures = int(state.get("upload_consec_failures") or 0)
        if consec_failures >= AUTO_ANCHOR_MAX_CONSECUTIVE_FAILURES:
            last_fail = int(state.get("last_upload_failure_at") or 0)
            if (now - last_fail) < AUTO_ANCHOR_BACKOFF_S:
                self.worker.editor_logging_handler.info(
                    "[OrynqAudit] anchor skip: backoff (failures="
                    + str(consec_failures) + " age=" + str(now - last_fail) + "s)"
                )
                return

        # Gate 4: API key present
        api_key = self._get_gateway_api_key()
        if not api_key:
            self.worker.editor_logging_handler.info(
                "[OrynqAudit] anchor skip: no_api_key (local-only mode)"
            )
            return

        # Upload and persist.
        self.worker.editor_logging_handler.info(
            "[OrynqAudit] anchor start: chain_len=" + str(current_len)
            + " last_len=" + str(last_len)
        )
        result = self._upload_chain_to_materios(chain, api_key)
        if result is not None:
            state["last_anchor"] = result
            state["upload_consec_failures"] = 0
        else:
            state["upload_consec_failures"] = consec_failures + 1
            state["last_upload_failure_at"] = now

        await self._save_state(state)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def call(self, worker: AgentWorker, background_daemon_mode: bool):
        self.worker = worker
        self.background_daemon_mode = background_daemon_mode
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.editor_logging_handler.info(
            "[OrynqAudit] background.py call() — launching watch_loop"
        )
        self.worker.session_tasks.create(self.watch_loop())
