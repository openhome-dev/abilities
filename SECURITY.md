# Security Policy

## Reporting a Vulnerability

**Do NOT open a public GitHub issue for security vulnerabilities.**

Email **security@openhome.xyz** with:

- Description of the vulnerability
- Steps to reproduce
- Affected Ability (name + path in repo)
- Potential impact (data exposure, arbitrary execution, etc.)

### Response Timeline

| Severity | Acknowledgment | Fix Target |
|----------|---------------|------------|
| Critical | 24 hours | 7 days |
| High | 48 hours | 14 days |
| Medium | 5 business days | 30 days |
| Low | 10 business days | Next release |

## Supported Versions

| Branch | Supported |
|--------|-----------|
| `main` | ✅ |
| `dev` | ✅ (pre-release) |
| Older tags | ❌ |

## What We Scan For

Every community Ability PR is reviewed against these criteria before merge:

### Prohibited Patterns

- **Hardcoded secrets**: No API keys, tokens, passwords, or credentials in source code
- **Dynamic code execution**: No `eval()`, `exec()`, `compile()`, `__import__()`, or `importlib` usage
- **Shell access**: No `os.system()`, `subprocess.*`, `os.popen()`, or backtick execution
- **File system abuse**: No reads/writes outside the Ability's own directory
- **Network exfiltration**: No undocumented outbound HTTP requests; all external API calls must be declared in the Ability's README
- **Pickle/deserialization**: No `pickle.loads()`, `yaml.load()` (without SafeLoader), or `marshal.loads()`
- **Prompt injection vectors**: No user input passed unsanitized into system-level prompts via `text_to_text_response()`

### Required Patterns

- All Abilities must use the `CapabilityWorker` SDK — direct platform internals access is forbidden
- `register_capability()` must load from `config.json` only (no custom config file paths)
- `resume_normal_flow()` must be called on every exit path to return control to the Personality

## Security Best Practices for Contributors

1. Use environment variables or the OpenHome dashboard's API key settings for secrets — never commit them
2. Validate and sanitize all input from `user_response()` before passing it to APIs or LLM prompts
3. Scope all file operations to `os.path.dirname(os.path.abspath(__file__))`
4. Document every external API call in your Ability's README, including what data is sent
5. Pin dependency versions if your Ability requires external packages

## Scope

This policy covers all code in the `openhome-dev/abilities` repository:

- `official/` — maintained by OpenHome
- `community/` — contributed by the community
- `templates/` — starter code
- `validate_ability.py` — CI validation script
- `.github/workflows/` — CI/CD pipelines
