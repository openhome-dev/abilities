import hashlib
import json
import time
from typing import Optional

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# Orynq AI Auditability Ability
#
# Creates tamper-proof audit trails for AI conversations using Orynq's
# Proof-of-Inference protocol. Builds SHA-256 rolling hash chains that
# are verifiable locally — no blockchain setup required.
#
# Optionally, the hash chain can be anchored to the Materios partner
# chain and then batched into a Cardano mainnet transaction for
# permanent on-chain immutability.
#
# Blockchain anchoring paths:
#   1. Sponsored (API key) — FPS submits the receipt on your behalf
#   2. Permissionless (own wallet) — you submit directly with MATRA
#      tokens from the faucet
# =============================================================================

# --- Materios partner chain configuration ---
MATERIOS_GATEWAY_URL = "https://materios.fluxpointstudios.com/blobs"
MATERIOS_GATEWAY_API_KEY = ""  # Optional — enables sponsored receipt submission

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave", "nothing"}
YES_WORDS = {"yes", "yeah", "sure", "yep", "y", "ok", "okay", "anchor", "blockchain", "chain",
             "submit", "cardano", "materios", "on-chain", "onchain", "immutable"}


class OrynqAiAuditabilityCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register_capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run())

    def _log_info(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.info(msg)

    def _log_error(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.error(msg)

    def _is_exit(self, text: Optional[str]) -> bool:
        return (text or "").lower().strip() in EXIT_WORDS

    def _build_hash_chain_entry(
        self,
        role: str,
        content: str,
        previous_hash: str,
        sequence: int,
    ) -> dict:
        """Build a single entry in the rolling SHA-256 hash chain."""
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        payload = json.dumps(
            {
                "seq": sequence,
                "role": role,
                "content": content,
                "prev": previous_hash,
                "ts": timestamp,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        entry_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return {
            "seq": sequence,
            "role": role,
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "chain_hash": entry_hash,
            "previous_hash": previous_hash,
            "timestamp": timestamp,
        }

    def _build_trace_content(self, trace: list[dict]) -> bytes:
        """Serialize the trace into canonical JSON bytes for blob storage."""
        return json.dumps(trace, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def _compute_content_hash(self, content: bytes) -> str:
        """SHA-256 hash of raw content bytes."""
        return hashlib.sha256(content).hexdigest()

    # -----------------------------------------------------------------
    # Blockchain anchoring: upload to Materios gateway
    # -----------------------------------------------------------------
    def _anchor_to_materios(self, trace: list[dict]) -> Optional[dict]:
        """Upload audit trail to Materios blob gateway.

        With an API key: the gateway auto-submits a receipt on-chain
        (sponsored — no wallet needed).

        Without an API key: the blob is stored on the gateway. The user
        can submit the receipt on-chain themselves using the orynq-sdk
        with a Materios wallet funded from the faucet.
        """
        try:
            content = self._build_trace_content(trace)
            content_hash = self._compute_content_hash(content)

            headers = {"Content-Type": "application/json"}
            if MATERIOS_GATEWAY_API_KEY:
                headers["x-api-key"] = MATERIOS_GATEWAY_API_KEY

            # Step 1: Upload manifest
            manifest = {
                "chunks": [
                    {"index": 0, "sha256": content_hash, "size": len(content)}
                ],
                "total_size": len(content),
            }
            manifest_resp = requests.post(
                MATERIOS_GATEWAY_URL + "/" + content_hash + "/manifest",
                headers=headers,
                json=manifest,
                timeout=30,
            )
            if manifest_resp.status_code not in (200, 201, 409):
                self._log_error(
                    "[OrynqAudit] Manifest upload failed: "
                    + str(manifest_resp.status_code)
                )
                return None
            self._log_info("[OrynqAudit] Manifest uploaded: " + content_hash[:16])

            # Step 2: Upload chunk
            chunk_headers = {"Content-Type": "application/octet-stream"}
            if MATERIOS_GATEWAY_API_KEY:
                chunk_headers["x-api-key"] = MATERIOS_GATEWAY_API_KEY

            chunk_resp = requests.put(
                MATERIOS_GATEWAY_URL + "/" + content_hash + "/chunks/0",
                headers=chunk_headers,
                data=content,
                timeout=30,
            )
            if chunk_resp.status_code not in (200, 201, 409):
                self._log_error(
                    "[OrynqAudit] Chunk upload failed: "
                    + str(chunk_resp.status_code)
                )
                return None
            self._log_info("[OrynqAudit] Chunk uploaded: " + str(len(content)) + " bytes")

            sponsored = bool(MATERIOS_GATEWAY_API_KEY)
            return {
                "content_hash": content_hash,
                "status": "submitted" if sponsored else "uploaded",
                "sponsored": sponsored,
            }

        except Exception as e:
            self._log_error("[OrynqAudit] Materios error: " + str(e))
            return None

    async def _collect_messages(self) -> list[tuple]:
        """Collect user messages for the audit trail."""
        await self.capability_worker.speak(
            "Got it. I will include your messages in the audit trail. "
            "Say more to add entries, or say done when finished."
        )

        first_input = await self.capability_worker.user_response()
        if not first_input or self._is_exit(first_input) or first_input.lower().strip() == "done":
            return []

        messages = [("user", first_input)]

        while True:
            next_input = await self.capability_worker.user_response()
            if not next_input or self._is_exit(next_input):
                break
            if next_input.lower().strip() == "done":
                break
            messages.append(("user", next_input))
            count = str(len(messages))
            await self.capability_worker.speak(
                "Added. " + count + " messages so far. Say done to finalize."
            )

        return messages

    async def run(self):
        try:
            await self.capability_worker.speak(
                "I will create a tamper-proof audit trail for this conversation. "
                "Each message gets hashed into a chain where any modification is detectable. "
                "Tell me what to include."
            )

            messages_to_audit = await self._collect_messages()

            if not messages_to_audit:
                await self.capability_worker.speak("No messages to audit. Cancelling.")
                return

            # Build the rolling hash chain
            trace = []
            previous_hash = "0" * 64
            seq = 0
            for role, content in messages_to_audit:
                entry = self._build_hash_chain_entry(role, content, previous_hash, seq)
                trace.append(entry)
                previous_hash = entry["chain_hash"]
                seq += 1

            trace_len = str(len(trace))
            anchor_hash = trace[-1]["chain_hash"]

            # Local artifact is always created
            await self.capability_worker.speak(
                "Built a " + trace_len + "-entry hash chain. "
                "Anchor hash: " + anchor_hash[:16] + ". "
                "This is already tamper-proof locally. "
                "Would you also like to anchor it to the blockchain?"
            )

            anchor_input = await self.capability_worker.user_response()
            wants_anchor = any(
                w in (anchor_input or "").lower().split()
                for w in YES_WORDS
            )

            if not anchor_input or self._is_exit(anchor_input) or not wants_anchor:
                response_text = self.capability_worker.text_to_text_response(
                    "Summarize for voice: a " + trace_len + "-entry tamper-proof hash chain "
                    "was created locally. Anchor hash is " + anchor_hash[:16] + ". "
                    "Not submitted to blockchain. One sentence."
                )
                await self.capability_worker.speak(response_text)
                return

            # Anchor to Materios
            await self.capability_worker.speak("Uploading to Materios for blockchain anchoring.")
            result = self._anchor_to_materios(trace)

            if result:
                ch = str(result.get("content_hash", ""))[:16]
                if result.get("sponsored"):
                    response_text = self.capability_worker.text_to_text_response(
                        "Summarize for voice: audit trail uploaded and receipt submitted "
                        "to Materios. Content hash: " + ch + ". "
                        "The committee will certify it and batch it into a Cardano "
                        "mainnet transaction. Check materios.fluxpointstudios.com/explorer. "
                        "One sentence."
                    )
                else:
                    response_text = self.capability_worker.text_to_text_response(
                        "Summarize for voice: audit trail uploaded to Materios gateway. "
                        "Content hash: " + ch + ". To complete on-chain submission, "
                        "use the orynq SDK with a Materios wallet funded from the faucet. "
                        "One sentence."
                    )
                await self.capability_worker.speak(response_text)
            else:
                await self.capability_worker.speak(
                    "Could not reach the gateway right now. "
                    "Your local hash chain is still valid. Anchor hash: " + anchor_hash[:16]
                )

        except Exception as e:
            self._log_error("[OrynqAudit] Unexpected error: " + str(e))
            if self.capability_worker:
                await self.capability_worker.speak(
                    "Sorry, something went wrong. Please try again."
                )
        finally:
            if self.capability_worker:
                self.capability_worker.resume_normal_flow()
