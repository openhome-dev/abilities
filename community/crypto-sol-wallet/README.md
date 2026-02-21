# Crypto SOL Wallet

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)

## What It Does

Gives your OpenHome speaker a Solana wallet voice interface. **Read-only:** check SOL and USDC balances, live SOL price, and recent transactions. **Payment links:** request SOL from a contact or generate a Solana Pay link to send SOL/USDC to a contact — the link is sent to your phone; you approve in Phantom. The ability never holds private keys.

All data comes from **real external APIs**: Solana RPC and CoinGecko. Wallet address and contacts are configured in a preferences file.

## Suggested Trigger Words

- check my SOL
- Solana balance
- SOL price
- crypto balance solana
- Phantom
- Phantom wallet
- send SOL
- pay with SOL
- request SOL
- Solana wallet
- check Solana
- how much SOL do I have
- SOL transactions
- send USDC solana
- what's SOL worth
- solana fees

## Setup

1. **Phantom:** Install Phantom on your phone and copy your Solana wallet address (base58, 32–44 chars, no `0x`).
2. **Preferences file:** The ability reads `crypto_sol_prefs.json` (created automatically if missing). You must set `wallet_address` and optionally `contacts` before balance/transaction/payment features work.
3. **Creating/editing prefs:** Use the OpenHome file storage for this ability. The expected JSON shape:
   ```json
   {
     "wallet_address": "YourSolanaWalletAddressHere",
     "contacts": {
       "alex": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
       "mom": "3Tdbn6A3x7djfZBzQ7tmHnKsRRtP8y9boDaj43npFjJj"
     },
     "rpc_url": "https://api.mainnet-beta.solana.com",
     "default_currency": "usd",
     "spoken_decimals": 2
   }
   ```
4. **Optional:** For better RPC reliability under load, set `rpc_url` to a Helius endpoint: `https://mainnet.helius-rpc.com/?api-key=YOUR_KEY` (free tier at helius.dev).
5. **No API keys required** for basic use: CoinGecko is used without a key; public Solana RPC works (rate limits may apply).

## How It Works

- **Check balance:** Asks Solana RPC for SOL balance and USDC token account; speaks amount and optional USD value (via CoinGecko).
- **Check price:** Fetches SOL price and 24h change from CoinGecko; speaks it.
- **Recent transactions:** Fetches last 5 signatures, parses simple SOL/SPL transfers, speaks up to 3 in plain language (complex transactions are skipped or summarized as "complex transaction").
- **Request payment:** You say a contact name and amount (e.g. "Request 2 SOL from Alex"). Ability builds a Solana Pay URL for *your* wallet, confirms with you, then pushes the link via `payment-link` websocket so the companion app can show it on your phone; the payer opens it in Phantom.
- **Send payment:** You say contact and amount (e.g. "Send 50 USDC to Alex"). Ability builds a Solana Pay URL to the contact’s address, confirms, pushes the link; you open it in Phantom to approve.
- **Exit:** Say "stop", "exit", "done", etc. to leave the ability.

## Security

- The ability **never stores or sees private keys**. It only uses public addresses.
- It **never broadcasts transactions**. It only generates Solana Pay URLs; you approve in Phantom.
- Confirmation is required before any payment link; double confirmation for amounts over $500 USD equivalent.
- API keys (e.g. Helius) belong in the prefs file, not in code.

## Technical Notes

- Uses `session_tasks.sleep()` and `session_tasks.create()` (no `asyncio`).
- Logging via `editor_logging_handler` (no `print()`).
- `resume_normal_flow()` is called on every exit path (in a `finally` block).
- All HTTP requests use a timeout (15s RPC, 10s CoinGecko).
- Prefs: `check_if_file_exists`, then `read_file`; on save, `delete_file` then `write_file` for valid JSON.

## Example Conversation

**User:** Check my SOL  
**AI:** Hey, I can check your Solana wallet… What would you like?  
**User:** My balance  
**AI:** You have 12.5 SOL worth about 2228 dollars. You have 500 USDC on Solana.

**User:** Request 2 SOL from Alex  
**AI:** I'll create a payment request for 2 SOL from Alex. That's about 356 dollars. Shall I send the link?  
**User:** Yes  
**AI:** I've sent a payment link to your phone. They'll need to open it in Phantom to send you the SOL.

**User:** Stop  
**AI:** See you later.
