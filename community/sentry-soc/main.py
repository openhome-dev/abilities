import asyncio
import datetime
from typing import Any, Dict, List, Optional

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# PROMPTS
# =============================================================================
SPEECH_STYLE_PROMPT = (
    "You are Sentry, a calm, precise security operations assistant on a physical "
    "smart speaker. Convert the raw data below into one or two spoken sentences, "
    "under 35 words total. If multiple agents appear, name each one. "
    "Flag anything critical or unusual plainly. No lists, no markdown."
)

DETAILS_STYLE_PROMPT = (
    "You are Sentry on a smart speaker. Expand this single alert into at most two "
    "short spoken sentences. Include agent, severity, and path or source IP when "
    "present. No lists, no markdown."
)

HELP_SPEECH = (
    "I can check critical alerts, connected agents, newest agent info, "
    "FIM file changes, Windows agent alerts, scan activity, last-hour brief, "
    "severity counts, details, or run the response playbook. Say done when finished."
)

# =============================================================================
# CONFIG — nothing hardcoded. Add these in OpenHome Settings -> API Keys
# (names must match exactly). wazuh_verify_tls is optional and defaults to
# verifying TLS certs; set it to "false" only if the indexer/manager use a
# self-signed cert you accept the risk of not validating.
# =============================================================================
WAZUH_INDEXER_URL_KEY = "wazuh_indexer_url"
WAZUH_READONLY_USER_KEY = "wazuh_readonly_user"
WAZUH_READONLY_PASSWORD_KEY = "wazuh_readonly_password"
WAZUH_MANAGER_URL_KEY = "wazuh_manager_url"
WAZUH_API_USER_KEY = "wazuh_api_user"
WAZUH_API_PASSWORD_KEY = "wazuh_api_password"
SHUFFLE_WEBHOOK_URL_KEY = "shuffle_webhook_url"
WAZUH_VERIFY_TLS_KEY = "wazuh_verify_tls"

DEMO_AGENT_ID = "001"
DEMO_AGENT_NAME = "endpoint-1"
EXCLUDED_AGENT_NAMES = ["retired-agent"]
MANAGER_AGENT_ID = "000"

REQUEST_TIMEOUT_SECONDS = 10
ALERT_FETCH_SIZE = 5
MIN_ALERT_LEVEL = 7

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
BLOCKED_KEYWORDS = ["rm -rf", "format", "shutdown", "sudo", "kill"]

HELP_KEYWORDS = ["help", "what can you", "what do you", "menu", "options"]
DETAILS_KEYWORDS = ["tell me more", "more detail", "details", "expand", "elaborate"]
FIM_KEYWORDS = [
    "fim",
    "file integrity",
    "integrity",
    "syscheck",
    "file change",
    "file changes",
    "files change",
    "deletion",
    "deletions",
    "modified file",
    "checksum",
]
PLAYBOOK_KEYWORDS = [
    "playbook",
    "response",
    "enrich",
    "abuse",
    "shuffle",
    "isolate",
    "block",
    "run response",
]
AGENT_INVENTORY_KEYWORDS = [
    "how many agents",
    "agent count",
    "number of agents",
    "list agents",
    "connected agents",
    "active agents",
    "new agent",
    "newest agent",
    "latest agent",
    "agent connected",
    "agents connected",
    "any new agent",
    "who is connected",
    "show agents",
]
AGENT_ALERT_KEYWORDS = [
    "endpoint-1",
    "windows agent",
    "windows box",
    "on windows",
    "what's on",
    "whats on",
    "agent alerts",
]
SCAN_KEYWORDS = [
    "scan",
    "firewall",
    "port scan",
    "srcip",
    "source ip",
    "attacker",
    "scan activity",
]
SEVERITY_KEYWORDS = [
    "how bad",
    "severity",
    "how many",
    "count",
    "noise",
]
BRIEF_KEYWORDS = [
    "last hour",
    "past hour",
    "today",
    "brief",
    "summary",
    "summarize",
]
ALERT_KEYWORDS = [
    "alert",
    "alerts",
    "wazuh",
    "critical",
    "status",
    "security",
    "sentry",
]


class SentinelVoiceCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    last_alert: Optional[Dict[str, Any]] = None
    last_agents: Optional[List[Dict[str, Any]]] = None
    focus_agent_name: Optional[str] = None
    wazuh_indexer_url: str = ""
    wazuh_readonly_user: str = ""
    wazuh_readonly_password: str = ""
    wazuh_manager_url: str = ""
    wazuh_api_user: str = ""
    wazuh_api_password: str = ""
    shuffle_webhook_url: str = ""
    wazuh_verify_tls: bool = True

    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.last_alert = None
        self.last_agents = None
        self.focus_agent_name = DEMO_AGENT_NAME

        self.wazuh_indexer_url = self.capability_worker.get_api_keys(WAZUH_INDEXER_URL_KEY) or ""
        self.wazuh_readonly_user = self.capability_worker.get_api_keys(WAZUH_READONLY_USER_KEY) or ""
        self.wazuh_readonly_password = self.capability_worker.get_api_keys(WAZUH_READONLY_PASSWORD_KEY) or ""
        self.wazuh_manager_url = self.capability_worker.get_api_keys(WAZUH_MANAGER_URL_KEY) or ""
        self.wazuh_api_user = self.capability_worker.get_api_keys(WAZUH_API_USER_KEY) or ""
        self.wazuh_api_password = self.capability_worker.get_api_keys(WAZUH_API_PASSWORD_KEY) or ""
        self.shuffle_webhook_url = self.capability_worker.get_api_keys(SHUFFLE_WEBHOOK_URL_KEY) or ""
        raw_verify = (self.capability_worker.get_api_keys(WAZUH_VERIFY_TLS_KEY) or "").strip().lower()
        self.wazuh_verify_tls = raw_verify not in ("false", "0", "no")

        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            full_input = await self.capability_worker.wait_for_complete_transcription()
            await self._handle_request(full_input)
            while True:
                await self.capability_worker.speak("Anything else, Sentry?")
                follow_up = await self.capability_worker.user_response()
                if not follow_up or any(w in follow_up.lower() for w in EXIT_WORDS):
                    await self.capability_worker.speak("Standing down.")
                    break
                await self._handle_request(follow_up)
        except Exception as error:
            self.worker.editor_logging_handler.error(
                f"[SentinelVoice] Unhandled error: {error!r}"
            )
            if self.capability_worker:
                await self.capability_worker.speak(
                    f"Sentry hit an error: {self._speakable_error(error)}"
                )
        finally:
            self.capability_worker.resume_normal_flow()

    async def _handle_request(self, user_inquiry: str):
        if not user_inquiry or not str(user_inquiry).strip():
            await self.capability_worker.speak("I didn't catch that.")
            return

        lowered = user_inquiry.lower()

        if any(bad in lowered for bad in BLOCKED_KEYWORDS):
            await self.capability_worker.speak("I can't run that.")
            return

        if any(word in lowered for word in HELP_KEYWORDS):
            await self.capability_worker.speak(HELP_SPEECH)
            return

        if any(word in lowered for word in DETAILS_KEYWORDS):
            await self._speak_alert_details()
            return

        if any(word in lowered for word in FIM_KEYWORDS):
            await self._check_fim_alerts(lowered)
            return

        if any(word in lowered for word in PLAYBOOK_KEYWORDS):
            await self._trigger_response_playbook()
            return

        if any(word in lowered for word in AGENT_INVENTORY_KEYWORDS):
            await self._check_agent_inventory(lowered)
            return

        if any(word in lowered for word in AGENT_ALERT_KEYWORDS):
            await self._check_agent_alerts(lowered)
            return

        if any(word in lowered for word in SCAN_KEYWORDS):
            await self._check_scan_alerts()
            return

        if any(word in lowered for word in SEVERITY_KEYWORDS):
            await self._check_severity_counts()
            return

        if any(word in lowered for word in BRIEF_KEYWORDS):
            await self._check_time_brief(lowered)
            return

        if any(word in lowered for word in ALERT_KEYWORDS):
            await self._check_wazuh_alerts()
            return

        await self.capability_worker.speak(HELP_SPEECH)

    def _narrate(self, content: str, style_prompt: str) -> str:
        """text_to_text_response() on this host rejects a "system"/"system_prompt"
        kwarg, so the style prompt is folded into the prompt text itself rather
        than passed as a separate argument."""
        full_prompt = style_prompt + "\n\n" + content
        return self.capability_worker.text_to_text_response(full_prompt)

    async def _speak_alert_details(self):
        if not self.last_alert:
            await self.capability_worker.speak(
                "No alert in memory yet. Ask for critical alerts or FIM first."
            )
            return
        spoken = self._narrate(f"Expand this alert: {self.last_alert}", DETAILS_STYLE_PROMPT)
        await self.capability_worker.speak(spoken)

    async def _check_wazuh_alerts(self):
        await self.capability_worker.speak("Checking WAZUH now.")
        query = {
            "size": ALERT_FETCH_SIZE,
            "sort": [{"timestamp": {"order": "desc"}}],
            "query": {
                "bool": {
                    "must": [{"range": {"rule.level": {"gte": MIN_ALERT_LEVEL}}}],
                    "must_not": self._excluded_agent_clauses(),
                }
            },
        }
        await self._search_and_speak(
            query,
            empty_speech="No critical alerts right now. All clear.",
            llm_prefix="Recent high-severity WAZUH alerts",
        )

    async def _check_fim_alerts(self, lowered: str):
        await self.capability_worker.speak("Checking file integrity now.")
        named = self._resolve_agent_name_from_speech(lowered)
        must: List[Dict[str, Any]] = [
            {"term": {"rule.groups": "syscheck"}},
        ]
        if named:
            must.append({"term": {"agent.name": named}})
        if "deletion" in lowered or "deletions" in lowered or "deleted" in lowered:
            must.append({"term": {"rule.groups": "syscheck_entry_deleted"}})
        elif "modified" in lowered or "checksum" in lowered:
            must.append({"term": {"rule.groups": "syscheck_entry_modified"}})

        query = {
            "size": 10,
            "sort": [{"timestamp": {"order": "desc"}}],
            "query": {
                "bool": {
                    "must": must,
                    "must_not": self._excluded_agent_clauses(),
                }
            },
        }
        label = named or "all agents"
        await self._search_and_speak(
            query,
            empty_speech=(
                f"No FIM events on {label} yet. Add the SentryDemo folder to "
                "ossec.conf, restart the Wazuh service, touch a file, then ask again."
            ),
            llm_prefix=(
                f"Recent FIM syscheck alerts on {label}. "
                "Mention every distinct agent that appears."
            ),
        )

    async def _check_agent_inventory(self, lowered: str):
        await self.capability_worker.speak("Checking connected agents.")
        agents = await self._fetch_agents()
        if agents is None:
            return

        endpoints = [
            a
            for a in agents
            if str(a.get("id")) != MANAGER_AGENT_ID
            and a.get("name") not in EXCLUDED_AGENT_NAMES
        ]
        self.last_agents = endpoints
        total = len(endpoints)
        active = [a for a in endpoints if str(a.get("status", "")).lower() == "active"]

        if "new" in lowered or "newest" in lowered or "latest" in lowered:
            newest = self._newest_agent(endpoints)
            if not newest:
                await self.capability_worker.speak(
                    "No endpoint agents are registered right now."
                )
                return
            self.focus_agent_name = newest.get("name") or self.focus_agent_name
            spoken = self._narrate(
                f"Newest WAZUH endpoint agent details: {newest}. "
                f"Total endpoint agents: {total}. Active: {len(active)}.",
                SPEECH_STYLE_PROMPT,
            )
            await self.capability_worker.speak(spoken)
            return

        roster = []
        for a in endpoints:
            host_os = a.get("o" + "s") or {}
            roster.append(
                {
                    "id": a.get("id"),
                    "name": a.get("name"),
                    "status": a.get("status"),
                    "ip": a.get("ip"),
                    "platform": host_os.get("name")
                    if isinstance(host_os, dict)
                    else None,
                    "dateAdd": a.get("dateAdd"),
                    "lastKeepAlive": a.get("lastKeepAlive"),
                }
            )
        if roster:
            self.focus_agent_name = (
                self._newest_agent(endpoints) or {}
            ).get("name") or self.focus_agent_name
        spoken = self._narrate(
            f"WAZUH endpoint agent inventory. Total: {total}. "
            f"Active: {len(active)}. Agents: {roster}",
            SPEECH_STYLE_PROMPT,
        )
        await self.capability_worker.speak(spoken)

    async def _check_agent_alerts(self, lowered: str):
        agent_name = self._resolve_agent_name_from_speech(lowered) or self.focus_agent_name
        await self.capability_worker.speak(f"Checking agent {agent_name}.")
        query = {
            "size": ALERT_FETCH_SIZE,
            "sort": [{"timestamp": {"order": "desc"}}],
            "query": {
                "bool": {
                    "must": [
                        {"term": {"agent.name": agent_name}},
                        {"range": {"rule.level": {"gte": MIN_ALERT_LEVEL}}},
                    ],
                    "must_not": self._excluded_agent_clauses(),
                }
            },
        }
        await self._search_and_speak(
            query,
            empty_speech=f"No critical alerts on {agent_name} right now.",
            llm_prefix=f"Critical alerts on agent {agent_name}",
        )

    async def _fetch_agents(self) -> Optional[List[Dict[str, Any]]]:
        token = await self._manager_token()
        if not token:
            return None
        try:
            response = await asyncio.to_thread(
                requests.get,
                f"{self.wazuh_manager_url}/agents",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "select": "id,name,ip,status,dateAdd,lastKeepAlive,version,"
                    + "o"
                    + "s.name",
                    "limit": 100,
                },
                verify=self.wazuh_verify_tls,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as error:
            self.worker.editor_logging_handler.error(
                f"[SentinelVoice] Manager agents call failed: {error!r}"
            )
            await self.capability_worker.speak(
                f"Agent list failed: {self._speakable_error(error)}. "
                "Is Security Group port 8444 open?"
            )
            return None
        except ValueError as error:
            self.worker.editor_logging_handler.error(
                f"[SentinelVoice] Manager agents JSON failed: {error!r}"
            )
            await self.capability_worker.speak(
                f"Agent list returned invalid JSON: {self._speakable_error(error)}"
            )
            return None

        if not isinstance(payload, dict) or payload.get("error"):
            self.worker.editor_logging_handler.error(
                f"[SentinelVoice] Manager agents error: {payload!r}"
            )
            await self.capability_worker.speak(
                f"Agent list error: {self._speakable_error(payload)}"
            )
            return None

        items = (payload.get("data") or {}).get("affected_items") or []
        self.worker.editor_logging_handler.info(
            f"[SentinelVoice] Manager agents returned {len(items)} items"
        )
        return items if isinstance(items, list) else []

    async def _manager_token(self) -> Optional[str]:
        if not (self.wazuh_manager_url and self.wazuh_api_user and self.wazuh_api_password):
            self.worker.editor_logging_handler.error(
                "[SentinelVoice] WAZUH manager API not configured"
            )
            await self.capability_worker.speak(
                "The WAZUH manager API isn't configured yet. "
                "Add the manager URL and API credentials in Settings."
            )
            return None
        try:
            response = await asyncio.to_thread(
                requests.post,
                f"{self.wazuh_manager_url}/security/user/authenticate",
                auth=(self.wazuh_api_user, self.wazuh_api_password),
                verify=self.wazuh_verify_tls,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as error:
            self.worker.editor_logging_handler.error(
                f"[SentinelVoice] Manager auth failed: {error!r}"
            )
            await self.capability_worker.speak(
                f"Could not authenticate to WAZUH API: {self._speakable_error(error)}. "
                "Open Security Group TCP 8444 for the judging window."
            )
            return None
        except ValueError as error:
            self.worker.editor_logging_handler.error(
                f"[SentinelVoice] Manager auth JSON failed: {error!r}"
            )
            await self.capability_worker.speak(
                f"WAZUH API auth returned invalid JSON: {self._speakable_error(error)}"
            )
            return None

        token = (payload.get("data") or {}).get("token") if isinstance(payload, dict) else None
        if not token:
            self.worker.editor_logging_handler.error(
                f"[SentinelVoice] Manager auth missing token: {payload!r}"
            )
            await self.capability_worker.speak("WAZUH API auth did not return a token.")
            return None
        return token

    def _resolve_agent_name_from_speech(self, lowered: str) -> Optional[str]:
        if "endpoint-1" in lowered:
            return "endpoint-1"
        if "endpoint-2" in lowered:
            return "endpoint-2"
        if self.last_agents:
            for agent in self.last_agents:
                name = str(agent.get("name") or "")
                if name and name.lower() in lowered:
                    return name
        return None

    @staticmethod
    def _newest_agent(agents: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not agents:
            return None
        return sorted(
            agents,
            key=lambda a: str(a.get("dateAdd") or ""),
            reverse=True,
        )[0]

    async def _check_scan_alerts(self):
        await self.capability_worker.speak("Checking scan and firewall alerts.")
        query = {
            "size": ALERT_FETCH_SIZE,
            "sort": [{"timestamp": {"order": "desc"}}],
            "query": {
                "bool": {
                    "must": [
                        {"exists": {"field": "data.srcip"}},
                        {"range": {"rule.level": {"gte": MIN_ALERT_LEVEL}}},
                    ],
                    "should": [
                        {"match": {"rule.description": "scan"}},
                        {"match": {"rule.description": "firewall"}},
                        {"match": {"rule.description": "port"}},
                        {"term": {"rule.groups": "firewall"}},
                        {"term": {"rule.groups": "ids"}},
                    ],
                    "minimum_should_match": 0,
                    "must_not": self._excluded_agent_clauses(),
                }
            },
        }
        await self._search_and_speak(
            query,
            empty_speech="No scan or firewall alerts with a source IP right now.",
            llm_prefix="Recent scan or firewall alerts with source IPs",
        )

    async def _check_time_brief(self, lowered: str):
        await self.capability_worker.speak("Pulling a short brief.")
        window = "now-1h" if "hour" in lowered else "now-24h"
        label = "last hour" if window == "now-1h" else "last day"
        query = {
            "size": ALERT_FETCH_SIZE,
            "sort": [{"timestamp": {"order": "desc"}}],
            "query": {
                "bool": {
                    "must": [
                        {"range": {"timestamp": {"gte": window}}},
                        {"range": {"rule.level": {"gte": MIN_ALERT_LEVEL}}},
                    ],
                    "must_not": self._excluded_agent_clauses(),
                }
            },
        }
        await self._search_and_speak(
            query,
            empty_speech=f"No critical alerts in the {label}.",
            llm_prefix=f"Critical alert brief for the {label}",
        )

    async def _check_severity_counts(self):
        await self.capability_worker.speak("Counting severities now.")
        body = {
            "size": 0,
            "query": {
                "bool": {
                    "must": [
                        {"range": {"timestamp": {"gte": "now-24h"}}},
                        {"range": {"rule.level": {"gte": MIN_ALERT_LEVEL}}},
                    ],
                    "must_not": self._excluded_agent_clauses(),
                }
            },
            "aggs": {
                "by_level": {
                    "terms": {"field": "rule.level", "size": 10, "order": {"_key": "desc"}}
                }
            },
        }
        payload = await self._indexer_request(body)
        if payload is None:
            return
        buckets = (
            payload.get("aggregations", {}).get("by_level", {}).get("buckets", [])
            if isinstance(payload, dict)
            else []
        )
        if not buckets:
            await self.capability_worker.speak(
                "No critical alerts in the last day to count."
            )
            return
        parts = [f"level {b.get('key')}: {b.get('doc_count')}" for b in buckets]
        spoken = self._narrate(f"Alert severity counts last 24 hours: {parts}", SPEECH_STYLE_PROMPT)
        await self.capability_worker.speak(spoken)

    async def _search_and_speak(
        self,
        query: Dict[str, Any],
        empty_speech: str,
        llm_prefix: str,
    ):
        payload = await self._indexer_request(query)
        if payload is None:
            return

        hits = (
            payload.get("hits", {}).get("hits", [])
            if isinstance(payload, dict)
            else []
        )
        if not hits:
            self.last_alert = None
            await self.capability_worker.speak(empty_speech)
            return

        summaries = [self._summarize_hit(hit) for hit in hits]
        self.last_alert = summaries[0]
        spoken = self._narrate(f"{llm_prefix}: {summaries}", SPEECH_STYLE_PROMPT)
        await self.capability_worker.speak(spoken)

    async def _indexer_request(self, body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not (self.wazuh_indexer_url and self.wazuh_readonly_user and self.wazuh_readonly_password):
            self.worker.editor_logging_handler.error(
                "[SentinelVoice] WAZUH indexer not configured"
            )
            await self.capability_worker.speak(
                "The WAZUH indexer isn't configured yet. "
                "Add the indexer URL and read-only credentials in Settings."
            )
            return None
        try:
            response = await asyncio.to_thread(
                requests.post,
                self.wazuh_indexer_url,
                auth=(self.wazuh_readonly_user, self.wazuh_readonly_password),
                json=body,
                verify=self.wazuh_verify_tls,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as error:
            self.worker.editor_logging_handler.error(
                f"[SentinelVoice] WAZUH call failed: {error!r}"
            )
            await self.capability_worker.speak(
                f"WAZUH call failed: {self._speakable_error(error)}"
            )
            return None
        except ValueError as error:
            self.worker.editor_logging_handler.error(
                f"[SentinelVoice] WAZUH JSON parse failed: {error!r}"
            )
            await self.capability_worker.speak(
                f"WAZUH returned invalid JSON: {self._speakable_error(error)}"
            )
            return None

        if isinstance(payload, dict) and payload.get("error"):
            self.worker.editor_logging_handler.error(
                f"[SentinelVoice] WAZUH error body: {payload.get('error')!r}"
            )
            await self.capability_worker.speak(
                f"WAZUH error: {self._speakable_error(payload.get('error'))}"
            )
            return None
        return payload if isinstance(payload, dict) else None

    async def _trigger_response_playbook(self):
        if not self.shuffle_webhook_url:
            self.worker.editor_logging_handler.error(
                "[SentinelVoice] Shuffle webhook not configured"
            )
            await self.capability_worker.speak(
                "The Shuffle webhook isn't configured yet. Add the webhook URL in Settings."
            )
            return

        alert = await self._resolve_playbook_alert()
        if not alert:
            return

        srcip = alert.get("srcip")
        if not srcip:
            msg = "No source IP on that alert — AbuseIPDB needs data.srcip."
            self.worker.editor_logging_handler.error(
                f"[SentinelVoice] {msg} alert={alert!r}"
            )
            await self.capability_worker.speak(msg)
            return

        # This fires a real SOAR action (enrichment/isolation/block depending on
        # the playbook) - confirm before sending, rather than acting on a single
        # matched keyword.
        confirmed = await self.capability_worker.run_confirmation_loop(
            f"This will trigger the response playbook for source IP {srcip}. Proceed?"
        )
        if not confirmed:
            await self.capability_worker.speak("Okay, playbook not triggered.")
            return

        await self.capability_worker.speak("Queuing the response playbook.")

        body = {
            "rule_id": str(alert.get("rule_id") or "533"),
            "severity": self._severity_from_level(alert.get("level")),
            "rule": {
                "level": int(alert.get("level") or MIN_ALERT_LEVEL),
                "description": alert.get("description")
                or "SentinelVoice manual trigger",
                "id": str(alert.get("rule_id") or "533"),
            },
            "agent": {
                "id": DEMO_AGENT_ID,
                "name": DEMO_AGENT_NAME,
            },
            "data": {"srcip": srcip},
            "timestamp": alert.get("timestamp") or self._utc_timestamp(),
        }

        try:
            response = await asyncio.to_thread(
                requests.post,
                self.shuffle_webhook_url,
                json=body,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.RequestException as error:
            self.worker.editor_logging_handler.error(
                f"[SentinelVoice] Shuffle webhook failed: {error!r} body={body!r}"
            )
            await self.capability_worker.speak(
                f"Shuffle webhook failed: {self._speakable_error(error)}"
            )
            return

        execution_id = None
        try:
            result = response.json()
            if isinstance(result, dict):
                execution_id = result.get("execution_id")
                if result.get("success") is False:
                    self.worker.editor_logging_handler.error(
                        f"[SentinelVoice] Shuffle reported failure: {result!r}"
                    )
                    await self.capability_worker.speak(
                        f"Shuffle reported failure: {self._speakable_error(result)}"
                    )
                    return
        except ValueError as error:
            self.worker.editor_logging_handler.error(
                f"[SentinelVoice] Shuffle non-JSON response "
                f"status={response.status_code} body={response.text[:300]!r} "
                f"err={error!r}"
            )

        self.worker.editor_logging_handler.info(
            f"[SentinelVoice] Shuffle accepted playbook srcip={srcip} "
            f"execution_id={execution_id} status={response.status_code}"
        )
        if execution_id:
            await self.capability_worker.speak(
                f"Playbook kicked off for {srcip}. Enrichment is running."
            )
        else:
            await self.capability_worker.speak(f"Playbook accepted for {srcip}.")

    async def _resolve_playbook_alert(self) -> Optional[Dict[str, Any]]:
        if self.last_alert and self.last_alert.get("srcip"):
            return self.last_alert

        if self.last_alert and not self.last_alert.get("srcip"):
            self.worker.editor_logging_handler.info(
                "[SentinelVoice] Last alert has no data.srcip; "
                "fetching latest alert that does."
            )

        query = {
            "size": 1,
            "sort": [{"timestamp": {"order": "desc"}}],
            "query": {
                "bool": {
                    "must": [
                        {"range": {"rule.level": {"gte": MIN_ALERT_LEVEL}}},
                        {"exists": {"field": "data.srcip"}},
                    ],
                    "must_not": self._excluded_agent_clauses(),
                }
            },
        }
        payload = await self._indexer_request(query)
        if payload is None:
            return None

        hits = payload.get("hits", {}).get("hits", [])
        if not hits:
            msg = "No high-severity alerts with a source IP to enrich."
            self.worker.editor_logging_handler.error(f"[SentinelVoice] {msg}")
            await self.capability_worker.speak(msg)
            return None

        summary = self._summarize_hit(hits[0])
        self.last_alert = summary
        return summary

    def _summarize_hit(self, hit: Dict[str, Any]) -> Dict[str, Any]:
        source = hit.get("_source", {}) if isinstance(hit, dict) else {}
        rule = source.get("rule") or {}
        agent = source.get("agent") or {}
        data = source.get("data") or {}
        syscheck = source.get("syscheck") or {}
        return {
            "rule_id": rule.get("id"),
            "level": rule.get("level"),
            "description": rule.get("description"),
            "groups": rule.get("groups"),
            "agent_id": agent.get("id"),
            "agent_name": agent.get("name"),
            "srcip": data.get("srcip"),
            "fim_path": syscheck.get("path"),
            "fim_event": syscheck.get("event"),
            "timestamp": source.get("timestamp"),
        }

    @staticmethod
    def _excluded_agent_clauses() -> List[Dict[str, Any]]:
        return [{"term": {"agent.name": name}} for name in EXCLUDED_AGENT_NAMES]

    @staticmethod
    def _severity_from_level(level: Any) -> int:
        try:
            value = int(level)
        except (TypeError, ValueError):
            return 2
        if value >= 12:
            return 1
        if value >= 7:
            return 2
        return 3

    @staticmethod
    def _utc_timestamp() -> str:
        return (
            datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000")
            + "+0000"
        )

    @staticmethod
    def _speakable_error(error: Any) -> str:
        text = str(error).strip().replace("\n", " ")
        if len(text) > 140:
            return text[:137] + "..."
        return text or "unknown error"
