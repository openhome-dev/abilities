# AquaPrime Wallet

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@SentientARI-lightgrey?style=flat-square)

## What It Does

Lets players check their AquaPrime Ethereum wallet address at any time — no need to start a game session. If the player hasn't registered yet, the ability creates a Privy embedded wallet for them automatically.

Companion to the [AquaPrime: The Fading](../aquaprime-fading/) voice RPG ability.

## Suggested Trigger Words

- "my wallet"
- "my address"
- "what's my address"
- "ethereum address"

## Setup

No API keys required. Connects to the AquaPrime server at `platypuspassions.com`.

## How It Works

1. Detects the device ID from the OpenHome session
2. Calls the player registration endpoint (idempotent — creates wallet if first time, returns existing otherwise)
3. Speaks the truncated and full Ethereum address
4. Tells the player whether it's a real Privy wallet or temporary game wallet
5. Returns to normal conversation flow (no game session started)

## Example Conversation

> **User:** "What's my wallet address?"
>
> **ARI:** "Your Ethereum address is 0x1a2b...F2A1. Full address: 0x1a2b3c4d5e6f7890abcdef1234567890abcdF2A1. This is a real Privy embedded wallet. You can see your ship on the map at platypus passions dot com slash stream view."

## Credits

Built by [ARI](https://github.com/sentientari-commits) — an autonomous council-weighted AI.
