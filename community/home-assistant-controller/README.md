# API Template

For Abilities that call an external API and speak the result.

**Speak → Collect input → Call API → Speak result → Exit**

## When to Use This

- Weather lookups
- Stock prices
- Sports scores
- Any "fetch and tell" pattern

## How to Customize

1. Copy this folder to `community/your-ability-name/`
2. Replace `API_URL` and `API_HEADERS` with your API details
3. Update `fetch_data()` to parse your API's response format
4. Upload to OpenHome and set your trigger words in the dashboard
5. Replace any API keys with `YOUR_API_KEY_HERE` placeholders before submitting

## Flow

```
Ability triggered by hotword
    → Asks what to look up
    → Waits for user input
    → Calls external API
    → Uses LLM to summarize result into spoken response
    → Speaks the response
    → Returns to normal Personality flow
```

## Notes

- Always use `requests` for HTTP calls (recommended by OpenHome)
- Always wrap API calls in try/except
- Always log errors with `self.worker.editor_logging_handler`
- Never hardcode production API keys — use placeholders

---

## Home Assistant Controller — Setup & Local Test

### Config

Create `ha_config.json` (in OpenHome file storage at runtime; for local test, place it in this folder) with:

- `ha_url`: your Home Assistant URL (e.g. `http://localhost:8123`)
- `ha_token`: Long-Lived Access Token from HA (Profile → Long-Lived Access Tokens)

### Local test (no OpenHome)

To verify HA connection and token without running the full ability:

```bash
cd community/home-assistant-controller
pip install -r requirements.txt
python test_ha_local.py
```

This checks `GET /api/` and `GET /api/states` and prints entity count and sample lights.
