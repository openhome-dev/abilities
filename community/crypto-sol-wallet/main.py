"""
Crypto SOL Wallet — Voice ability for Solana/Phantom: balances, prices,
recent transactions, and Solana Pay request/send links (no private keys).
V1: Read-only + payment request deeplinks. Prefs in crypto_sol_prefs.json.
"""
import json
import os
import re
import time
from typing import ClassVar

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

PREFS_FILE = "crypto_sol_prefs.json"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
DEFAULT_RPC = "https://api.mainnet-beta.solana.com"

EXIT_WORDS: ClassVar[set] = {
    "stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "never mind",
}

INTENT_CLASSIFY_PROMPT = """You are an intent classifier for a Solana voice wallet assistant.
Return ONLY valid JSON with no markdown or extra text.

Intents: check_balance, check_price, recent_transactions, request_payment, send_payment, help, exit, unknown

Extract when relevant: amount (number or null), token ("sol" or "usdc" or null), contact_name (string or null).

User input: "{input}"

JSON:"""


def _is_exit(user_input: str) -> bool:
    if not user_input:
        return False
    lower = user_input.lower().strip()
    return any(w in lower for w in EXIT_WORDS)


def _base58_address_valid(addr: str) -> bool:
    if not addr or len(addr) < 32 or len(addr) > 44:
        return False
    return bool(re.match(r"^[1-9A-HJ-NP-Za-km-z]+$", addr))


class CryptoSolWalletCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    # -------------------------------------------------------------------------
    # Prefs
    # -------------------------------------------------------------------------

    async def _load_prefs(self) -> dict:
        default = {
            "wallet_address": "",
            "contacts": {},
            "rpc_url": DEFAULT_RPC,
            "default_currency": "usd",
            "spoken_decimals": 2,
            "times_used": 0,
        }
        try:
            if await self.capability_worker.check_if_file_exists(PREFS_FILE, False):
                raw = await self.capability_worker.read_file(PREFS_FILE, False)
                if raw:
                    prefs = json.loads(raw)
                    default.update(prefs)
        except (json.JSONDecodeError, Exception) as e:
            self.worker.editor_logging_handler.warning(f"[CryptoSol] Load prefs: {e}")
        return default

    async def _save_prefs(self, prefs: dict):
        try:
            if await self.capability_worker.check_if_file_exists(PREFS_FILE, False):
                await self.capability_worker.delete_file(PREFS_FILE, False)
            await self.capability_worker.write_file(
                PREFS_FILE, json.dumps(prefs), False
            )
        except Exception as e:
            self.worker.editor_logging_handler.warning(f"[CryptoSol] Save prefs: {e}")

    # -------------------------------------------------------------------------
    # RPC & APIs
    # -------------------------------------------------------------------------

    def _rpc(self, prefs: dict, method: str, params: list) -> dict | None:
        url = (prefs.get("rpc_url") or DEFAULT_RPC).strip()
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 429:
                self.worker.editor_logging_handler.warning(
                    "[CryptoSol] RPC rate limited. Try again in a few seconds."
                )
                return None
            if resp.status_code != 200:
                self.worker.editor_logging_handler.warning(
                    f"[CryptoSol] RPC {resp.status_code}: {resp.text[:200]}"
                )
                return None
            data = resp.json()
            if "error" in data:
                self.worker.editor_logging_handler.warning(f"[CryptoSol] RPC error: {data['error']}")
                return None
            return data.get("result")
        except requests.exceptions.Timeout:
            self.worker.editor_logging_handler.warning("[CryptoSol] RPC timeout")
            return None
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[CryptoSol] RPC: {e}")
            return None

    def _get_sol_balance(self, prefs: dict) -> float | None:
        addr = (prefs.get("wallet_address") or "").strip()
        if not addr:
            return None
        result = self._rpc(prefs, "getBalance", [addr])
        if result is None:
            return None
        lamports = result.get("value")
        if lamports is None:
            return None
        return lamports / 1e9

    def _get_usdc_balance(self, prefs: dict) -> float | None:
        addr = (prefs.get("wallet_address") or "").strip()
        if not addr:
            return None
        result = self._rpc(
            prefs,
            "getTokenAccountsByOwner",
            [
                addr,
                {"mint": USDC_MINT},
                {"encoding": "jsonParsed"},
            ],
        )
        if not result or not result.get("value"):
            return None
        try:
            info = result["value"][0]["account"]["data"]["parsed"]["info"]
            return float(info.get("tokenAmount", {}).get("uiAmount") or 0)
        except (KeyError, IndexError, TypeError):
            return None

    def _get_sol_price(self) -> tuple[float | None, float | None]:
        try:
            r = requests.get(
                COINGECKO_URL,
                params={
                    "ids": "solana",
                    "vs_currencies": "usd",
                    "include_24hr_change": "true",
                },
                timeout=10,
            )
            if r.status_code != 200:
                return None, None
            data = r.json()
            sol = data.get("solana", {})
            price = sol.get("usd")
            change = sol.get("usd_24h_change")
            return (float(price) if price is not None else None), (
                float(change) if change is not None else None
            )
        except Exception as e:
            self.worker.editor_logging_handler.warning(f"[CryptoSol] CoinGecko: {e}")
            return None, None

    def _get_signatures(self, prefs: dict, limit: int = 10) -> list:
        addr = (prefs.get("wallet_address") or "").strip()
        if not addr:
            return []
        result = self._rpc(
            prefs, "getSignaturesForAddress", [addr, {"limit": limit}]
        )
        if not result:
            return []
        return result if isinstance(result, list) else []

    def _get_transaction(self, prefs: dict, signature: str) -> dict | None:
        result = self._rpc(
            prefs,
            "getTransaction",
            [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
        )
        return result

    def _parse_simple_transfer(
        self, tx: dict, my_address: str, contacts: dict
    ) -> dict | None:
        """Extract simple SOL or SPL transfer: direction, amount, counterparty name."""
        try:
            msg = (tx or {}).get("transaction", {}).get("message", {})
            instructions = msg.get("instructions") or []
            my_addr = my_address.strip()
            for ix in instructions:
                parsed = ix.get("parsed") or {}
                itype = parsed.get("type")
                info = parsed.get("info") or {}
                if ix.get("program") == "system" and itype == "transfer":
                    src = info.get("source") or ""
                    dst = info.get("destination") or ""
                    lamports = int(info.get("lamports") or 0)
                    sol = lamports / 1e9
                    if src == my_addr:
                        name = self._address_to_contact(dst, contacts)
                        return {"direction": "sent", "amount_sol": sol, "amount_usdc": None, "counterparty": name}
                    if dst == my_addr:
                        name = self._address_to_contact(src, contacts)
                        return {"direction": "received", "amount_sol": sol, "amount_usdc": None, "counterparty": name}
                if ix.get("program") == "spl-token" and itype in ("transfer", "transferChecked"):
                    token_amount = (info.get("tokenAmount") or {}).get("uiAmount")
                    if token_amount is None:
                        token_amount = info.get("amount")
                    if token_amount is not None:
                        amount = float(token_amount) if isinstance(token_amount, (int, float)) else None
                    else:
                        amount = None
                    source = info.get("source") or ""
                    dest = info.get("destination") or ""
                    if source == my_addr:
                        name = self._address_to_contact(dest, contacts)
                        return {"direction": "sent", "amount_sol": None, "amount_usdc": amount, "counterparty": name}
                    if dest == my_addr:
                        name = self._address_to_contact(source, contacts)
                        return {"direction": "received", "amount_sol": None, "amount_usdc": amount, "counterparty": name}
            return None
        except Exception as e:
            self.worker.editor_logging_handler.warning(f"[CryptoSol] Parse tx: {e}")
            return None

    def _address_to_contact(self, address: str, contacts: dict) -> str:
        addr = (address or "").strip()
        for name, caddr in (contacts or {}).items():
            if (caddr or "").strip() == addr:
                return name
        if len(addr) >= 4:
            return f"wallet ending in {addr[-4:]}"
        return "unknown"

    # -------------------------------------------------------------------------
    # Solana Pay URL & websocket
    # -------------------------------------------------------------------------

    def _build_solana_pay_url(
        self,
        recipient: str,
        amount: float,
        token: str = "sol",
        label: str = "OpenHome",
        message: str = "Payment",
    ) -> str:
        message_enc = requests.utils.quote(message)
        if token == "usdc":
            return (
                f"solana:{recipient}?amount={amount}"
                f"&spl-token={USDC_MINT}&label={label}&message={message_enc}"
            )
        return f"solana:{recipient}?amount={amount}&label={label}&message={message_enc}"

    async def _push_payment_link(
        self,
        url: str,
        action: str,
        token: str,
        amount: str,
        amount_usd: str,
        recipient_name: str,
        recipient_address: str,
    ):
        await self.capability_worker.send_data_over_websocket("payment-link", {
            "chain": "solana",
            "wallet": "phantom",
            "url": url,
            "action": action,
            "token": token,
            "amount": amount,
            "amount_usd": amount_usd,
            "recipient_name": recipient_name,
            "recipient_address": recipient_address,
            "timestamp": int(time.time()),
        })
        self.worker.editor_logging_handler.info(f"[CryptoSol] Payment link sent: {action} {token} {amount}")

    def _classify_intent(self, user_input: str) -> dict:
        prompt = INTENT_CLASSIFY_PROMPT.format(input=user_input.strip())
        raw = self.capability_worker.text_to_text_response(prompt)
        raw = re.sub(r"^```\w*\n?", "", raw).replace("```", "").strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"intent": "unknown", "amount": None, "token": None, "contact_name": None}

    def _resolve_contact(self, name: str, prefs: dict) -> str | None:
        contacts = prefs.get("contacts") or {}
        name_lower = (name or "").strip().lower()
        for k, v in contacts.items():
            if k.lower() == name_lower and v:
                addr = (v or "").strip()
                if _base58_address_valid(addr):
                    return addr
        return None

    # -------------------------------------------------------------------------
    # Main loop
    # -------------------------------------------------------------------------

    async def run(self):
        try:
            prefs = await self._load_prefs()
            wallet = (prefs.get("wallet_address") or "").strip()
            if not wallet or not _base58_address_valid(wallet):
                await self.capability_worker.speak(
                    "You haven't set up your wallet address yet. Add your Solana address in the crypto preferences file, then try again."
                )
                self.capability_worker.resume_normal_flow()
                return

            await self.capability_worker.speak(
                "Hey, I can check your Solana wallet, get prices, show transactions, or help you send and request SOL and USDC. What would you like?"
            )

            while True:
                await self.worker.session_tasks.sleep(0.1)
                user_input = await self.capability_worker.user_response()
                if not user_input or not user_input.strip():
                    continue
                if _is_exit(user_input):
                    await self.capability_worker.speak("See you later.")
                    break

                parsed = self._classify_intent(user_input)
                intent = (parsed.get("intent") or "unknown").strip().lower()
                amount = parsed.get("amount")
                token = (parsed.get("token") or "sol").strip().lower() or "sol"
                contact_name = (parsed.get("contact_name") or "").strip() or None

                if intent == "check_balance":
                    sol_bal = self._get_sol_balance(prefs)
                    if sol_bal is None:
                        await self.capability_worker.speak(
                            "The Solana network isn't responding. Try again in a moment."
                        )
                        continue
                    price_usd, _ = self._get_sol_price()
                    usdc_bal = self._get_usdc_balance(prefs)
                    if sol_bal == 0 and (usdc_bal is None or usdc_bal == 0):
                        await self.capability_worker.speak("Your wallet doesn't have any SOL or USDC right now.")
                        continue
                    parts = []
                    if sol_bal > 0:
                        parts.append(f"You have {sol_bal:.2f} SOL")
                        if price_usd is not None:
                            parts.append(f"worth about {sol_bal * price_usd:.0f} dollars")
                        parts.append(".")
                    if usdc_bal is not None and usdc_bal > 0:
                        parts.append(f" You have {usdc_bal:.0f} USDC on Solana.")
                    await self.capability_worker.speak(" ".join(parts))

                elif intent == "check_price":
                    price, change = self._get_sol_price()
                    if price is None:
                        await self.capability_worker.speak(
                            "I couldn't get the SOL price right now. Try again later."
                        )
                        continue
                    change_str = ""
                    if change is not None:
                        direction = "up" if change >= 0 else "down"
                        change_str = f", {direction} {abs(change):.1f} percent in the last twenty four hours"
                    await self.capability_worker.speak(
                        f"SOL is at {price:.2f} dollars{change_str}."
                    )

                elif intent == "recent_transactions":
                    sigs = self._get_signatures(prefs, limit=5)
                    if not sigs:
                        await self.capability_worker.speak("You have no recent Solana transactions.")
                        continue
                    contacts = prefs.get("contacts") or {}
                    spoken = []
                    for sig_info in sigs[:3]:
                        sig = sig_info.get("signature")
                        if not sig:
                            continue
                        tx = self._get_transaction(prefs, sig)
                        parsed_tx = self._parse_simple_transfer(tx, wallet, contacts) if tx else None
                        if parsed_tx:
                            d = parsed_tx["direction"]
                            name = parsed_tx.get("counterparty") or "someone"
                            if parsed_tx.get("amount_sol") is not None:
                                amt = f"{parsed_tx['amount_sol']:.2f} SOL"
                            elif parsed_tx.get("amount_usdc") is not None:
                                amt = f"{parsed_tx['amount_usdc']:.0f} USDC"
                            else:
                                amt = "some amount"
                            spoken.append(f"{d} {amt} {'to' if d == 'sent' else 'from'} {name}")
                        else:
                            spoken.append("a complex transaction")
                    if spoken:
                        await self.capability_worker.speak(
                            "Your most recent: " + ". ".join(spoken) + "."
                        )
                    else:
                        await self.capability_worker.speak(
                            "I found recent transactions but couldn't summarize them. Check your wallet on Phantom for details."
                        )

                elif intent == "request_payment":
                    if not contact_name:
                        await self.capability_worker.speak(
                            "Who should send you the payment? Say a contact name from your list."
                        )
                        continue
                    to_address = self._resolve_contact(contact_name, prefs)
                    if not to_address:
                        names = list((prefs.get("contacts") or {}).keys())
                        await self.capability_worker.speak(
                            f"I don't have a contact named {contact_name}. Your saved contacts are {', '.join(names) or 'none'}. Add them in the preferences file."
                        )
                        continue
                    amt = float(amount) if amount is not None else None
                    if amt is None or amt <= 0:
                        await self.capability_worker.speak("How much SOL do you want to request? Say a number.")
                        continue
                    price_usd, _ = self._get_sol_price()
                    usd_approx = (amt * price_usd) if price_usd else None
                    confirm_msg = f"I'll create a payment request for {amt} SOL from {contact_name}."
                    if usd_approx is not None:
                        confirm_msg += f" That's about {usd_approx:.0f} dollars."
                    confirm_msg += " Shall I send the link?"
                    if usd_approx is not None and usd_approx > 500:
                        ok = await self.capability_worker.run_confirmation_loop(confirm_msg)
                        if not ok:
                            await self.capability_worker.speak("No problem.")
                            continue
                        ok2 = await self.capability_worker.run_confirmation_loop(
                            f"Just to be sure — that's about {usd_approx:.0f} dollars. Are you certain?"
                        )
                        if not ok2:
                            await self.capability_worker.speak("Cancelled.")
                            continue
                    else:
                        ok = await self.capability_worker.run_confirmation_loop(confirm_msg)
                        if not ok:
                            await self.capability_worker.speak("No problem.")
                            continue
                    url = self._build_solana_pay_url(
                        wallet, amt, "sol", "OpenHome", "Payment request"
                    )
                    await self._push_payment_link(
                        url, "request", "SOL", str(amt),
                        f"{usd_approx:.2f}" if usd_approx is not None else "",
                        contact_name, to_address,
                    )
                    await self.capability_worker.speak(
                        "I've sent a payment link to your phone. They'll need to open it in Phantom to send you the SOL."
                    )

                elif intent == "send_payment":
                    if not contact_name:
                        await self.capability_worker.speak(
                            "Who do you want to send to? Say a contact name."
                        )
                        continue
                    to_address = self._resolve_contact(contact_name, prefs)
                    if not to_address:
                        names = list((prefs.get("contacts") or {}).keys()
                        await self.capability_worker.speak(
                            f"I don't have a contact named {contact_name}. Your contacts are {', '.join(names) or 'none'}."
                        )
                        continue
                    amt = float(amount) if amount is not None else None
                    if amt is None or amt <= 0:
                        await self.capability_worker.speak("How much do you want to send? Say the amount and token, like 50 USDC or 1 SOL.")
                        continue
                    tok = "usdc" if token == "usdc" else "sol"
                    price_usd, _ = self._get_sol_price()
                    usd_approx = (amt * price_usd) if (tok == "sol" and price_usd) else (amt if tok == "usdc" else None)
                    confirm_msg = f"I'll create a link to send {amt} {tok.upper()} to {contact_name}."
                    if usd_approx is not None:
                        confirm_msg += f" That's about {usd_approx:.0f} dollars."
                    confirm_msg += " Shall I send the link to your phone?"
                    if usd_approx is not None and usd_approx > 500:
                        ok = await self.capability_worker.run_confirmation_loop(confirm_msg)
                        if not ok:
                            await self.capability_worker.speak("No problem.")
                            continue
                        ok2 = await self.capability_worker.run_confirmation_loop(
                            f"Just to be sure — that's about {usd_approx:.0f} dollars. Are you certain?"
                        )
                        if not ok2:
                            await self.capability_worker.speak("Cancelled.")
                            continue
                    else:
                        ok = await self.capability_worker.run_confirmation_loop(confirm_msg)
                        if not ok:
                            await self.capability_worker.speak("No problem.")
                            continue
                    url = self._build_solana_pay_url(
                        to_address, amt, tok, "OpenHome", "From your speaker"
                    )
                    await self._push_payment_link(
                        url, "send", tok.upper(), str(amt),
                        f"{usd_approx:.2f}" if usd_approx is not None else "",
                        contact_name, to_address,
                    )
                    await self.capability_worker.speak(
                        "I've sent the link to your phone. Open it in Phantom to confirm sending."
                    )

                elif intent == "help":
                    await self.capability_worker.speak(
                        "You can ask for your SOL or USDC balance, the current SOL price, your recent transactions, "
                        "or request and send SOL and USDC using payment links. Say stop when you're done."
                    )

                else:
                    await self.capability_worker.speak(
                        "I didn't catch that. You can check balances, prices, transactions, or send and request SOL. What would you like?"
                    )

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[CryptoSol] Error: {e}")
            await self.capability_worker.speak("Something went wrong. Exiting.")
        finally:
            self.capability_worker.resume_normal_flow()
