# Town Hall — Voice Civic Briefing Platform

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@ileana--pr-lightgrey?style=flat-square)

A voice-activated civic briefing ability for OpenHome. Ask your agent what's happening in local and state government and get a spoken summary of upcoming meetings, active legislation, and public agendas — pulled live from official government sources.

**Town Hall is designed to be extended.** Virginia and Richmond, VA are the reference implementations. The architecture is built so any developer can add a source for their city, county, state, or federal body by implementing a single Python class.

---

## Trigger Words

| Phrase | What it does |
| --- | --- |
| `"virginia state"` | Virginia General Assembly **meetings** briefing |
| `"state of virginia"` | same meetings briefing |
| `"virginia legislature"` | same meetings briefing |
| `"virginia legislation"` | Virginia **bills** list (LIS API, CSV fallback) |
| `"richmond city"` | Richmond City Council meetings briefing |
| `"richmond city council"` | same meetings briefing |
| `"richmond legislation"` | pending Richmond ordinances and resolutions |
| `"seattle city"` / `"seattle legislation"` | Seattle City Council (Legistar) |
| `"oakland city"` / `"oakland legislation"` | Oakland City Council (Legistar) |
| `"boston city"` / `"boston legislation"` | Boston City Council (Legistar) |
| `"denver city"` / `"denver legislation"` | Denver City Council (Legistar) |
| `"baltimore city"` / `"baltimore legislation"` | Baltimore City Council (Legistar) |
| `"phoenix city"` / `"phoenix legislation"` | Phoenix City Council (Legistar) |
| `"pittsburgh city"` / `"pittsburgh legislation"` | Pittsburgh City Council (Legistar) |
| `"san jose city"` / `"san jose legislation"` | San Jose City Council (Legistar) |
| `"town hall"` | asks which briefing you want, then delivers it |
| `"configure topics"` | opens interactive topic preference configuration |
| `"set topics"` | opens interactive topic preference configuration |
| `"remove topics"` | remove specific topics (or clear all) from preferences |
| `"delete topics"` | same as remove topics |
| `"clear topics"` | same as remove topics |

Naming a jurisdiction in the trigger skips straight to that briefing — no confirmation step. The generic `"town hall"` trigger is the only one that asks which source you want. Topic configuration runs **only** when you use the topic trigger words (never prompted automatically after a briefing).

---

## Current Sources

| Source | Level | Auth |
| --- | --- | --- |
| Virginia General Assembly (LIS) | State | `LIS_API_KEY` preferred; meetings fall back to public ICS, bills to public `BILLS.CSV` |
| Richmond City Council (Legistar) | City | none |
| Seattle City Council (Legistar) | City | none |
| Oakland City Council (Legistar) | City | none |
| Boston City Council (Legistar) | City | none |
| Denver City Council (Legistar) | City | none |
| Baltimore City Council (Legistar) | City | none |
| Phoenix City Council (Legistar) | City | none |
| Pittsburgh City Council (Legistar) | City | none |
| San Jose City Council (Legistar) | City | none |

### Planned Sources

| Source | Level | Status |
| --- | --- | --- |
| U.S. Congress (congress.gov API) | Federal | planned |
| More Legistar cities (Sacramento, Long Beach, San Antonio, King County, …) | City / County | deferred |

> Want to add your city, county, or state? See [Contributing a Source](#contributing-a-source) below.

---

## Setup

### 1. Dependencies

None. All data comes from public web APIs over plain HTTP using the OpenHome SDK — no external Python packages or system utilities required. The ability runs identically on the OpenHome cloud platform and in local development.

### 2. Trigger words

Set at least one of the trigger phrases listed above in the Dashboard when you install the ability.

### 3. LIS API key (recommended for Virginia)

The Virginia source prefers the LIS REST API for meetings and bills. Without a key it still works via public fallbacks (ICS calendar + `BILLS.CSV`), but the API is fresher when available:

1. Register for a free key at [lis.virginia.gov/developers](https://lis.virginia.gov/developers).
2. In the OpenHome Dashboard, go to **Settings → Third-Party Keys** and add:
   - **Label:** `LIS_API_KEY`
   - **Value:** your key (`XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX`)

The ability logs `LIS_API_KEY resolved successfully` on startup if the key is found.

---

## Usage Examples

- *"Virginia state."* → upcoming GA / committee meetings, then optional meeting-details offer
- *"Virginia legislation."* → active bills, then optional bill-details offer
- *"Richmond city."* → Richmond meetings, then optional meeting-details offer
- *"Richmond legislation."* → ordinances/resolutions, then optional item-details offer
- *"Town hall."* → *"Which briefing would you like?"*
- *"Configure topics."* / *"Remove topics."* → topic preference management (trigger-only)
- *"Get details on meeting 1."* / *"Tell me about HB 1234."* → direct details lookup

---

## How It Works

### Scenario 1: Direct Trigger with Keyword

**User says:** *"Richmond city"*

**What happens:**

1. **Trigger routing** — "richmond" routes to the Richmond City Council source
2. **Fetch live data** — Legistar Web API for upcoming meetings
3. **Format briefing** — Numbered meetings with date/time
4. **Cache** — Writes `townhall_briefing.md`
5. **LLM summarization** — 4–6 spoken sentences
6. **One-turn details offer** — *"Would you like details on a meeting? Say the meeting number, or say no."* One listen, then exit (no multi-turn loop)

**Example spoken output:**
> "There are 8 upcoming meetings this week. The City Council meets Monday…"  
> **Agent:** "Would you like details on a meeting? Say the meeting number, or say no."  
> **User:** "Meeting 1"  
> **Agent:** *(agenda highlights)*  
> *(session ends)*

**Behind the scenes:**
```
User: "richmond city"
  ↓
RichmondCitySource.fetch_updates()
  ↓
Cache → townhall_briefing.md → spoken summary
  ↓
One-turn details offer → get_details() or exit
```

---

### Scenario 2: Virginia meetings (town-hall style)

**User says:** *"Virginia state"*

**What happens:**

1. **Meetings first** — `fetch_updates()` tries `GetPartnerScheduleListAsync` with `LIS_API_KEY`
2. **ICS fallback** — If the API fails or returns nothing usable, parse `https://liscdn.blob.core.windows.net/cdn/meetings.ics`
3. **Numbered list** — Upcoming committee / commission meetings
4. **Cue** — Mentions `virginia legislation` for bills
5. **One-turn details offer** — same meeting-details pattern as Richmond

**Example:**
> **Agent:** "There are several upcoming General Assembly committee meetings…"  
> **Agent:** "Would you like details on a meeting? Say the meeting number, or say no."  
> **User:** "No."  
> **Agent:** "Okay."

---

### Scenario 3: Virginia legislation

**User says:** *"Virginia legislation"*

**What happens:**

1. **Bills list** — LIS legislation API for the current session; on key/API failure uses public `BILLS.CSV` for that session code
2. **Topic filter** — Prioritizes user topics (or housing/education/zoning defaults), caps at 8
3. **One-turn details offer** — *"Want details on a specific item? Say the bill or ordinance name, or say no."*
4. **Bill details** — `get_details("HB 1234")` from the cached list (description, status, patron, summary fields when present)

---

### Scenario 4: Generic Trigger (No Keyword)

**User says:** *"Town hall"*

1. Agent asks: *"Which briefing would you like?"*
2. User names a jurisdiction → same flow as Scenarios 1–3
3. Unknown locality → graceful gap message

---

### Scenario 5: Missing / rejected LIS API key

Meetings and legislation still attempt public fallbacks:

- Meetings → ICS
- Legislation → `https://lis.blob.core.windows.net/lisfiles/{SessionCode}/BILLS.CSV`

If both API and fallback fail, the agent speaks a short unavailable message (no crash).

---

### Scenario 6: Setting Topic Preferences

**User says:** *"Configure topics"* (or *"set topics"*)

Topic setup is **trigger-only** — the agent does **not** ask to set topics after a normal briefing.

1. Ask for free-form topics (or what to add if some already exist)
2. Append to the user-level list
3. Apply across sources that support filtering

**Remove topics** / **delete topics** / **clear topics** remain separate triggers.

---

### Scenario 7: Getting Meeting Details

After a meetings briefing, accept the one-turn offer **or** start a new utterance:

- `"Get details on meeting 1"`
- `"Tell me about City Council"` (Richmond)
- `"Tell me about House Appropriations"` (Virginia, when that title was listed)

Richmond uses Legistar event items. Virginia uses cached schedule/ICS fields, and `GetPartnerSchedulebyIdAsync` when an id and API key are available.

---

### Scenario 8: Richmond Legislation Tracking

**User says:** *"Richmond legislation"*

Same Legistar matters flow as before, then the **one-turn details offer** for a specific ORD/RES (not a multi-turn “anything else?” loop).

### Caching and Watchdog Loop

**Background process (runs automatically on startup):**

1. **Warm cache immediately** — 3 seconds after the ability loads, fetch all sources once
2. **Refresh daily** — Every 24 hours, re-fetch all sources and update `townhall_briefing.md`
3. **Cache validation** — Before serving a cached briefing, each source validates its section isn't all error messages

**Why cache?**
- Government APIs can be slow (1–3 seconds per call)
- Voice interactions need instant responses
- Briefings are time-insensitive (hourly changes are fine)

**Cache invalidation:**
- If a source's cached section contains only error lines, it's considered invalid
- Invalid cache → fresh fetch is triggered
- Otherwise, cached briefing is served immediately

---

## Architecture

Town Hall is built around a `CivicSource` base class. Each source is an independent module that knows how to fetch and format updates from one government body. The core ability just loops over registered sources and aggregates their output.

```
community/town-hall/
├── main.py                  # ability entry point, watchdog loop, LIS key resolution
├── sources/
│   ├── base.py              # CivicSource abstract base class — start here to contribute
│   ├── legistar.py          # LegistarCitySource parent for Granicus Legistar cities
│   ├── __init__.py          # register your source here (discover_sources)
│   ├── virginia_state.py    # reference: Virginia General Assembly (state legislature)
│   ├── richmond_va.py       # Richmond City Council (Legistar)
│   ├── seattle_wa.py        # …and other thin Legistar city subclasses
│   └── …
└── README.md
```

### CivicSource interface

```python
class CivicSource(ABC):
    def get_name(self) -> str: ...           # display name, e.g. "Virginia General Assembly"
    def get_source_url(self) -> str: ...     # canonical URL for the data source
    async def fetch_updates(self) -> str:    # returns a markdown-formatted briefing string
        ...
    # optional features — base class provides default stubs; override where available
    async def search(self, query: str) -> str: ...
    async def get_details(self, item_id: str) -> str: ...
    async def fetch_legislation(self) -> str: ...
    def set_topic_preferences(self, topics: list[str]) -> None: ...
    def get_topic_preferences(self) -> list[str]: ...
```

HTTP helpers (`_http_get`, `_http_post`) are available on the base class via the OpenHome SDK (`worker.session_tasks`). Call `bind_worker()` first (the coordinator does this automatically).

### Watchdog loop

On startup, Town Hall warms the briefing cache immediately, then refreshes daily. Briefings are written to `townhall_briefing.md` in the agent's context directory so responses are instant even when sources are slow.

---

## Contributing a Source

We welcome sources for any city, county, state, or federal body. The pattern is the same regardless of jurisdiction.

### Steps

1. Fork this repo and branch off `dev`:
   ```bash
   git checkout -b add-your-source-name dev
   ```

2. Create `sources/your_source.py` and subclass `CivicSource`:
   ```python
   from .base import CivicSource

   class YourCitySource(CivicSource):
       def get_name(self) -> str:
           return "Your City Council"

       def get_source_url(self) -> str:
           return "https://yourcity.gov/calendar"

       async def fetch_updates(self) -> str:
           # http calls are synchronous, but fetch_updates must stay async
           resp = self._http_get(self.get_source_url())
           # parse resp.text, return a markdown string
           return "### Your City Council\n- ..."
   ```

3. Register your source in `sources/__init__.py` by importing it and appending an instance to the list returned by `discover_sources()`. (OpenHome forbids dynamic imports, so registration is explicit.)

4. If your source needs an API key, follow the same pattern as `virginia_state.py` — accept the key via `set_api_key()` and document the label name in your source's docstring and in this README.

5. Open a PR against `dev` on `openhome-dev/abilities`. See the [contribution guide](https://docs.openhome.com/community/contributing) for the full checklist.

### Source guidelines

- Return a markdown string from `fetch_updates()` — the agent's LLM converts it to speech.
- Keep the output concise: 5–10 bullet points max. This is a voice briefing, not a report.
- Use `self._http_get()` for all HTTP calls — the base class routes through the OpenHome SDK (`worker.session_tasks`) and returns response-like objects with `.text` and `.status_code`.
- Surface errors as strings in the return value (e.g. `"Error fetching ... HTTP 403"`) rather than raising — the briefing aggregator will include them so the agent can report and debug.
- No `print()` — logging is available via the platform when needed.
- No hardcoded API keys — use placeholders and document the key label in the README.

---

## Developer Notes

- **Adding a federal source** — U.S. Congress data is available via the [congress.gov API](https://api.congress.gov/) (free key). A `FederalCongressSource` following the same pattern is on the roadmap.
- **Adding more city sources** — Subclass `LegistarCitySource` in `sources/legistar.py` with a city `client_id` (the subdomain before `.legistar.com`), then register it in `sources/__init__.py`.
- **Knowledge gaps** — when a source returns no usable data, it is logged to `knowledge_gaps.json` in the ability directory. Review this to see which jurisdictions are failing and prioritize fixes.
