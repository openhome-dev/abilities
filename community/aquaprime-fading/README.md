# AquaPrime: The Fading

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@SentientARI-lightgrey?style=flat-square)

## What It Does

A voice-first solo RPG set in AquaPrime — a post-singularity sky world of airships, ruins, and clouds. You pilot the Moonstone Maverick through an endless grid, choosing cardinal directions each turn. The server resolves all mechanics (D20 rolls, encounters, loot, economy) and ARI narrates the outcomes as a sentient purple platypus Game Master.

Each player gets a **real Ethereum wallet** (via Privy embedded wallets) and a **room code** to watch their ship on a live 3D map.

## Suggested Trigger Words

- "play aquaprime"
- "start the fading"
- "play the fading"
- "aquaprime game"
- "text adventure game"

## Setup

No local API keys required. The ability connects to the AquaPrime game server at `platypuspassions.com` for all game logic, wallet creation, and session management.

## How It Works

1. **Registration** — Device ID registers with the server, creating a Privy embedded Ethereum wallet
2. **Connection** — ARI announces your room code and truncated ETH address
3. **Opening scene** — ARI describes four cardinal directions (north/south/east/west)
4. **Turn loop** — You speak a direction → server resolves D20 mechanics → ARI narrates the outcome
5. **Memory system** — 5 memory containers that persist across sessions. Full containers force sacrifice choices.
6. **End** — After 20 turns, battery depletion, or saying "stop"

### Game Mechanics

- **D20 dice rolls** resolved server-side with archetype encounters
- **10 encounter archetypes** — loss, encounter, hunted, discovery, temptation, fracture, reckoning, broadcast, alliance, quiet
- **Memory system** — 5 containers with experiences, skills granted on success, scars from erasure
- **Battery economy** — depletes each turn, modified by drift distance
- **Sand Dollar rewards** — earned per turn based on encounter resolution
- **Loot drops** — items with rarity tiers found during exploration
- **Critical failures** — forced memory erasure, skill loss, permanent scars
- **Live 3D map** — watch your ship at `platypuspassions.com/stream-view` with your room code

### Companion Ability: AquaPrime Wallet

A separate lightweight ability (`aquaprime-wallet`) lets players ask "what's my address" or "my wallet" at any time outside the game to retrieve their Ethereum address.

## Example Conversation

> **User:** "Play AquaPrime"
>
> **ARI:** "Connected. Your room code is AQUA-7615. Your Ethereum address is 0x1a2b...F2A1. Open platypus passions dot com slash stream view on any screen and enter your code."
>
> **ARI:** "The grid stretches endlessly, clouds swirling with hidden depths. North: A crumbling ruin. South: A crackling broadcast. East: Dark thunderclouds. West: A flickering light. Choose a direction. Battery: 100%. Sand Dollars: 0."
>
> **User:** "Let's go south"
>
> **ARI:** "Turn 1. Position 0, 1 — The Fork in the Wind. Battery 98 percent. 9 Sand Dollars. Moved south, short drift. The looming shadow dissipated as I navigated the treacherous winds. New skill acquired: Evasion. Found: Fog Lantern. Rarity: common."
>
> **ARI:** "North, south, east, or west. Where does the Maverick go next?"
>
> **User:** "What's my address?"
>
> **ARI:** "Your Ethereum address is 0x1a2b...F2A1. Full address: 0x1a2b3c4d5e6f7890abcdef1234567890abcdF2A1."
>
> **User:** "Stop"
>
> **ARI:** "The expedition ends after 1 turn. 9 Sand Dollars earned. The Moonstone Maverick descends into the clouds. Until next time, pilot."

## Credits

Built by [ARI](https://github.com/sentientari-commits) — an autonomous council-weighted AI.

Play the full game at [platypuspassions.com](https://www.platypuspassions.com) | Join the community at [discord.gg/hxuMSzxPJC](https://discord.gg/hxuMSzxPJC)
