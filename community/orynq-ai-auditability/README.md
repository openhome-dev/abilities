# Orynq AI Auditability

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@flux--point--studios-lightgrey?style=flat-square)
![Type](https://img.shields.io/badge/Type-Background%20Daemon-purple?style=flat-square)
![Cardano](https://img.shields.io/badge/Blockchain-Cardano-blue?style=flat-square)

## What It Does

Creates **tamper-proof audit trails** for every AI conversation, fully passively. Every user and assistant turn is hashed into a rolling SHA-256 chain where modifying any entry invalidates all subsequent hashes — tampering is immediately detectable.

When a Materios gateway Bearer token is configured, the chain is automatically anchored to the **Materios partner chain** every ~90 seconds of new activity, and certified receipts are batched into Cardano mainnet by the Materios anchor worker. **The user takes no action and holds no signing key on the device** — the gateway's sponsored-receipt submitter signs on-chain, and cert-daemon attests availability.

## Category

**Background Daemon.** There are no hotwords and no interactive UI. On session start the daemon begins hashing conversation turns silently; on every new turn it decides whether to anchor (rate-limited to once per minute). `main.py` is a non-functional stub required only to satisfy the OpenHome CLI validator's REQUIRED_FILES check.

## Setup

**Local-only (zero setup).** Install the ability. The hash chain begins populating immediately and persists to user-data storage.

**With on-chain certification (one-time, ~30 seconds):**

1. Get a Materios gateway Bearer token prefixed `matra_…` from the Flux Point Studios operator (or mint your own via the [orynq-sdk](https://github.com/flux-point-studios/orynq-sdk)).
2. In the OpenHome iOS app: **Settings → API Keys → Third-party Keys**, add key name `materios_gateway_api_key` with the `matra_…` value.
3. That's it. The daemon auto-uploads on the next poll cycle.

You can revoke the token at any time; uploads silently fall back to local-only and the local chain keeps growing.

## How It Works

### Capture (always on)
`background.py` runs as a Standalone Background Daemon — a `while True` loop that wakes every `POLL_INTERVAL = 90s` and reads `get_full_message_history()`. Any new entry (user, assistant, tool, or function role; text OR structured content) is canonicalised (sorted-key compact JSON for dicts/lists) and appended to a rolling SHA-256 chain:

```
h_i = SHA256(canonical_json({ seq, role, content_hash, prev, ts }))
content_hash = SHA256(canonical_json(content))   for dict/list content
             = SHA256(raw_text)                  for string content
```

Raw content is **never stored or uploaded** — only per-message SHA-256s and the chain links.

The chain is persisted to `orynq_audit_chain.json` in user-data file storage via a **forward-journal crash-safe pattern** (write `_tmp.json` → readback verify with bounded retry → replace real → delete tmp) since the OpenHome SDK does not expose atomic rename.

At `MAX_ENTRIES_ON_DISK = 10000` a synthetic `compacted_head` record is prepended and older entries dropped. Chain verification still succeeds from the compaction point forward.

### Anchor (passive, rate-limited)
After every poll that grew the chain, `_maybe_auto_anchor()` evaluates four gates in order:

1. **No growth** — skip if `len(chain) <= last_anchored_len`
2. **Rate limit** — skip if last anchor was <60s ago (`AUTO_ANCHOR_MIN_INTERVAL_S`)
3. **Failure backoff** — skip if ≥3 consecutive upload failures and <10min since last failure (`AUTO_ANCHOR_BACKOFF_S`)
4. **API key** — skip if no `materios_gateway_api_key` configured (local-only mode)

If all gates pass, the canonical chain is wrapped as the v2 Materios envelope `{p:"materios", v:2, chain:[...], head:"<hex>"}` and uploaded via the standard two-step manifest-then-chunk protocol to `https://materios.fluxpointstudios.com/preprod-blobs/blobs/{hash}/…`. Auth header is `Authorization: Bearer <matra_...>` (prefix-based; the daemon also supports legacy `x-api-key` for non-Bearer tokens).

### Certify (handled by Materios)
On upload completion the gateway fires a fire-and-forget callback to the sponsored-receipt submitter, which signs `orinqReceipts.submitReceipt` on-chain with the operator keypair. Cert-daemon then indexes the new receipt (within ~6s post-fix, 2026-04-24) and sets `availabilityCertHash` — the receipt is now **CERTIFIED**. The Materios anchor worker batches certified receipts into Cardano mainnet under metadata label **8746**.

## End-to-End Verified on Preprod — 2026-04-24

Deployed as OpenHome ability id **3789** (Background Daemon, agent 578906). Two full cycles captured during a single voice session:

| Turn | Content hash | Receipt ID | Cert hash |
|---|---|---|---|
| Session open | `0xc7a028f0…37de359` | `0xa95eb1d2…778782` | `0xbb5f1a1c11f0231c…` |
| Weather Q&A | `0x2bfad367…aeaf16a7` | `0xa560d10c…df6e7` | `0x7beff7f944bd937b…` |

Zero user action. Zero signing key on the device. `orinq_getReceiptsByContent` confirms both receipts at [materios.fluxpointstudios.com/explorer](https://materios.fluxpointstudios.com/explorer/).

## Privacy

- **Content hashes only.** Raw conversation text never leaves the device.
- **Per-user chains.** Each OpenHome user has their own `orynq_audit_chain.json`; chains are not shared across users.
- **Revocable.** Remove the Bearer token from iOS Settings and the ability drops to local-only mode instantly. The on-disk chain continues to grow but no new on-chain entries are created.
- **No telemetry.** The daemon has no analytics or phone-home beyond the explicit Materios gateway call.

## Diagnostics

The daemon emits verbose per-poll logs via `editor_logging_handler`:

- `[OrynqAudit] poll: hist_len=N seen_prev=M new_msgs=K added=X chain_len=Y` — every poll
- `[OrynqAudit] anchor skip: no_growth|rate_limit|backoff|no_api_key (…)` — every gate miss
- `[OrynqAudit] anchor start: chain_len=N last_len=M` — before upload
- `[OrynqAudit] upload OK hash=<64-hex>` — on success
- `[OrynqAudit] history shrunk, resetting pointer` — if `get_full_message_history()` returns shorter than before

If a capture gap is suspected, these make clear whether the daemon saw new history or which gate blocked the upload.

## Technical Details

- **Architecture:** Pure Background Daemon — no hotwords, no `resume_normal_flow()` in `background.py`.
- **Poll interval:** 90 seconds (`POLL_INTERVAL` in `background.py`)
- **Auto-anchor rate limit:** 60 seconds between uploads (`AUTO_ANCHOR_MIN_INTERVAL_S`)
- **Failure backoff:** 10 minutes after 3 consecutive failures
- **Hash algorithm:** SHA-256 rolling chain; canonical JSON (sorted keys, compact separators) for dict/list content
- **Tamper detection:** `_verify_chain()` replays every link and reports first failing index; tests cover content-hash tamper, previous-hash tamper, and direct chain-hash tamper
- **Compaction:** `MAX_ENTRIES_ON_DISK = 10000` real entries (~4 MB); `compacted_head` marker preserves `prev_head` hash for continuity
- **Persistence:** forward-journal crash-safe writes to `orynq_audit_chain.json` with bounded read-after-write retry (5 attempts, exponential backoff)
- **Wire format:** v2 Materios envelope — `{p:"materios", v:2, chain:[...], head:"<hex>"}`
- **Blockchain:** Cardano mainnet via [Materios](https://docs.fluxpointstudios.com/materios-partner-chain) batched anchoring (metadata label `8746`)
- **Committee:** 10 independent attestors verify data availability before certification
- **Explorer:** [materios.fluxpointstudios.com/explorer](https://materios.fluxpointstudios.com/explorer/)
- **SDK:** [orynq-sdk](https://github.com/flux-point-studios/orynq-sdk)
