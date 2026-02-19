# Bedtime Wind-Down

A dedicated "goodnight" ritual that closes out the user's day. Triggered by a simple bedtime command, this ability fetches tomorrow's first calendar event, generates a personalized soothing message, reads a calming quote, and plays ambient sleep sounds in a loop to help the user drift off. It operates entirely in a linear sequence with no conversation loops, prioritizing a peaceful, low-friction experience.

### Trigger Words
* "bedtime"
* "bed time"
* "time for bed"
* "sleep mode"
* "night mode"
* "tuck me in"
* "going to sleep"

### Setup
To fully enable the dynamic calendar schedule feature, you must configure the Composio API:
1. Open `main.py`.
2. Locate the `COMPOSIO_API_KEY` and `COMPOSIO_USER_ID` variables at the top of the `BedtimeWindDownCapability` class.
3. Replace `"YOUR_COMPOSIO_API_KEY"` and `"YOUR_COMPOSIO_USER_ID"` with your actual Composio credentials.

*(Note: If the API keys are not set, the ability will gracefully default to a "no events tomorrow" state and still function perfectly.)*

No API key is required for the ZenQuotes integration (it uses the free tier).

### How It Works
1. **User triggers the Ability** with a hotword (e.g., "Time for bed").
2. **Loads Preferences**: The ability silently reads `bedtime_prefs.json` to check user settings (preferred ambient sound, duration, quote toggles). If it's the first run, it generates the default settings.
3. **Fetches Tomorrow's Schedule**: Calls the Google Calendar API (via Composio) to find the first event of the next day and calculates a suggested wake-up time.
4. **LLM Generation**: The LLM crafts a brief, calming 3-4 sentence wind-down message based on the schedule.
5. **Speaks Message**: The ability speaks the message using a specific, soft meditation voice (`GBv7mTt0atIp3Br8iCZE`) rather than the default personality voice.
6. **Reads a Quote**: Fetches a calming quote from the ZenQuotes API (or a local fallback list) and speaks it.
7. **Plays Ambient Sounds**: Enters "music mode" and dynamically loops the chosen ambient track (e.g., rain, ocean, white noise) for the configured duration (default 30 minutes).
8. **Smart/Silent Exit**: If the user says "Stop", it breaks the loop immediately. Otherwise, when the timer finishes, the ability exits silently without waking the user.

### Key SDK Functions Used
* `text_to_speech()` — Speaks text utilizing a hardcoded, specific voice ID for a calming tone.
* `text_to_text_response()` — Generates the personalized wind-down message using the LLM synchronously.
* `play_audio()` — Streams the downloaded ambient MP3 bytes directly to the speaker.
* `send_data_over_websocket()` — Toggles `music-mode` on and off during audio playback to manage device state.
* `check_if_file_exists()`, `read_file()`, `write_file()` — Manages persistent JSON preferences locally on the device.
* `resume_normal_flow()` — Quietly returns control to the main personality.

### Example Sequence

**User:** "Time for bed."  
**AI:** *(In a soft, calming voice)* "Tomorrow you have a team standup at 9 AM, so waking up around 8 would give you plenty of time. Everything else can wait until morning. Rest well."  
**AI:** "The best bridge between despair and hope is a good night's sleep. E. Joseph Cossman."  
**AI:** "Starting ocean sounds. They'll play for 30 minutes. Sleep well."  
*(Ocean waves play seamlessly for 30 minutes... then the device silently powers down the session)*