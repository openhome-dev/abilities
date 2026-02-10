# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in an OpenHome Ability, **please do NOT open a public issue.**

Instead, email **security@openhome.xyz** with:

1. Description of the vulnerability
2. Steps to reproduce
3. Potential impact
4. Affected ability name(s)

We will respond within **48 hours** and work with you on a fix.

## Security Review for Community Abilities

All community abilities are reviewed for:

- **No hardcoded secrets** — API keys, tokens, passwords
- **No dangerous imports** — `subprocess`, `os.system`, `eval()`, `exec()`
- **No network exfiltration** — unauthorized data transmission
- **No file system abuse** — reading/writing outside ability scope
- **SDK compliance** — proper use of CapabilityWorker API

## Responsible Disclosure

We follow responsible disclosure. Security researchers who report valid
vulnerabilities will be credited in our security advisories (unless they
prefer anonymity).
