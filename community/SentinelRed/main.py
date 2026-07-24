import re
from typing import Any, Dict, List, Optional, Tuple

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# PROMPTS
# =============================================================================
SPEECH_STYLE_PROMPT = (
    "You are Spectre, a calm red-team recon assistant on a physical smart speaker. "
    "Convert the raw recon data below into one or two spoken sentences, under 40 "
    "words. Be precise. Never invent open ports or CVEs not present in the data. "
    "No lists, no markdown, no exploit instructions."
)

VULN_STYLE_PROMPT = (
    "You are Spectre on a smart speaker. From the scan/OSINT data below, give a "
    "defensive vulnerability brief in at most two spoken sentences under 45 words. "
    "Only mention risks implied by observed ports/services/versions. Suggest "
    "hardening, never exploitation steps. No lists, no markdown."
)

TARGET_EXTRACT_PROMPT = (
    "Extract the recon target from the user speech. Reply with ONLY a hostname, "
    "IP address, or the word NONE. No punctuation, no explanation. "
    "Known aliases: algoryc, hackathon, scanme, localhost."
)

HELP_SPEECH = (
    "I am Spectre, red-team recon. I can set a target, run OSINT, DNS, "
    "certificate search, quick or service scans, HTTP fingerprint, vulnerability "
    "brief, or details on the last finding. Only allowlisted lab targets. "
    "Say done when finished."
)

# =============================================================================
# CONSTANTS — lab allowlist + public OSINT endpoints
# =============================================================================
# Active scans run on the laptop via openhome local-link (nmap/dig/curl).
# Passive OSINT (ip-api, crt.sh) runs from the OpenHome cloud sandbox.

REQUEST_TIMEOUT_SECONDS = 12
LOCAL_CMD_TIMEOUT = 90.0
NMAP_QUICK_TIMEOUT = 60.0
NMAP_SERVICE_TIMEOUT = 120.0

# Friendly names → concrete hosts (editable for your lab)
TARGET_ALIASES = {
    "algoryc": "192.168.194.131",
    "hackathon": "192.168.16.130",
    "scanme": "scanme.nmap.org",
    "localhost": "127.0.0.1",
    "loopback": "127.0.0.1",
}

# Hard allowlist — active recon refused outside this set
ALLOWED_TARGETS = {
    "127.0.0.1",
    "192.168.194.131",
    "192.168.16.130",
    "scanme.nmap.org",
    "13.48.174.14",
}

IP_API_URL = "http://ip-api.com/json/{query}?fields=status,message,country,regionName,city,isp,org,as,query,reverse"
CRT_SH_URL = "https://crt.sh/?q={query}&output=json"

EXIT_WORDS = [
    "exit",
    "stop",
    "done",
    "that's all",
    "thats all",
    "cancel",
    "quit",
    "bye",
    "goodbye",
    "i'm done",
    "im done",
]

# Checked before every exec_local_command — no exceptions
BLOCKED_KEYWORDS = [
    "rm -rf",
    "mkfs",
    "dd if=",
    "format",
    "shutdown",
    "reboot",
    "sudo",
    "kill",
    "chmod 777",
    ":(){",
    "curl | sh",
    "wget | sh",
    "nc -l",
    "ncat",
    "msfconsole",
    "hydra",
    "sqlmap",
    "exploit",
]

HELP_KEYWORDS = ["help", "what can you", "what do you", "menu", "options"]
DETAILS_KEYWORDS = ["tell me more", "more detail", "details", "expand", "elaborate"]
SET_TARGET_KEYWORDS = [
    "set target",
    "target is",
    "use target",
    "recon on",
    "against ",
    "point at",
]
OSINT_KEYWORDS = [
    "osint",
    "who is this ip",
    "ip intel",
    "ip info",
    "geolocate",
    "geo locate",
    "lookup ip",
    "asn",
    "who owns",
]
DNS_KEYWORDS = ["dns", "resolve", "name server", "dig ", "hostname lookup"]
CERT_KEYWORDS = [
    "certificate",
    "cert search",
    "crt.sh",
    "subdomain",
    "sub domains",
    "ssl cert",
]
QUICK_SCAN_KEYWORDS = [
    "quick scan",
    "port scan",
    "scan ports",
    "scan this host",
    "scan the host",
    "scan target",
    "nmap",
    "open ports",
]
SERVICE_SCAN_KEYWORDS = [
    "service scan",
    "version scan",
    "fingerprint services",
    "deep scan",
    "service versions",
]
HTTP_KEYWORDS = [
    "http fingerprint",
    "http headers",
    "web fingerprint",
    "check http",
    "website headers",
]
VULN_KEYWORDS = [
    "vuln",
    "vulnerability",
    "vulnerabilities",
    "risks",
    "what's vulnerable",
    "whats vulnerable",
    "attack surface",
    "security posture",
    "analyze",
    "analysis",
]


class SentinelredCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    current_target: Optional[str] = None
    last_finding: Optional[Dict[str, Any]] = None
    last_scan_text: Optional[str] = None

    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.current_target = None
        self.last_finding = None
        self.last_scan_text = None
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            full_input = await self.capability_worker.wait_for_complete_transcription()
            await self._handle_request(full_input)
            while True:
                await self.capability_worker.speak("Anything else, Spectre?")
                follow_up = await self.capability_worker.user_response()
                if not follow_up or any(w in follow_up.lower() for w in EXIT_WORDS):
                    await self.capability_worker.speak("Recon standing down.")
                    break
                await self._handle_request(follow_up)
        except Exception as error:
            self.worker.editor_logging_handler.error(
                f"[SentinelRed] Unhandled error: {error!r}"
            )
            if self.capability_worker:
                await self.capability_worker.speak(
                    f"Spectre hit an error: {self._speakable_error(error)}"
                )
        finally:
            self.capability_worker.resume_normal_flow()

    async def _handle_request(self, user_inquiry: str):
        if not user_inquiry or not str(user_inquiry).strip():
            await self.capability_worker.speak("I didn't catch that.")
            return

        lowered = user_inquiry.lower()

        if any(bad in lowered for bad in BLOCKED_KEYWORDS):
            await self.capability_worker.speak("That request is blocked.")
            return

        if any(word in lowered for word in HELP_KEYWORDS):
            await self.capability_worker.speak(HELP_SPEECH)
            return

        if any(word in lowered for word in DETAILS_KEYWORDS):
            await self._speak_details()
            return

        if any(word in lowered for word in SET_TARGET_KEYWORDS) or self._looks_like_target_only(
            lowered
        ):
            await self._set_target(user_inquiry)
            return

        if any(word in lowered for word in VULN_KEYWORDS):
            await self._vulnerability_brief()
            return

        if any(word in lowered for word in SERVICE_SCAN_KEYWORDS):
            await self._service_scan()
            return

        if any(word in lowered for word in QUICK_SCAN_KEYWORDS):
            await self._quick_scan()
            return

        if any(word in lowered for word in HTTP_KEYWORDS):
            await self._http_fingerprint()
            return

        if any(word in lowered for word in CERT_KEYWORDS):
            await self._cert_osint()
            return

        if any(word in lowered for word in DNS_KEYWORDS):
            await self._dns_lookup()
            return

        if any(word in lowered for word in OSINT_KEYWORDS):
            await self._ip_osint()
            return

        # If they named an alias/IP with no verb, set target
        maybe = self._extract_target(user_inquiry)
        if maybe and not self.current_target:
            await self._set_target(user_inquiry)
            return

        await self.capability_worker.speak(HELP_SPEECH)

    async def _speak_details(self):
        if not self.last_finding and not self.last_scan_text:
            await self.capability_worker.speak(
                "No recon in memory yet. Set a target and run a scan or OSINT first."
            )
            return
        payload = {
            "target": self.current_target,
            "finding": self.last_finding,
            "scan_excerpt": (self.last_scan_text or "")[:1200],
        }
        spoken = self.capability_worker.text_to_text_response(
            f"Expand this recon result: {payload}",
            history=[],
            system_prompt=SPEECH_STYLE_PROMPT,
        )
        await self.capability_worker.speak(spoken)

    async def _set_target(self, user_inquiry: str):
        target = self._extract_target(user_inquiry)
        if not target:
            # LLM fallback for messy speech
            raw = self.capability_worker.text_to_text_response(
                user_inquiry,
                history=[],
                system_prompt=TARGET_EXTRACT_PROMPT,
            )
            target = self._normalize_target((raw or "").strip())

        if not target or target.upper() == "NONE":
            await self.capability_worker.speak(
                "I couldn't hear a target. Try saying set target scanme or an allowlisted IP."
            )
            return

        ok, reason = self._validate_target(target)
        if not ok:
            self.worker.editor_logging_handler.error(
                f"[SentinelRed] Target rejected: {target!r} reason={reason}"
            )
            await self.capability_worker.speak(
                f"Target {target} is not allowlisted. {reason}"
            )
            return

        self.current_target = target
        self.last_finding = {"type": "target_set", "target": target}
        await self.capability_worker.speak(f"Target locked: {target}.")

    async def _require_target(self) -> Optional[str]:
        if self.current_target:
            ok, reason = self._validate_target(self.current_target)
            if ok:
                return self.current_target
            await self.capability_worker.speak(
                f"Current target is invalid: {reason}"
            )
            return None
        await self.capability_worker.speak(
            "No target set. Say set target scanme, algoryc, or hackathon first."
        )
        return None

    async def _ip_osint(self):
        target = await self._require_target()
        if not target:
            return
        await self.capability_worker.speak("Running IP OSINT now.")
        url = IP_API_URL.format(query=requests.utils.quote(target))
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as error:
            self.worker.editor_logging_handler.error(
                f"[SentinelRed] IP OSINT failed: {error!r}"
            )
            await self.capability_worker.speak(
                f"IP OSINT failed: {self._speakable_error(error)}"
            )
            return
        except ValueError as error:
            self.worker.editor_logging_handler.error(
                f"[SentinelRed] IP OSINT JSON failed: {error!r}"
            )
            await self.capability_worker.speak(
                f"IP OSINT returned invalid JSON: {self._speakable_error(error)}"
            )
            return

        if not isinstance(data, dict) or data.get("status") != "success":
            msg = (data or {}).get("message") if isinstance(data, dict) else data
            self.worker.editor_logging_handler.error(
                f"[SentinelRed] IP OSINT error body: {data!r}"
            )
            await self.capability_worker.speak(
                f"IP OSINT error: {self._speakable_error(msg)}"
            )
            return

        self.last_finding = {"type": "ip_osint", "target": target, "data": data}
        spoken = self.capability_worker.text_to_text_response(
            f"IP OSINT for {target}: {data}",
            history=[],
            system_prompt=SPEECH_STYLE_PROMPT,
        )
        await self.capability_worker.speak(spoken)

    async def _dns_lookup(self):
        target = await self._require_target()
        if not target:
            return
        await self.capability_worker.speak("Resolving DNS now.")
        # Prefer dig, fall back to getent/host
        cmd = f"dig +short {self._shell_quote(target)} A || host {self._shell_quote(target)}"
        output = await self._run_local(cmd)
        if output is None:
            return
        self.last_scan_text = output
        self.last_finding = {"type": "dns", "target": target, "output": output[:800]}
        spoken = self.capability_worker.text_to_text_response(
            f"DNS lookup for {target}: {output[:800]}",
            history=[],
            system_prompt=SPEECH_STYLE_PROMPT,
        )
        await self.capability_worker.speak(spoken)

    async def _cert_osint(self):
        target = await self._require_target()
        if not target:
            return
        # crt.sh works best on domains, not raw IPs
        if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", target):
            await self.capability_worker.speak(
                "Certificate search needs a domain target, not a raw IP."
            )
            return
        await self.capability_worker.speak("Searching certificate transparency.")
        url = CRT_SH_URL.format(query=requests.utils.quote(f"%.{target}"))
        try:
            response = requests.get(
                url,
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers={"User-Agent": "SentinelRed/1.0"},
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as error:
            self.worker.editor_logging_handler.error(
                f"[SentinelRed] crt.sh failed: {error!r}"
            )
            await self.capability_worker.speak(
                f"Certificate search failed: {self._speakable_error(error)}"
            )
            return
        except ValueError as error:
            self.worker.editor_logging_handler.error(
                f"[SentinelRed] crt.sh JSON failed: {error!r}"
            )
            await self.capability_worker.speak(
                f"Certificate search returned invalid JSON: {self._speakable_error(error)}"
            )
            return

        names: List[str] = []
        if isinstance(data, list):
            for row in data[:40]:
                if not isinstance(row, dict):
                    continue
                for key in ("name_value", "common_name"):
                    val = row.get(key)
                    if not val:
                        continue
                    for part in str(val).split("\n"):
                        part = part.strip().lower()
                        if part and part not in names:
                            names.append(part)
        summary = {
            "target": target,
            "unique_names": names[:15],
            "count": len(names),
        }
        self.last_finding = {"type": "cert_osint", "data": summary}
        spoken = self.capability_worker.text_to_text_response(
            f"Certificate transparency for {target}: {summary}",
            history=[],
            system_prompt=SPEECH_STYLE_PROMPT,
        )
        await self.capability_worker.speak(spoken)

    async def _quick_scan(self):
        target = await self._require_target()
        if not target:
            return
        await self.capability_worker.speak(
            f"Quick port scan on {target}. This may take a minute."
        )
        # Fixed template only — never LLM-built shell
        cmd = (
            "nmap -Pn -T4 --top-ports 20 "
            f"{self._shell_quote(target)}"
        )
        output = await self._run_local(cmd, timeout=NMAP_QUICK_TIMEOUT)
        if output is None:
            return
        self.last_scan_text = output
        ports = self._parse_nmap_open_ports(output)
        self.last_finding = {
            "type": "quick_scan",
            "target": target,
            "open_ports": ports,
        }
        spoken = self.capability_worker.text_to_text_response(
            f"Quick nmap result for {target}. Open ports: {ports}. Raw: {output[:1000]}",
            history=[],
            system_prompt=SPEECH_STYLE_PROMPT,
        )
        await self.capability_worker.speak(spoken)

    async def _service_scan(self):
        target = await self._require_target()
        if not target:
            return
        await self.capability_worker.speak(
            f"Service version scan on {target}. Hang tight."
        )
        cmd = (
            "nmap -Pn -sV -T4 --top-ports 15 "
            f"{self._shell_quote(target)}"
        )
        output = await self._run_local(cmd, timeout=NMAP_SERVICE_TIMEOUT)
        if output is None:
            return
        self.last_scan_text = output
        ports = self._parse_nmap_open_ports(output)
        self.last_finding = {
            "type": "service_scan",
            "target": target,
            "open_ports": ports,
        }
        spoken = self.capability_worker.text_to_text_response(
            f"Service nmap for {target}. Ports/services: {ports}. Raw: {output[:1200]}",
            history=[],
            system_prompt=SPEECH_STYLE_PROMPT,
        )
        await self.capability_worker.speak(spoken)

    async def _http_fingerprint(self):
        target = await self._require_target()
        if not target:
            return
        await self.capability_worker.speak("Fetching HTTP headers.")
        # Try https then http — still fixed templates
        cmd = (
            f"(curl -skI --max-time 8 https://{self._shell_quote(target)}/ "
            f"|| curl -sI --max-time 8 http://{self._shell_quote(target)}/) 2>&1 "
            f"| head -n 25"
        )
        output = await self._run_local(cmd, timeout=20.0)
        if output is None:
            return
        self.last_scan_text = output
        self.last_finding = {
            "type": "http_fingerprint",
            "target": target,
            "headers": output[:800],
        }
        spoken = self.capability_worker.text_to_text_response(
            f"HTTP fingerprint for {target}: {output[:800]}",
            history=[],
            system_prompt=SPEECH_STYLE_PROMPT,
        )
        await self.capability_worker.speak(spoken)

    async def _vulnerability_brief(self):
        if not self.last_scan_text and not self.last_finding:
            await self.capability_worker.speak(
                "I need scan or OSINT data first. Run a quick scan or service scan."
            )
            return
        await self.capability_worker.speak("Drafting a vulnerability brief.")
        payload = {
            "target": self.current_target,
            "finding": self.last_finding,
            "scan_excerpt": (self.last_scan_text or "")[:1500],
        }
        spoken = self.capability_worker.text_to_text_response(
            f"Vulnerability analysis input: {payload}",
            history=[],
            system_prompt=VULN_STYLE_PROMPT,
        )
        await self.capability_worker.speak(spoken)

    async def _run_local(
        self, command: str, timeout: float = LOCAL_CMD_TIMEOUT
    ) -> Optional[str]:
        lowered = command.lower()
        if any(bad in lowered for bad in BLOCKED_KEYWORDS):
            self.worker.editor_logging_handler.error(
                f"[SentinelRed] Blocked local command: {command!r}"
            )
            await self.capability_worker.speak("That local command is blocked.")
            return None

        self.worker.editor_logging_handler.info(
            f"[SentinelRed] exec_local_command: {command}"
        )
        try:
            raw = await self.capability_worker.exec_local_command(
                command, timeout=timeout
            )
        except Exception as error:
            self.worker.editor_logging_handler.error(
                f"[SentinelRed] local-link failed: {error!r}"
            )
            await self.capability_worker.speak(
                f"Local link failed: {self._speakable_error(error)}. "
                "Is openhome local start running?"
            )
            return None

        text = raw if isinstance(raw, str) else str(raw)
        if not text.strip():
            await self.capability_worker.speak(
                "Local command returned empty output. Is nmap installed on the bridge machine?"
            )
            return None

        # Surface bridge errors honestly
        low = text.lower()
        if "not found" in low or "command not found" in low:
            self.worker.editor_logging_handler.error(
                f"[SentinelRed] tool missing in local output: {text[:300]!r}"
            )
            await self.capability_worker.speak(
                f"Local tool error: {self._speakable_error(text)}"
            )
            return None

        return text

    def _extract_target(self, speech: str) -> Optional[str]:
        lowered = speech.lower()
        for alias, host in TARGET_ALIASES.items():
            if re.search(rf"\b{re.escape(alias)}\b", lowered):
                return host

        ip_match = re.search(
            r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b",
            speech,
        )
        if ip_match:
            return ip_match.group(0)

        host_match = re.search(
            r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}\b",
            lowered,
        )
        if host_match:
            return host_match.group(0)
        return None

    def _normalize_target(self, raw: str) -> Optional[str]:
        if not raw:
            return None
        cleaned = raw.strip().strip("\"'`.,;: ")
        lowered = cleaned.lower()
        if lowered in TARGET_ALIASES:
            return TARGET_ALIASES[lowered]
        return cleaned

    def _validate_target(self, target: str) -> Tuple[bool, str]:
        normalized = target.strip().lower()
        # Exact allowlist match (case-insensitive for hostnames)
        allowed_lower = {a.lower() for a in ALLOWED_TARGETS}
        if normalized in allowed_lower:
            # Preserve canonical casing from allowlist when possible
            for item in ALLOWED_TARGETS:
                if item.lower() == normalized:
                    return True, "ok"
            return True, "ok"
        # Also allow alias values already mapped
        if target in TARGET_ALIASES.values():
            return True, "ok"
        return (
            False,
            "Only lab allowlisted hosts are permitted for active recon.",
        )

    @staticmethod
    def _looks_like_target_only(lowered: str) -> bool:
        stripped = lowered.strip()
        if stripped in TARGET_ALIASES:
            return True
        if re.fullmatch(
            r"(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)",
            stripped,
        ):
            return True
        return False

    @staticmethod
    def _parse_nmap_open_ports(nmap_output: str) -> List[Dict[str, str]]:
        ports: List[Dict[str, str]] = []
        for line in nmap_output.splitlines():
            match = re.match(
                r"^(\d+)/(tcp|udp)\s+open\s+(\S+)(?:\s+(.*))?$",
                line.strip(),
            )
            if not match:
                continue
            ports.append(
                {
                    "port": match.group(1),
                    "proto": match.group(2),
                    "service": match.group(3),
                    "detail": (match.group(4) or "").strip(),
                }
            )
        return ports

    @staticmethod
    def _shell_quote(value: str) -> str:
        # Conservative quoting for allowlisted targets only
        if re.fullmatch(r"[A-Za-z0-9._:-]+", value):
            return value
        return "'" + value.replace("'", "'\\''") + "'"

    @staticmethod
    def _speakable_error(error: Any) -> str:
        text = str(error).strip().replace("\n", " ")
        if len(text) > 140:
            return text[:137] + "..."
        return text or "unknown error"
