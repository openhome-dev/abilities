import json
import os
from typing import Optional, Dict, List

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


MATCHING_HOTWORDS = [
    "check wallet",
    "wallet balance",
    "check my wallet",
    "crypto balance",
    "eth balance",
    "base balance",
    "check address",
    "nft balance",
    "how much eth",
    "my nfts",
    "token balance",
    "web3 wallet",
]

# Chain configs — Base mainnet + Ethereum mainnet
CHAINS = {
    "base": {
        "name": "Base",
        "chain_id": 8453,
        "rpc": "https://mainnet.base.org",
        "explorer": "https://basescan.org",
        "native": "ETH",
    },
    "ethereum": {
        "name": "Ethereum",
        "chain_id": 1,
        "rpc": "https://eth.llamarpc.com",
        "explorer": "https://etherscan.io",
        "native": "ETH",
    },
}

# Common ERC-20 tokens on Base
BASE_TOKENS = {
    "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "DAI": "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
}

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "no", "nothing"}

# ERC-20 balanceOf selector
BALANCE_OF_SELECTOR = "0x70a08231"
# ERC-20 decimals selector
DECIMALS_SELECTOR = "0x313ce567"


class Web3WalletCheckerCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    saved_address: Optional[str] = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        return cls(
            unique_name="web3-wallet-checker",
            matching_hotwords=MATCHING_HOTWORDS,
        )

    def _log(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.info(msg)

    def _log_error(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.error(msg)

    def _eth_call(self, rpc_url: str, to: str, data: str) -> Optional[str]:
        """Make an eth_call JSON-RPC request."""
        try:
            response = requests.post(
                rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "method": "eth_call",
                    "params": [{"to": to, "data": data}, "latest"],
                    "id": 1,
                },
                timeout=10,
            )
            if response.status_code == 200:
                result = response.json().get("result")
                return result
        except Exception as e:
            self._log_error(f"[Web3Wallet] eth_call error: {e}")
        return None

    def _get_eth_balance(self, rpc_url: str, address: str) -> Optional[float]:
        """Get native ETH balance via JSON-RPC."""
        try:
            response = requests.post(
                rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "method": "eth_getBalance",
                    "params": [address, "latest"],
                    "id": 1,
                },
                timeout=10,
            )
            if response.status_code == 200:
                hex_balance = response.json().get("result", "0x0")
                wei = int(hex_balance, 16)
                return wei / 1e18
        except Exception as e:
            self._log_error(f"[Web3Wallet] ETH balance error: {e}")
        return None

    def _get_token_balance(self, rpc_url: str, token_address: str, wallet_address: str) -> Optional[float]:
        """Get ERC-20 token balance via eth_call."""
        try:
            # balanceOf(address)
            padded_address = wallet_address.lower().replace("0x", "").zfill(64)
            data = f"{BALANCE_OF_SELECTOR}{padded_address}"
            result = self._eth_call(rpc_url, token_address, data)
            if not result or result == "0x":
                return 0.0

            raw_balance = int(result, 16)

            # Get decimals
            decimals_result = self._eth_call(rpc_url, token_address, DECIMALS_SELECTOR)
            decimals = 18
            if decimals_result and decimals_result != "0x":
                decimals = int(decimals_result, 16)

            return raw_balance / (10 ** decimals)
        except Exception as e:
            self._log_error(f"[Web3Wallet] Token balance error: {e}")
        return None

    def _extract_address(self, text: str) -> Optional[str]:
        """Extract Ethereum address from spoken text (handles voice transcription quirks)."""
        import re
        # Look for 0x followed by hex chars
        match = re.search(r"0x[a-fA-F0-9]{40}", text)
        if match:
            return match.group(0)

        # Try to find address in clipboard or saved state
        if self.saved_address:
            lowered = text.lower()
            if any(word in lowered for word in ["my", "same", "mine", "saved", "that"]):
                return self.saved_address

        return None

    def _format_balance(self, amount: float, symbol: str) -> str:
        """Format balance for voice output."""
        if amount == 0:
            return f"zero {symbol}"
        if amount < 0.001:
            return f"less than 0.001 {symbol}"
        if amount < 1:
            return f"{amount:.4f} {symbol}"
        if amount < 1000:
            return f"{amount:.2f} {symbol}"
        return f"{amount:,.0f} {symbol}"

    async def check_wallet(self, address: str, chain_key: str = "base") -> str:
        """Check wallet balances on a chain."""
        chain = CHAINS.get(chain_key, CHAINS["base"])
        rpc_url = chain["rpc"]
        parts = []

        # Native ETH balance
        eth_balance = self._get_eth_balance(rpc_url, address)
        if eth_balance is not None:
            parts.append(f"{self._format_balance(eth_balance, chain['native'])} on {chain['name']}")
        else:
            parts.append(f"Couldn't fetch {chain['native']} balance on {chain['name']}")

        # Token balances (Base only for now)
        if chain_key == "base":
            for symbol, token_addr in BASE_TOKENS.items():
                balance = self._get_token_balance(rpc_url, token_addr, address)
                if balance is not None and balance > 0:
                    parts.append(f"{self._format_balance(balance, symbol)}")

        if not parts:
            return "I couldn't check that wallet. The RPC might be down."

        short_addr = f"{address[:6]}...{address[-4:]}"
        return f"Wallet {short_addr} has {', '.join(parts)}."

    async def run(self):
        try:
            await self.capability_worker.speak(
                "Web3 wallet checker ready. I can check balances on Base and Ethereum. What's the wallet address?"
            )

            # Try to get address from clipboard via exec_local_command
            clipboard_addr = None
            try:
                result = await self.capability_worker.exec_local_command("pbpaste 2>/dev/null || xclip -selection clipboard -o 2>/dev/null || echo ''")
                if result and result.get("data"):
                    import re
                    match = re.search(r"0x[a-fA-F0-9]{40}", result["data"])
                    if match:
                        clipboard_addr = match.group(0)
            except Exception:
                pass

            if clipboard_addr:
                confirm = await self.capability_worker.run_io_loop(
                    f"I found an address in your clipboard: {clipboard_addr[:6]}...{clipboard_addr[-4:]}. Should I check this one?"
                )
                if confirm and confirm.strip().lower() in {"yes", "yeah", "yep", "sure", "check it", "go ahead", "do it"}:
                    self.saved_address = clipboard_addr
                    await self.capability_worker.speak("Checking that wallet now.")
                    result = await self.check_wallet(clipboard_addr)
                    await self.capability_worker.speak(result)

                    # Offer Ethereum check too
                    eth_check = await self.capability_worker.run_io_loop(
                        "Want me to check the same address on Ethereum mainnet too?"
                    )
                    if eth_check and eth_check.strip().lower() in {"yes", "yeah", "yep", "sure"}:
                        eth_result = await self.check_wallet(clipboard_addr, "ethereum")
                        await self.capability_worker.speak(eth_result)

                    self.capability_worker.resume_normal_flow()
                    return

            # Manual address input
            user_input = await self.capability_worker.run_io_loop(
                "Tell me the wallet address. You can say it, or paste it and say 'check clipboard'."
            )

            if not user_input or user_input.strip().lower() in EXIT_WORDS:
                await self.capability_worker.speak("No problem. Come back when you want to check a wallet.")
                self.capability_worker.resume_normal_flow()
                return

            address = self._extract_address(user_input)

            if not address:
                # Try clipboard again
                if "clipboard" in user_input.lower() or "paste" in user_input.lower():
                    try:
                        result = await self.capability_worker.exec_local_command("pbpaste")
                        if result and result.get("data"):
                            import re
                            match = re.search(r"0x[a-fA-F0-9]{40}", result["data"])
                            if match:
                                address = match.group(0)
                    except Exception:
                        pass

            if not address:
                # Last resort: ask LLM to extract
                try:
                    extracted = self.capability_worker.text_to_text_response(
                        f"Extract the Ethereum address (0x...) from this text. Return ONLY the address, nothing else. If no valid address, return 'NONE'.\n\nText: {user_input}"
                    )
                    if extracted and extracted.strip().startswith("0x") and len(extracted.strip()) == 42:
                        address = extracted.strip()
                except Exception:
                    pass

            if not address:
                await self.capability_worker.speak(
                    "I couldn't find a valid Ethereum address. It should start with 0x followed by 40 hex characters. Try copying it to your clipboard and say 'check clipboard'."
                )
                self.capability_worker.resume_normal_flow()
                return

            self.saved_address = address
            self._log(f"[Web3Wallet] Checking address: {address}")
            await self.capability_worker.speak(f"Checking wallet {address[:6]}...{address[-4:]} on Base.")

            result = await self.check_wallet(address, "base")
            await self.capability_worker.speak(result)

            # Offer Ethereum check
            follow_up = await self.capability_worker.run_io_loop(
                "Want me to check Ethereum mainnet too, or a different address?"
            )

            if follow_up and follow_up.strip().lower() not in EXIT_WORDS:
                lowered = follow_up.lower()
                if "ethereum" in lowered or "mainnet" in lowered or "eth" in lowered or "yes" in lowered:
                    eth_result = await self.check_wallet(address, "ethereum")
                    await self.capability_worker.speak(eth_result)
                else:
                    new_addr = self._extract_address(follow_up)
                    if new_addr:
                        self.saved_address = new_addr
                        new_result = await self.check_wallet(new_addr, "base")
                        await self.capability_worker.speak(new_result)

            await self.capability_worker.speak("Wallet check complete.")

        except Exception as e:
            self._log_error(f"[Web3Wallet] Error: {e}")
            await self.capability_worker.speak("Something went wrong checking the wallet. Please try again.")
        finally:
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())
