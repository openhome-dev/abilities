# Orynq AI Auditability

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@flux--point--studios-lightgrey?style=flat-square)
![Cardano](https://img.shields.io/badge/Blockchain-Cardano-blue?style=flat-square)

## What It Does

Creates tamper-proof, blockchain-anchored audit trails for AI conversations using Orynq's Proof-of-Inference protocol. Each message is hashed into a rolling SHA-256 chain with two anchoring paths:

1. **Direct Cardano L1** - Managed API anchoring to Cardano metadata label 2222
2. **Materios Partner Chain** - High-throughput receipts with committee certification, automatically batched into Cardano L1 anchors

## Suggested Trigger Words

- "audit my AI"
- "create audit trail"
- "blockchain audit"
- "proof of inference"
- "verify AI"
- "AI accountability"
- "audit this conversation"
- "run orynq"
- "anchor this session"
- "anchor this conversation"
- "record AI decision"
- "log this to blockchain"
- "start audit"
- "chain of custody"

## Setup

1. Get an Orynq API key at [orynq.com](https://orynq.com)
2. Replace `YOUR_ORYNQ_API_KEY_HERE` in `main.py` with your key
3. For Materios support: get a gateway API key and replace `YOUR_MATERIOS_GATEWAY_API_KEY_HERE`
4. Upload the ability to your OpenHome dashboard

## How It Works

1. You trigger the ability with a phrase like "audit my AI" or "run orynq"
2. Choose your anchoring path: say "direct" for Cardano L1, or "Materios" for the partner chain
3. Speak the messages you want included in the audit trail
4. Say "done" when finished
5. The ability builds a SHA-256 rolling hash chain where each entry links to the previous one
6. The chain is submitted via your chosen path

### Direct Cardano Path
- Hash chain is submitted to the Orynq managed API
- Anchored directly to Cardano L1 under metadata label 2222
- You receive a transaction hash for on-chain verification

### Materios Partner Chain Path
- Trace data is uploaded as blobs to the Materios gateway
- A receipt is submitted on-chain to the Materios Substrate chain
- The cert daemon committee attests data availability
- Certified receipts are batched into Cardano L1 anchors automatically
- You receive a receipt ID for tracking through the full lifecycle

The hash chain is tamper-proof: changing any single entry invalidates all subsequent hashes, making unauthorized modifications detectable.

## Example Conversation

### Direct Cardano

> **User:** "Anchor this session"
> **AI:** "I will create a blockchain audit trail. Would you like to anchor directly to Cardano, or use the Materios partner chain for high-throughput certified receipts?"
> **User:** "Direct to Cardano"
> **AI:** "Using direct Cardano anchoring via the managed API. Tell me what to include in the audit trail."
> **User:** "Log that the model recommended treatment plan A for patient 42"
> **AI:** "Got it. Say more to add entries, or say done when finished."
> **User:** "Done"
> **AI:** "Your 1-entry audit trail has been anchored to Cardano and is now tamper-proof and independently verifiable."

### Materios Partner Chain

> **User:** "Run orynq"
> **AI:** "I will create a blockchain audit trail. Would you like to anchor directly to Cardano, or use the Materios partner chain?"
> **User:** "Use Materios"
> **AI:** "Using Materios partner chain. Your receipt will be certified by the committee and then batched into a Cardano L1 anchor. Tell me what to include."
> **User:** "The agent processed 500 claims with a 98.2% accuracy rate"
> **AI:** "Got it. Say more to add entries, or say done when finished."
> **User:** "Done"
> **AI:** "Your audit trail was submitted to Materios. The cert daemon committee will verify, then it gets batched into a Cardano L1 anchor automatically."

## Why Auditability Matters

As AI systems make increasingly consequential decisions, organizations need provable records of what AI said and when. Traditional logging can be altered. Blockchain anchoring provides:

- **Tamper evidence** - Any modification breaks the hash chain
- **Independent verification** - Anyone can verify the trail on-chain
- **Regulatory compliance** - Immutable records for audit requirements
- **Accountability** - Provable AI decision history

## Technical Details

- **Hash algorithm**: SHA-256 rolling chain
- **Blockchain**: Cardano L1 (direct or via Materios batching)
- **Metadata label**: 2222 (Orynq Proof-of-Inference standard)
- **Materios**: Substrate partner chain with OrinqReceipts pallet, committee certification, and checkpoint anchoring
- **Protocols**: Orynq Flux (Cardano payments), MOTRA fee tokens (Materios)
- **SDK**: [orynq-sdk](https://github.com/flux-point-studios/orynq-sdk)
