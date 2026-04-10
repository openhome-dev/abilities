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
# Creates tamper-proof, blockchain-anchored audit trails for AI conversations
# using Orynq's Proof-of-Inference protocol. Builds SHA-256 rolling hash
# chains and supports two anchoring paths:
#
#   1. Managed API  - Direct Cardano L1 anchoring (metadata label 2222)
#   2. Materios     - Substrate partner chain with committee certification,
#                     then batched into Cardano L1 anchors
#
# The user chooses the path at runtime via voice.
# =============================================================================

# --- Managed API configuration ---
ORYNQ_API_URL = "https://api.orynq.com"
ORYNQ_API_KEY = "YOUR_ORYNQ_API_KEY_HERE"

# --- Materios partner chain configuration ---
MATERIOS_GATEWAY_URL = "https://materios.fluxpointstudios.com"
MATERIOS_GATEWAY_API_KEY = "YOUR_MATERIOS_GATEWAY_API_KEY_HERE"

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "leave", "nothing"}

MATERIOS_KEYWORDS = {"materios", "partner chain", "partner-chain", "certified", "committee", "high throughput"}
DIRECT_KEYWORDS = {"direct", "cardano", "l1", "managed", "simple", "fast"}

PLACEHOLDER_KEYS = {"YOUR_ORYNQ_API_KEY_HERE", "YOUR_MATERIOS_GATEWAY_API_KEY_HERE", ""}


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

    def _is_configured(self, mode: str) -> bool:
        """Check if the API key for the given mode is actually configured."""
        if mode == "materios":
            return MATERIOS_GATEWAY_API_KEY not in PLACEHOLDER_KEYS
        return ORYNQ_API_KEY not in PLACEHOLDER_KEYS

    def _detect_anchor_mode(self, text: str) -> Optional[str]:
        """Detect whether user wants Materios or direct Cardano anchoring."""
        lowered = (text or "").lower()
        if any(kw in lowered for kw in MATERIOS_KEYWORDS):
            return "materios"
        if any(kw in lowered for kw in DIRECT_KEYWORDS):
            return "direct"
        return None

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
        """Serialize the trace into content bytes for Materios blob storage."""
        return json.dumps(trace, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def _compute_content_hash(self, content: bytes) -> str:
        """SHA-256 hash of raw content bytes."""
        return hashlib.sha256(content).hexdigest()

    def _compute_manifest_hash(self, content_hash: str, chunk_count: int) -> str:
        """Compute a manifest hash from content hash and chunk metadata."""
        manifest = json.dumps(
            {"content_hash": content_hash, "chunk_count": chunk_count},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(manifest.encode("utf-8")).hexdigest()

    # -----------------------------------------------------------------
    # Path 1: Managed Orynq API -> direct Cardano L1
    # -----------------------------------------------------------------
    def _submit_to_orynq(self, trace: list[dict]) -> Optional[dict]:
        """Submit the hash chain trace to Orynq managed API for Cardano L1 anchoring."""
        try:
            headers = {
                "Authorization": "Bearer " + ORYNQ_API_KEY,
                "Content-Type": "application/json",
            }
            body = {
                "protocol": "proof-of-inference",
                "version": "1.0",
                "chain": "cardano:mainnet",
                "metadata_label": 2222,
                "trace": trace,
                "anchor_hash": trace[-1]["chain_hash"] if trace else "",
            }
            response = requests.post(
                ORYNQ_API_URL + "/v1/audit/anchor",
                headers=headers,
                json=body,
                timeout=30,
            )
            if response.status_code == 200:
                data = response.json()
                self._log_info("[OrynqAudit] Anchored: tx=" + str(data.get("tx_hash", "pending")))
                return data
            if response.status_code == 402:
                self._log_info("[OrynqAudit] Payment required for anchoring")
                return {"status": "payment_required", "message": "Anchoring requires payment via Flux protocol"}
            self._log_error("[OrynqAudit] API returned " + str(response.status_code) + ": " + response.text)
            return None
        except Exception as e:
            self._log_error("[OrynqAudit] Submission error: " + str(e))
            return None

    # -----------------------------------------------------------------
    # Path 2: Materios partner chain -> certification -> Cardano L1
    # -----------------------------------------------------------------
    def _submit_to_materios(self, trace: list[dict]) -> Optional[dict]:
        """Submit receipt to Materios gateway for partner chain anchoring.

        Flow: blob upload -> receipt submission -> committee certification
              -> batched Cardano L1 anchor.
        """
        try:
            content = self._build_trace_content(trace)
            content_hash = self._compute_content_hash(content)
            root_hash = content_hash
            manifest_hash = self._compute_manifest_hash(content_hash, 1)

            headers = {
                "x-api-key": MATERIOS_GATEWAY_API_KEY,
                "Content-Type": "application/json",
            }

            # Step 1: Upload blob data to gateway
            blob_body = {
                "content_hash": content_hash,
                "data": content.hex(),
                "encoding": "hex",
            }
            blob_resp = requests.post(
                MATERIOS_GATEWAY_URL + "/blobs/" + content_hash + "/upload",
                headers=headers,
                json=blob_body,
                timeout=30,
            )
            if blob_resp.status_code not in (200, 201, 409):
                self._log_error("[OrynqAudit] Materios blob upload failed: " + str(blob_resp.status_code))
                return None
            self._log_info("[OrynqAudit] Blob uploaded to Materios gateway")

            # Step 2: Submit receipt for on-chain storage and certification
            receipt_body = {
                "content_hash": content_hash,
                "root_hash": root_hash,
                "manifest_hash": manifest_hash,
                "trace_summary": {
                    "entry_count": len(trace),
                    "anchor_hash": trace[-1]["chain_hash"] if trace else "",
                    "protocol": "proof-of-inference",
                    "version": "1.0",
                },
            }
            receipt_resp = requests.post(
                MATERIOS_GATEWAY_URL + "/receipts/submit",
                headers=headers,
                json=receipt_body,
                timeout=30,
            )
            if receipt_resp.status_code in (200, 201):
                data = receipt_resp.json()
                receipt_id = data.get("receipt_id", data.get("receiptId", ""))
                self._log_info("[OrynqAudit] Materios receipt submitted: " + str(receipt_id))
                return {
                    "path": "materios",
                    "receipt_id": receipt_id,
                    "content_hash": content_hash,
                    "status": data.get("status", "submitted"),
                    "block_hash": data.get("block_hash", data.get("blockHash", "")),
                }
            if receipt_resp.status_code == 402:
                self._log_info("[OrynqAudit] Materios payment required")
                return {"status": "payment_required", "path": "materios"}
            self._log_error("[OrynqAudit] Materios receipt failed: " + str(receipt_resp.status_code))
            return None

        except Exception as e:
            self._log_error("[OrynqAudit] Materios submission error: " + str(e))
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
                "Added. " + count + " messages in the trail so far. Say done to finalize."
            )

        return messages

    async def _speak_local_result(self, trace: list[dict]):
        """Speak the local-only process trace result when no wallet is configured."""
        trace_len = str(len(trace))
        anchor_hash = trace[-1]["chain_hash"]
        response_text = self.capability_worker.text_to_text_response(
            "Summarize for voice: a local audit trail with " + trace_len + " entries was created "
            "as a tamper-proof hash chain. The anchor hash is " + anchor_hash[:16] + ". "
            "No wallet or API key is configured, so this is stored locally only. "
            "To anchor on-chain, configure your Materios or Orynq API key in the ability settings. "
            "Keep it to two short sentences for voice."
        )
        await self.capability_worker.speak(response_text)

    async def _speak_result(self, result: Optional[dict], trace: list[dict], mode: str):
        """Speak the anchoring result to the user."""
        trace_len = str(len(trace))

        if not result:
            anchor_hash = trace[-1]["chain_hash"]
            await self.capability_worker.speak(
                "I built the hash chain locally but could not reach the server right now. "
                "Your anchor hash is " + anchor_hash[:16] + ". You can verify it later."
            )
            return

        if result.get("status") == "payment_required":
            if mode == "materios":
                prompt = (
                    "Explain briefly that the audit trail was built and submitted to "
                    "Materios but the account needs MOTRA fee tokens for on-chain storage. "
                    "The hash chain has " + trace_len + " entries. One sentence for voice."
                )
            else:
                prompt = (
                    "Explain briefly that the audit trail was built but anchoring to Cardano "
                    "requires a small payment through the Orynq Flux protocol. The hash chain "
                    "has " + trace_len + " entries. One sentence for voice."
                )
            response_text = self.capability_worker.text_to_text_response(prompt)
            await self.capability_worker.speak(response_text)
            return

        if mode == "materios":
            receipt_id = str(result.get("receipt_id", ""))
            receipt_short = receipt_id[:16] if receipt_id else "pending"
            response_text = self.capability_worker.text_to_text_response(
                "Summarize for voice: audit trail with " + trace_len + " entries was submitted "
                "to the Materios partner chain. Receipt ID is " + receipt_short + ". "
                "The cert daemon committee will verify availability, then it gets batched "
                "into a Cardano L1 anchor automatically. One sentence."
            )
        elif result.get("tx_hash"):
            tx = str(result["tx_hash"])
            response_text = self.capability_worker.text_to_text_response(
                "Summarize for voice: audit trail with " + trace_len + " entries was anchored "
                "to Cardano. Transaction hash is " + tx + ". "
                "Mention it is now tamper-proof and independently verifiable. One sentence."
            )
        else:
            response_text = self.capability_worker.text_to_text_response(
                "Summarize for voice: audit trail with " + trace_len + " entries was submitted "
                "to Orynq and is being processed for Cardano anchoring. One sentence."
            )
        await self.capability_worker.speak(response_text)

    async def run(self):
        try:
            await self.capability_worker.speak(
                "I will create a blockchain audit trail for this conversation. "
                "Would you like to anchor directly to Cardano, or use the Materios "
                "partner chain for high-throughput certified receipts?"
            )

            mode_input = await self.capability_worker.user_response()
            if self._is_exit(mode_input):
                await self.capability_worker.speak("Okay, no audit trail created.")
                return

            # Detect anchoring mode from user response
            mode = self._detect_anchor_mode(mode_input)
            if not mode:
                # Default to managed API if unclear
                mode = "materios"
                self._log_info("[OrynqAudit] No clear preference, defaulting to Materios")

            if mode == "materios":
                await self.capability_worker.speak(
                    "Using Materios partner chain. Your receipt will be certified by "
                    "the committee and then batched into a Cardano L1 anchor. "
                    "Tell me what to include in the audit trail."
                )
            else:
                await self.capability_worker.speak(
                    "Using direct Cardano anchoring via the managed API. "
                    "Tell me what to include in the audit trail."
                )

            messages_to_audit = await self._collect_messages()

            if not messages_to_audit:
                await self.capability_worker.speak("No messages to audit. Cancelling.")
                return

            # Build the rolling hash chain
            trace = []
            previous_hash = "0" * 64  # genesis hash
            seq = 0
            for role, content in messages_to_audit:
                entry = self._build_hash_chain_entry(role, content, previous_hash, seq)
                trace.append(entry)
                previous_hash = entry["chain_hash"]
                seq += 1

            trace_len = str(len(trace))

            # Check if the chosen mode has a configured API key
            if not self._is_configured(mode):
                self._log_info("[OrynqAudit] No API key configured for " + mode + ", falling back to local artifact")
                await self.capability_worker.speak(
                    "Built a " + trace_len + "-entry hash chain. "
                    "No wallet is configured, so saving as a local audit artifact."
                )
                await self._speak_local_result(trace)
                return

            if mode == "materios":
                await self.capability_worker.speak(
                    "Built a " + trace_len + "-entry hash chain. "
                    "Submitting to Materios for certified anchoring."
                )
                result = self._submit_to_materios(trace)
            else:
                await self.capability_worker.speak(
                    "Built a " + trace_len + "-entry hash chain. "
                    "Submitting to Orynq for Cardano anchoring."
                )
                result = self._submit_to_orynq(trace)

            await self._speak_result(result, trace, mode)

        except Exception as e:
            self._log_error("[OrynqAudit] Unexpected error: " + str(e))
            if self.capability_worker:
                await self.capability_worker.speak(
                    "Sorry, something went wrong creating the audit trail. Please try again."
                )
        finally:
            if self.capability_worker:
                self.capability_worker.resume_normal_flow()
