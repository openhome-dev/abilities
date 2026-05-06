# Local Event Explorer

The **Local Event Explorer** is an OpenHome community ability that helps users discover concerts, sports, comedy, and festivals in their area. It uses **Ticketmaster** and **Serper.dev** (Google Events) in parallel as primary sources, falling back to **SeatGeek** if both return nothing.

## Features

- **Smart Geolocation**: Detects your city via IP on first run and asks you to confirm. Saves your home city persistently. Saying "nearby" at any time re-triggers IP detection.
- **Natural Language Time Parsing**: Ask for events "tonight", "this weekend", "next Saturday", or any other time phrase — parsed by LLM into exact date ranges.
- **Robust Intent Classification**: Keyword-first pre-classification catches event genres (jazz, comedy, concert…) and polite exits (thanks, bye, no thanks…) before the LLM, with punctuation-tolerant word matching for STT output.
- **Parallel API Fetching**: Ticketmaster and Serper run simultaneously via `asyncio.gather`; SeatGeek runs only as a fallback.
- **Interactive Drill-Down**: Ask for details on a specific result by position ("the first one") or keyword ("the jazz show").
- **Add to Calendar**: Directly inserts into Google Calendar if OAuth tokens are configured, otherwise generates a pre-filled Google Calendar link.
- **STT Bleed Protection**: Captures and validates the trigger text so accidental wake-word transcriptions don't pollute the first search.

## Flow Diagram

```mermaid
flowchart TD
    A([User activates ability]) --> B[Load prefs / home city]
    B --> C{home_city set?}
    C -- No --> D[IP Geolocation]
    D --> E{IP city found?}
    E -- Yes --> F[Ask user to confirm or change city]
    F --> G[Save city to prefs]
    E -- No --> H[Ask user to name a city]
    H --> G
    C -- Yes --> I

    G --> I[Main conversation loop]

    I --> J[Listen for user input]
    J --> K{Empty input?}
    K -- Yes x2 --> L[Re-prompt]
    K -- Yes x3 --> M([Exit: no response])
    K -- No --> N[Strip punctuation / lowercase]

    N --> O{Exit word or phrase?}
    O -- Yes --> M2([Exit: goodbye])
    O -- No --> P{Nearby phrase detected?}
    P -- Yes --> Q[Tag _nearby_hint]
    Q --> R
    P -- No --> R{Event keyword in input?}
    R -- Yes --> S[Call LLM classifier]
    S --> T{LLM returned clarify?}
    T -- Yes --> U[Force mode = search, keep location/time]
    T -- No --> V
    U --> V
    R -- No --> W[Call LLM classifier]
    W --> V

    V{LLM returned clarify\nbut location present?}
    V -- Yes --> X[Upgrade to search]
    V -- No --> Y

    X --> Y[Dispatch on mode]

    Y --> Z1[search]
    Y --> Z2[expand]
    Y --> Z3[calendar]
    Y --> Z4[city]
    Y --> Z5[clarify]

    Z1 --> AA{_nearby_hint or\nlocation = nearby?}
    AA -- Yes --> AB[IP geo → confirm with user]
    AB --> AC[Search APIs in parallel:\nTicketmaster + Serper]
    AA -- No --> AC
    AC --> AD{TM returned 0?}
    AD -- Yes --> AE[SeatGeek fallback]
    AE --> AF
    AD -- No --> AF[Merge + deduplicate results]
    AF --> AG{Events found?}
    AG -- Yes --> AH[Speak results → loop]
    AG -- No --> AI[Speak no-results message → loop]

    Z2 --> AJ[Resolve event ref by ordinal or keyword]
    AJ --> AK{Event found in list?}
    AK -- Yes --> AL[Speak event details → loop]
    AK -- No --> AM[LLM followup → loop]

    Z3 --> AN{OAuth tokens set?}
    AN -- Yes --> AO[POST to Google Calendar API]
    AN -- No --> AP[Generate calendar link → loop]
    AO --> AP

    Z4 --> AQ[Save new home city to prefs → loop]

    Z5 --> AR[LLM generates followup question → loop]
```

## Setup Instructions

To use this ability you need to provide API keys. You can hardcode them into the `AppConfig` class in `main.py`, or store them in the preferences file `event_explorer_prefs.json`:

```json
{
  "home_city": "Paris",
  "api_key_ticketmaster": "YOUR_KEY_HERE",
  "api_key_seatgeek": "YOUR_KEY_HERE",
  "api_key_serper": "YOUR_KEY_HERE"
}
```

### 1. Get API Keys

1. **Ticketmaster** (Primary): [Ticketmaster Developer Portal](https://developer.ticketmaster.com/) — free account gives you an API key.
2. **Serper.dev** (Google Events): [Serper.dev](https://serper.dev/) — 2,500 free queries on signup.
3. **SeatGeek** (Fallback): [SeatGeek Platform](https://seatgeek.com/account/develop) — register an app for a Client ID.
4. **Google Calendar** (Optional): Create an OAuth 2.0 Client ID in Google Cloud Console. Exchange an authorization code for a `refresh_token` and `access_token` via the `oauth2.googleapis.com` token endpoint, then add them to `AppConfig`.

### 2. Google Calendar OAuth (optional)

If Google tokens are left empty, the ability falls back to generating a pre-filled Google Calendar link and speaking the event name. No calendar insertion will happen automatically.

To enable direct insertion, add these to `AppConfig` in `main.py`:

```python
GOOGLE_CLIENT_ID     = "..."
GOOGLE_CLIENT_SECRET = "..."
GOOGLE_ACCESS_TOKEN  = "..."
GOOGLE_REFRESH_TOKEN = "..."
```

## Example Prompts

- "Open Event Explorer."
- "Nearby comedy events."
- "Find jazz shows this weekend in Cairo."
- "Are there any concerts tonight?"
- "Search for Taylor Swift in New Orleans."
- "Tell me more about the second one."
- "Add that to my calendar."
- "My city is Berlin."
- "No thanks." / "Done." / "Goodbye."
