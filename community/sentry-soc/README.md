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
5. Nothing is hardcoded in `main.py` — in the OpenHome Dashboard, go to **Settings -> API Keys** and add these (names must match exactly):

| API Key name | What it is |
|---|---|
| `wazuh_indexer_url` | Full indexer search URL, e.g. `https://YOUR_WAZUH_HOST:8443/wazuh-alerts-*/_search` |
| `wazuh_readonly_user` | Read-only indexer user |
| `wazuh_readonly_password` | Read-only indexer password |
| `wazuh_manager_url` | Manager API base URL, e.g. `https://YOUR_WAZUH_HOST:8444` |
| `wazuh_api_user` | Read-only manager API user |
| `wazuh_api_password` | Read-only manager API password |
| `shuffle_webhook_url` | Shuffle webhook URL for the response playbook |
| `wazuh_verify_tls` (optional) | Set to `false` only if the indexer/manager use a self-signed cert you accept the risk of not validating. Defaults to verifying TLS certs. |

Alerts/agent-inventory/playbook features degrade independently — e.g. alerts still work without the manager or Shuffle keys configured.

6. Upload this folder via the OpenHome Live Editor or `openhome push community/sentry-soc`.
7. Suggested triggers: `Sentry`, `check alerts`, `FIM changes`, `connected agents`, `run response playbook`.

---

## Notes

- Indexer queries and Shuffle calls run from the OpenHome cloud sandbox (outbound HTTPS/HTTP).
- TLS certs are verified by default; only disable via `wazuh_verify_tls` if you understand the MITM risk on a self-signed setup.
- `run response playbook` asks for a yes/no confirmation before it fires — it triggers a real SOAR action.
- Do not commit real credentials. Credentials live only in OpenHome's API Key store, never in source.
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
