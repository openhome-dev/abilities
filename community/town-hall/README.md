# Town Hall — Voice Civic Briefing Platform

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@ileana--pr-lightgrey?style=flat-square)

A voice-activated civic briefing ability for OpenHome. Ask your agent what's happening in local and state government and get a spoken summary of upcoming meetings, active legislation, and public agendas — pulled live from official government sources.

**Town Hall is designed to be extended.** Virginia (LIS) and Legistar cities (Richmond plus major U.S. cities) are the reference implementations. Add another city, county, state, or federal body by implementing a single Python class.

---

## Trigger Words

| Phrase | What it does |
| --- | --- |
| `"virginia state"` | Virginia General Assembly **meetings** briefing |
| `"state of virginia"` | same meetings briefing |
| `"virginia legislature"` | same meetings briefing |
| `"virginia legislation"` | Virginia **bills** list (LIS API, CSV fallback) |
| `"richmond city"` / `"richmond city council"` | Richmond City Council meetings |
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
| `"configure topics"` / `"set topics"` | add topic preferences (shared across sources) |
| `"remove topics"` / `"delete topics"` / `"clear topics"` | remove topics or clear the list |

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

The ability logs when `LIS_API_KEY` is resolved on startup.

---

## Usage Examples

| You say | What you get |
| --- | --- |
| *"Virginia state."* | Upcoming GA / committee meetings, then optional details follow-ups |
| *"Virginia legislation."* | Active bills, then optional bill-details follow-ups |
| *"Richmond city."* | Richmond meetings (Legistar), then optional details follow-ups |
| *"Richmond legislation."* | Ordinances / resolutions, then optional item details |
| *"Seattle city."* / *"Boston legislation."* | Same pattern for any registered Legistar city |
| *"Town hall."* | *"Which briefing would you like?"* → name a jurisdiction |
| *"Configure topics."* / *"Set topics."* | Add free-form topic preferences |
| *"Remove topics."* / *"Clear topics."* | Remove some or all saved topics |
| *"Details on meeting 1."* / *"Tell me about HB 1234."* | Direct details when a jurisdiction is in the phrase or session |

After a meetings or legislation briefing, the agent offers details, then may ask *"Anything else?"* for a few short follow-ups (or say *"done"* to exit). You can also name another jurisdiction in that window to switch briefings.

---

## How It Works

### Scenario 1: City meetings briefing (Legistar)

**User says:** *"Richmond city"* (or Seattle, Oakland, Boston, Denver, Baltimore, Phoenix, Pittsburgh, San Jose)

**What happens:**

1. **Trigger routing** — keyword matches the city source (e.g. `"richmond"` → Richmond City Council)
2. **Fetch meetings** — Legistar Web API `/events` (with cache warm via watchdog)
3. **Spoken summary** — short list from numbered meeting lines (no LLM for meetings)
4. **Details offer** — *"Would you like details on a meeting? Say the meeting number or name, or say done."*
5. **Short follow-ups** — up to a few turns; after each lookup, *"Anything else?"* or say *"done"*

**Example:**
> **Agent:** "Here are upcoming meetings for Richmond City Council. City Council, Monday…"  
> **Agent:** "Would you like details on a meeting? Say the meeting number or name, or say done."  
> **User:** "Meeting 1"  
> **Agent:** *(agenda highlights from Legistar event items)*  
> **Agent:** "Anything else? Say another meeting number or name, or say done."  
> **User:** "Done."  
> **Agent:** "Okay."

**Behind the scenes:**
```
User: "richmond city"
  ↓
RichmondCitySource.fetch_meetings()  (via LegistarCitySource)
  ↓
Cache → townhall_meetings.md → spoken summary
  ↓
Details offer → get_details() → optional "anything else?" → exit
```

---

### Scenario 2: Virginia meetings

**User says:** *"Virginia state"*

**What happens:**

1. **Meetings first** — `GetPartnerScheduleListAsync` when `LIS_API_KEY` is available
2. **ICS fallback** — If the API fails or returns nothing usable, parse `https://liscdn.blob.core.windows.net/cdn/meetings.ics`
3. **Numbered list** — Upcoming committee / commission meetings
4. **Cue** — Briefing text mentions `virginia legislation` for bills
5. **Details offer + follow-ups** — same pattern as city meetings; Virginia details use schedule/ICS fields (and partner-by-id when key + id exist)

**Example:**
> **Agent:** "Here are upcoming meetings for Virginia General Assembly…"  
> **Agent:** "Would you like details on a meeting? Say the meeting number or name, or say done."  
> **User:** "No." / *"Done."*  
> **Agent:** "Okay."

---

### Scenario 3: Legislation (Virginia or Legistar city)

**User says:** *"Virginia legislation"* or *"Seattle legislation"* / *"Richmond legislation"*

**What happens:**

1. **List** — Virginia: LIS bills API (CSV fallback). Legistar cities: `/matters` filtered by that city's ordinance/resolution types
2. **Topic filter** — Prioritizes the user's saved topics when present
3. **Spoken summary** — LLM summary grounded in the fetched list
4. **Details offer** — *"Want details on a specific item? Say the bill or ordinance name, or say done."*
5. **Follow-ups** — e.g. `"HB 1234"`, `"ORD. 2026-172"`, or another item; then *"Anything else?"*

---

### Scenario 4: Generic trigger (no jurisdiction)

**User says:** *"Town hall"*

1. Agent asks: *"Which briefing would you like?"*
2. User names a supported jurisdiction → same flow as Scenarios 1–3
3. Unknown locality → graceful message (try a supported city/state, or try again later as sources are added)

---

### Scenario 5: Empty calendar

If the live feed has no upcoming meetings in the briefing window:

> **Agent:** "There are no upcoming meetings on the calendar for Seattle City Council right now."

Session ends (no details offer).

---

### Scenario 6: Missing / rejected LIS API key

Virginia meetings and legislation still attempt public fallbacks:

- Meetings → ICS
- Legislation → `https://lis.blob.core.windows.net/lisfiles/{SessionCode}/BILLS.CSV`

If both API and fallback fail, the agent speaks a short unavailable message (no crash). Legistar cities do not need a key.

---

### Scenario 7: Topic preferences (trigger-only)

**Add / configure** — *"Configure topics"* or *"Set topics"*

1. Agent reads any existing list, then asks for free-form topics (e.g. housing, zoning, parks)
2. New topics are **appended** to the user-level list
3. Preferences apply across sources that support filtering

**Remove** — *"Remove topics"* / *"Delete topics"* / *"Clear topics"*

1. Agent lists current topics
2. User names topics to drop, or clears all
3. Remaining list is saved and pushed to sources

Topics are **never** prompted after a normal briefing — only via these triggers.

---

### Scenario 8: Meeting or item details

**After a briefing** (accept the details offer), **or** in a new utterance that includes a jurisdiction:

- `"Details on meeting 1"`
- `"Tell me about City Council"` (Legistar body name)
- `"Tell me about House Appropriations"` (Virginia, when that title was listed)
- `"ORD. 2026-172"` / `"HB 1234"` (legislation)

Legistar cities use event items from the Web API. Virginia uses cached schedule/ICS fields, and `GetPartnerSchedulebyIdAsync` when an id and API key are available.

---

### Scenario 9: Switch jurisdiction mid-follow-up

During the details / "anything else?" window, naming another registered source starts that briefing instead of answering against the wrong document:

> **User:** *(after a Virginia briefing)* "What about Seattle?"  
> **Agent:** *(Seattle meetings flow)*

---

### Caching and Watchdog Loop

**Background process (runs automatically on startup):**

1. **Warm cache** — a few seconds after the ability loads, fetch all sources once
2. **Refresh daily** — every 24 hours, re-fetch and write `townhall_meetings.md` (meetings only; never legislation)
3. **Cache validation** — before serving a cached section, each source must have a usable (non-error) section

**Why cache?**
- Government APIs can be slow
- Voice interactions need quick responses
- Meeting calendars do not need second-by-second freshness

**Cache invalidation:**
- Legacy `townhall_briefing.md` is deleted on fetch so old shared cache cannot poison results
- Invalid / error-only sections force a fresh fetch for that source

---

## Architecture

Town Hall is built around a `CivicSource` base class. Each source is an independent module that knows how to fetch and format updates from one government body. The core ability loops over registered sources and aggregates their output.

```
community/town-hall/
├── main.py                  # ability entry point, watchdog, routing, details offer
├── sources/
│   ├── base.py              # CivicSource abstract base class — start here to contribute
│   ├── legistar.py          # LegistarCitySource parent for Granicus Legistar cities
│   ├── __init__.py          # must stay empty (repo lint rule)
│   ├── registry.py          # register your source here (discover_sources)
│   ├── virginia_state.py    # Virginia General Assembly (LIS)
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

On startup, Town Hall warms the meetings cache immediately, then refreshes daily. Briefings are written to `townhall_meetings.md` in the agent's context directory so responses stay fast when sources are slow.

---

## Contributing a Source

We welcome sources for any city, county, state, or federal body. The pattern is the same regardless of jurisdiction.

### Steps

1. Fork this repo and branch off `dev`:
   ```bash
   git checkout -b add-your-source-name dev
   ```

2. Create `sources/your_source.py` and subclass `CivicSource` (or `LegistarCitySource` for Granicus Legistar):
   ```python
   from .legistar import LegistarCitySource

   class YourCitySource(LegistarCitySource):
       def __init__(self):
           super().__init__(
               client_id="yourclient",
               display_name="Your City Council",
               trigger_keywords=("yourcity",),
               priority_bodies=("City Council",),
           )
   ```

3. Register your source in `sources/registry.py` by importing it and appending an instance to the list returned by `discover_sources()`. (OpenHome forbids dynamic imports, so registration is explicit. Keep `sources/__init__.py` empty.)

4. If your source needs an API key, follow the same pattern as `virginia_state.py` — declare `required_api_key_name()`, accept the key via `set_api_key()`, and document the label in this README.

5. Open a PR against `dev` on `openhome-dev/abilities`. See the [contribution guide](https://docs.openhome.com/community/contributing) for the full checklist.

### Source guidelines

- Return a markdown string from `fetch_updates()` / `fetch_meetings()` — the ability turns it into speech.
- Keep the output concise: a short numbered list. This is a voice briefing, not a report.
- Use `self._http_get()` for all HTTP calls — the base class routes through the OpenHome SDK (`worker.session_tasks`) and returns response-like objects with `.text` and `.status_code`.
- Surface errors as strings in the return value (e.g. `"Error fetching ... HTTP 403"`) rather than raising — the briefing aggregator will include them so the agent can report and debug.
- No `print()` — logging is available via the platform when needed.
- No hardcoded API keys — use placeholders and document the key label in the README.

---

## Developer Notes

- **Adding a federal source** — U.S. Congress data is available via the [congress.gov API](https://api.congress.gov/) (free key). A `FederalCongressSource` following the same pattern is on the roadmap.
- **Adding more city sources** — Subclass `LegistarCitySource` in `sources/legistar.py` with a city `client_id` (the subdomain before `.legistar.com`), then register it in `sources/registry.py`.
- **Knowledge gaps** — when a source returns no usable data, it is logged to `knowledge_gaps.json` in the ability directory. Review this to see which jurisdictions are failing and prioritize fixes.
