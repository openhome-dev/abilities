# SentinelRed (Spectre)

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![RedTeam](https://img.shields.io/badge/Mode-Red%20Recon-red?style=flat-square)
![LocalLink](https://img.shields.io/badge/Bridge-local--link-blue?style=flat-square)

> Voice-driven **red-team recon** Ability for OpenHome. OSINT → DNS → cert search → nmap → HTTP fingerprint → spoken vulnerability brief. Active scans run only on an **allowlisted** lab target via `openhome local` (local-link).

**Separate from Blue (`sentinel-voice`).** Upload this folder on its own.

---

## What it does

| You say | What happens | Where it runs |
|---|---|---|
| set target scanme / algoryc / hackathon | Lock allowlisted target | Memory |
| IP OSINT / who owns this IP | Geo/ISP/ASN lookup | Cloud → ip-api.com |
| DNS lookup / resolve | `dig` / `host` | **local-link** |
| certificate search / subdomains | Certificate transparency | Cloud → crt.sh |
| quick scan / open ports | `nmap --top-ports 20` | **local-link** |
| service scan / version scan | `nmap -sV --top-ports 15` | **local-link** |
| HTTP fingerprint | `curl -I` headers | **local-link** |
| vulnerability brief / risks | Spoken hardening brief from last data | LLM (no exploits) |
| tell me more | Expand last finding | LLM |
| help | Spoken menu | — |
| done | Exit | — |

Persona name when speaking: **Spectre**.

---

## Safety (judges will ask)

- **Allowlist only** — default: lab Windows agents, `127.0.0.1`, `scanme.nmap.org`, team EC2 IP
- **Fixed command templates** — never LLM-generated shell
- **`BLOCKED_KEYWORDS`** checked on every user utterance and before every `exec_local_command`
- Vuln brief is **defensive** (hardening), not exploit steps
- No Metasploit / brute-force / exploit tooling

Edit allowlist in `main.py`:

```python
TARGET_ALIASES = {...}
ALLOWED_TARGETS = {...}
```

---

## Prerequisites (friend laptop)

1. Install CLI bridge (repo root):

```bash
python3 -m venv cli/.venv && source cli/.venv/bin/activate
pip install -e cli
openhome login --api-key <KEY>
openhome local start          # leave running
openhome local status         # must show connected + local-link
```

2. On the **same machine** as the bridge:

```bash
sudo apt install -y nmap dnsutils curl
which nmap dig host curl
```

3. Upload this folder via OpenHome Dashboard Live Editor (or `openhome push community/sentinel-red`).

4. Suggested triggers:

`Spectre`, `start recon`, `red team`, `scan this host`, `OSINT`, `vulnerability brief`

---

## Demo script (~90 sec)

1. **“Spectre”** (trigger)  
2. **“Set target scanme”** → *Target locked: scanme.nmap.org*  
3. **“IP OSINT”** → spoken geo/ASN  
4. **“Quick scan”** → open ports (needs local-link + nmap)  
5. **“Vulnerability brief”** → hardening summary  
6. **“I'm done”**

Lab alternate: **“Set target hackathon”** or **“algoryc”** (must be reachable from the bridge laptop).

---

## Relationship to Blue

| | Blue (`sentinel-voice`) | Red (`sentinel-red`) |
|---|---|---|
| Persona | Sentry | Spectre |
| Data | WAZUH + Shuffle | OSINT APIs + local nmap |
| Network | Cloud → AWS EC2 | Cloud OSINT + **local-link** for scans |

Keep them as **two Abilities** with different triggers so Blue stays stable while Red is developed.
