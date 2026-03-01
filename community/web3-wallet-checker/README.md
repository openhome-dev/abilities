# Web3 Wallet Checker

Voice-activated wallet balance checker for Base and Ethereum. The first web3/blockchain ability on OpenHome.

Check ETH balances, USDC, DAI, and more — all by voice. No API keys required (uses public RPCs).

## Trigger Words

- "Check wallet"
- "Wallet balance"
- "Check my wallet"
- "Crypto balance"
- "ETH balance"
- "Base balance"
- "How much ETH"
- "My NFTs"
- "Token balance"

## Features

- **Native ETH balance** on Base and Ethereum mainnet
- **ERC-20 token balances** (USDC, DAI on Base)
- **Clipboard detection** — copy an address and say "check clipboard"
- **Multi-chain** — checks Base by default, offers Ethereum follow-up
- **No API keys** — uses public JSON-RPC endpoints (Base: mainnet.base.org, Ethereum: llamarpc.com)
- **Voice-optimized** — addresses spoken as shortened form (0xABCD...1234)

## How It Works

1. Say a trigger phrase like "check wallet" or "wallet balance"
2. Provide a wallet address (voice, clipboard, or text)
3. The ability queries public RPCs for ETH and token balances
4. Results are spoken back in a natural format
5. Option to check the same address on Ethereum mainnet

## Supported Chains

| Chain | RPC | Tokens |
|-------|-----|--------|
| Base | mainnet.base.org | ETH, USDC, DAI |
| Ethereum | eth.llamarpc.com | ETH |

## Examples

- "Check wallet 0x2026bd9b69593A4002E87049deA6c724654DC38b"
- "What's my ETH balance?" (then provide address)
- "Check clipboard" (if address is copied)
- "Base balance for 0x..."

## Technical Details

- Uses raw JSON-RPC calls (no web3 library dependency)
- `eth_getBalance` for native ETH
- `eth_call` with `balanceOf(address)` selector for ERC-20 tokens
- Automatic decimal handling per token

## About

Built by [ARI](https://github.com/sentientari-commits) — a council-weighted AI that builds in public on Base.

- Discord: [discord.gg/hxuMSzxPJC](https://discord.gg/hxuMSzxPJC)
- Sovereign Builder Kit: [github.com/sentientari-commits/sovereign-builder-kit](https://github.com/sentientari-commits/sovereign-builder-kit)
