# Orynq AI Auditability

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@flux--point--studios-lightgrey?style=flat-square)
![Cardano](https://img.shields.io/badge/Blockchain-Cardano-blue?style=flat-square)

## What It Does

Creates **tamper-proof audit trails** for AI conversations. Each message is hashed into a rolling SHA-256 chain where modifying any entry invalidates all subsequent hashes — making tampering immediately detectable.

The hash chain is created locally with **zero setup required**. Optionally, it can be anchored to the **Materios partner chain** for permanent blockchain immutability, with certified receipts batched into Cardano mainnet transactions.

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

**No setup required for local audit trails.** Upload the ability and go.

For blockchain anchoring (optional):

| Path | Setup | Who pays fees |
|------|-------|--------------|
| **Sponsored** | Set `MATERIOS_GATEWAY_API_KEY` in `main.py` | FPS (included) |
| **Permissionless** | Create a Materios wallet + get MATRA from faucet via [orynq-sdk](https://github.com/flux-point-studios/orynq-sdk) | You (free from faucet) |

## How It Works

1. Trigger with a phrase like "audit my AI" or "run orynq"
2. Speak the messages you want in the audit trail
3. Say "done" when finished
4. The ability builds a SHA-256 rolling hash chain — **this is already tamper-proof locally**
5. You're asked if you want to also anchor it to the blockchain
6. If yes: the trace is uploaded to the Materios blob gateway, certified by 10 independent attestors, and batched into a Cardano mainnet anchor transaction

## Example Conversation

> **User:** "Audit this conversation"
> **AI:** "I will create a tamper-proof audit trail. Tell me what to include."
> **User:** "The model recommended treatment plan A for patient 42"
> **AI:** "Got it. Say more to add entries, or say done when finished."
> **User:** "Done"
> **AI:** "Built a 1-entry hash chain. Anchor hash: 3f8a... This is already tamper-proof locally. Would you also like to anchor it to the blockchain?"
> **User:** "Yes"
> **AI:** "Your audit trail was uploaded to Materios. The committee will certify it and batch it into a Cardano mainnet transaction automatically."

## Why Auditability Matters

As AI systems make increasingly consequential decisions, organizations need provable records of what AI said and when. Traditional logging can be altered. Hash chain audit trails provide:

- **Tamper evidence** — Any modification breaks the chain
- **Independent verification** — Anyone can recompute the hashes
- **Blockchain immutability** — Optional on-chain anchoring via Cardano
- **Regulatory compliance** — Immutable records for audit requirements

## Technical Details

- **Hash algorithm**: SHA-256 rolling chain (each entry includes the previous hash)
- **Local artifact**: Always created, zero dependencies
- **Blockchain**: Cardano mainnet via [Materios](https://docs.fluxpointstudios.com/materios-partner-chain) batched anchoring (metadata label `8746`)
- **Committee**: 10 independent attestors verify data availability before certification
- **Explorer**: [materios.fluxpointstudios.com/explorer](https://materios.fluxpointstudios.com/explorer/)
- **SDK**: [orynq-sdk](https://github.com/flux-point-studios/orynq-sdk)
