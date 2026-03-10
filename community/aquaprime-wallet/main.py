import json
import random

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

BASE_URL = "https://www.platypuspassions.com"


def register_player(device_id, display_name="Pilot"):
    """Register device. Returns {room_code, user_address, is_new_player, starting_node, wallet_type}."""
    try:
        resp = requests.post(
            f"{BASE_URL}/api/voice/player-register",
            json={"device_id": device_id, "display_name": display_name},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
        return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}


class AquaprimeWalletCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register_capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self._show_wallet())

    async def _show_wallet(self):
        """Quick wallet lookup — register if needed, speak the address."""
        try:
            try:
                device_id = self.worker.device_id
            except Exception:
                device_id = None

            log = self.worker.editor_logging_handler

            if not device_id:
                await self.capability_worker.speak(
                    "I cannot identify your device. "
                    "Say play aquaprime first to register and get a wallet."
                )
                self.capability_worker.resume_normal_flow()
                return

            # Idempotent — returns existing wallet if already registered
            reg = register_player(device_id)

            if not reg or reg.get("error"):
                log.error(f"Wallet lookup failed: {reg}")
                await self.capability_worker.speak(
                    "You don't have a wallet yet. "
                    "Say play aquaprime to start the game and get one."
                )
                self.capability_worker.resume_normal_flow()
                return

            wallet_address = reg.get("user_address", "")
            wallet_type = reg.get("wallet_type", "unknown")

            if not wallet_address:
                await self.capability_worker.speak(
                    "Could not retrieve your wallet. "
                    "Say play aquaprime to register."
                )
                self.capability_worker.resume_normal_flow()
                return

            short_addr = (
                f"{wallet_address[:6]}...{wallet_address[-4:]}"
                if len(wallet_address) >= 10
                else wallet_address
            )

            log.info(f"Wallet lookup: {wallet_address} (type={wallet_type})")

            await self.capability_worker.speak(
                f"Your Ethereum address is {short_addr}. "
                f"Full address: {wallet_address}. "
                f"This is a {'real Privy embedded wallet' if wallet_type == 'privy' else 'temporary game wallet'}. "
                f"You can see your ship on the map at platypus passions dot com slash stream view."
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Wallet lookup error: {e}")
            await self.capability_worker.speak(
                "Something went wrong looking up your wallet. Try again."
            )
        self.capability_worker.resume_normal_flow()
