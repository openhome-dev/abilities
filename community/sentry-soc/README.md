# Sentry SOC

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![SIEM](https://img.shields.io/badge/SIEM-WAZUH-blue?style=flat-square)
![SOAR](https://img.shields.io/badge/SOAR-Shuffle-green?style=flat-square)

> Voice-driven security operations assistant for OpenHome. Ask for live WAZUH alerts, agent inventory, FIM events, scan activity, and trigger a Shuffle response playbook — all by voice.

---

## What it does

| You say | What happens |
|---|---|
| check alerts / critical | High-severity WAZUH alerts |
| how many agents / connected agents | Manager API agent roster |
| new agent / newest agent | Newest endpoint agent details |
| Windows agent / endpoint-1 | Alerts for a named agent |
| any FIM changes / file integrity | Syscheck / FIM alerts |
| any scan activity | Alerts that include `data.srcip` |
| last hour / today's brief | Time-bounded critical brief |
| how bad is it | Severity counts |
| tell me more | Expand last alert |
| run response playbook | POST alert-shaped JSON to Shuffle |
| help | Spoken menu |

Persona: **Sentry**.

---

## Setup

1. Deploy a reachable WAZUH indexer (HTTPS) and optionally the manager API.
2. Create a **read-only** indexer user scoped to `wazuh-alerts-*`.
3. Create a **read-only** manager API user (e.g. `agents_readonly`).
4. Point a Shuffle webhook at a playbook that reads WAZUH-shaped JSON (`data.srcip`, `agent`, `rule`, …).
5. Edit placeholders at the top of `main.py`:

```python
WAZUH_INDEXER_URL = "https://YOUR_WAZUH_HOST:8443/wazuh-alerts-*/_search"
WAZUH_READONLY_USER = "YOUR_READONLY_USER"
WAZUH_READONLY_PASSWORD = "YOUR_READONLY_PASSWORD"
WAZUH_MANAGER_URL = "https://YOUR_WAZUH_HOST:8444"
WAZUH_API_USER = "YOUR_API_USER"
WAZUH_API_PASSWORD = "YOUR_API_PASSWORD"
SHUFFLE_WEBHOOK_URL = "https://YOUR_SHUFFLE_HOST/api/v1/hooks/YOUR_HOOK_ID"
```

6. Upload this folder via the OpenHome Live Editor or `openhome push community/sentry-soc`.
7. Suggested triggers: `Sentry`, `check alerts`, `FIM changes`, `connected agents`, `run response playbook`.

---

## Notes

- Indexer queries and Shuffle calls run from the OpenHome cloud sandbox (outbound HTTPS/HTTP).
- Self-signed indexer certs may require `verify=False` (demo shortcut only).
- Do not commit real credentials. Keep secrets out of git.
- FIM works best with a realtime-monitored demo folder on Windows agents (`syscheck`).

---

## Example conversation

User: "Sentry, check alerts"  
OpenHome: "Checking WAZUH now." → spoken critical summary  

User: "Any FIM changes?"  
OpenHome: spoken file integrity events  

User: "Run response playbook"  
OpenHome: "Playbook kicked off for …"  

User: "I'm done"  
OpenHome: "Standing down."
