# X News Feed

A voice-powered OpenHome ability that fetches the top tweets for any topic on X (Twitter), scores them by engagement, cleans them for natural speech, and reads them aloud.

---

## What It Does

- **Demo mode** — No API key needed. Presents 5 curated topics as a numbered menu. User picks one and hears the top 3 pre-scored tweets for that topic.
- **Live mode** — With an API key, asks the user to name any topic freely, fetches up to 30 real tweets, scores them, and reads the top 3.
- **Tweet cleaning** — Strips URLs, hashtags, mentions, and HTML entities before speaking, then uses the LLM to rewrite each tweet as a single natural sentence.
- **Quick mode** — Reads the top 2 tweets, then offers the 3rd.
- **Full mode** — Reads all 3 tweets upfront, then opens an interactive Q&A session.
- **Topic deep-dives** — Ask for more detail on any tweet by number during Q&A.
- **Smart exit** — Multiple natural phrases to end the session gracefully.

---

## How It Works

### Demo Mode vs Live Mode

The ability checks whether a real Bearer Token is configured at startup:

**Demo mode** (no token set):
1. Reads out the 5 static `TOPIC_SEEDS` as a numbered list
2. User says a number (1–5) or a topic name like "Crypto" or "Climate"
3. The top 3 pre-scored demo tweets for that topic are read aloud

**Live mode** (token configured):
1. Asks the user to name any topic they want — no restrictions
2. Fetches up to 30 real tweets from X Recent Search API using a plain synchronous `requests.get()` call
3. Scores every tweet using weighted public metrics
4. Keeps the top 3 highest-scoring tweets
5. Sends them to the LLM for a short summary
6. Reads them aloud after cleaning and polishing for speech

### Tweet Cleaning Pipeline

Every live tweet goes through a two-stage cleaning process before being spoken:

**Stage 1 — Regex cleanup** (`clean_tweet_text`):
- Removes all URLs (`https://t.co/...`)
- Removes all hashtags (`#PAKvsBAN`)
- Removes all mentions (`@SomeUser`)
- Decodes HTML entities (`&amp;` → "and", `&lt;` → "less than", etc.)
- Collapses extra whitespace and newlines

**Stage 2 — LLM polish** (`polish_tweet_for_speech`):
- Sends the cleaned text to the LLM with a prompt to rewrite it as a single natural-sounding sentence
- Removes any leftover emoji or awkward fragments from URL/hashtag removal
- Falls back to the regex-cleaned text if the LLM call fails

**Example:**
```
Raw tweet:
"#PAKvsBAN | 1st ODI 🇵🇰 Pakistan humbled in Bangladesh 🇧🇩;
 hosts chase down target in 15.1 overs https://t.co/fJj7f4NqxN"

After regex clean:
"Pakistan humbled in Bangladesh; hosts chase down target in 15.1 overs"

After LLM polish (spoken aloud):
"Pakistan were humbled in the first ODI as Bangladesh chased down
 the target in just 15 overs."
```

### Engagement Scoring

Each fetched tweet is scored using weighted public metrics:

| Metric | Weight | Reason |
|--------|--------|--------|
| `like_count` | ×3 | Strongest positive engagement |
| `retweet_count` | ×2 | Indicates shareworthy content |
| `quote_count` | ×2 | Signals conversation-worthy content |
| `reply_count` | ×1 | Engagement but can be negative |
| `bookmark_count` | ×1 | Quiet saves, moderate signal |
| `impression_count` | ×0 | Excluded — reach, not quality |

Tweets are sorted descending by score. The top 3 are kept.

### Quick Mode vs Full Mode

Mode is detected from the phrase used to trigger the ability:

**Quick mode** (default):
- Reads tweets 1 and 2
- Offers: "There is one more tweet. Want to hear it, or are you all set?"
- If the user says yes/more/sure → reads tweet 3
- Exits after a short follow-up

**Full mode** (triggered by phrases like "all tweets", "full briefing", "catch me up"):
- Reads all 3 tweets upfront
- Speaks the LLM-generated topic summary
- Opens an interactive Q&A loop where the user can ask about specific tweets or the topic generally
- Exits after the user says "done" or after 2 idle responses

---

## Topic Seeds (Demo Mode)

```python
TOPIC_SEEDS = [
    "Artificial Intelligence",
    "Crypto",
    "Climate",
    "Tech Innovation",
    "Global Markets",
]
```

In demo mode these are presented as a numbered menu. The user picks one by saying its number or name. In live mode these are not used — the user can name any topic freely.

---

## Trigger Words

**Quick mode:**
- "Twitter trends"
- "X news"
- "What's trending on X"
- "Latest from X"
- "X trends"

**Full mode:**
- "All tweets"
- "All trends"
- "Full briefing"
- "Catch me up"
- "Tell me everything"
- "Deep dive"
- "Show all"

---

## Setup

### 1. Get a Bearer Token (for live mode)

1. Go to [developer.twitter.com](https://developer.twitter.com/en/portal/dashboard)
2. Create a project and app
3. Generate a Bearer Token with access to the **v2 Recent Search** endpoint
4. Copy the token

The ability works without a token using built-in demo data — useful for testing and demonstrations.

### 2. Configure the Ability

Open `main.py` and replace the placeholder:

```python
# Replace this:
X_API_BEARER_TOKEN = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# With your token:
X_API_BEARER_TOKEN = "your_bearer_token_here"
```

### 3. Upload to OpenHome

1. Create a new ability in your OpenHome dashboard
2. Upload the `main.py` file
3. Set trigger words in the OpenHome dashboard
4. Test using "Start Live Test"

---

## Example Conversations

### Quick Mode (Live)

```
You:      "Twitter trends"
Ability:  "Hey there, let us check what is buzzing on X."
Ability:  "What topic would you like to explore? You can say anything,
           for example Space Exploration, Football, or Electric Vehicles."
You:      "Artificial Intelligence"
Ability:  "One moment, fetching top tweets on Artificial Intelligence."
Ability:  "Here are the top 2 tweets on Artificial Intelligence:"
Ability:  "Tweet 1: Developers are rethinking how AI fits into workflows
           at every level, from junior engineers building foundations
           to seniors orchestrating entire agent teams."
Ability:  "Tweet 2: Every company is becoming an AI company whether they
           want to or not — those who adapt their workflows will come out ahead."
Ability:  "There is one more tweet. Want to hear it, or are you all set?"
You:      "Sure"
Ability:  "Tweet 3: AI agents are not here to replace engineers —
           they are taking over the repetitive work, leaving
           the creative thinking to humans."
Ability:  "That is the top 3. Anything else?"
You:      "Done"
Ability:  "Stay informed!"
```

### Full Mode (Demo)

```
You:      "Full briefing"
Ability:  "Hey there, welcome to X News! I will help you catch up on
           the latest tweets for any topic you care about."
Ability:  "Here are the available topics: 1. Artificial Intelligence,
           2. Crypto, 3. Climate, 4. Tech Innovation, 5. Global Markets.
           Just say the number or the topic name."
You:      "Three"
Ability:  "Here is the full rundown of the top 3 tweets on Climate:"
Ability:  "Tweet 1: The Climate Summit 2026 concluded with 47 nations
           signing binding emissions targets, the most ambitious global
           agreement since Paris."
Ability:  "Tweet 2: Solar is now the cheapest energy source in history,
           and every new coal plant built today will be a stranded asset
           within a decade."
Ability:  "Tweet 3: Carbon capture technology just hit a new efficiency
           milestone, suggesting we may have more tools available than
           previously thought."
Ability:  "Overall: Climate Summit 2026 has produced a landmark multi-nation
           commitment on emissions, reigniting optimism about coordinated
           global climate action."
Ability:  "Want to know more about any of these? Ask away, or say done
           when finished."
You:      "Tell me more about tweet two"
Ability:  "More on tweet 2: The falling cost of solar is accelerating
           the retirement of fossil fuel infrastructure globally,
           making clean energy the default economic choice."
Ability:  "What else would you like to know?"
You:      "Goodbye"
Ability:  "Catch you later!"
```

---

## SDK Patterns Used

**Capturing the trigger phrase (runs first):**
```python
user_input = await self.capability_worker.wait_for_complete_transcription()
```

**Speaking:**
```python
await self.capability_worker.speak("Message to user")
```

**Listening for a reply:**
```python
user_input = await self.capability_worker.user_response()
```

**LLM text generation (synchronous — no await):**
```python
response = self.capability_worker.text_to_text_response(prompt)
```

**HTTP calls (plain synchronous — no asyncio or threading):**
```python
resp = requests.get(url, headers=headers, timeout=10)
```

**Managed sleep (use instead of asyncio.sleep):**
```python
await self.worker.session_tasks.sleep(0.4)
```

**Per-user file storage:**
```python
await self.capability_worker.write_file("prefs.json", json.dumps(data), False)
raw = await self.capability_worker.read_file("prefs.json", False)
```

**Always call at the end:**
```python
self.capability_worker.resume_normal_flow()
```

---

## Demo Data

When no API token is configured, `DEMO_TRENDS` provides 3 pre-scored tweets per topic:

```python
DEMO_TRENDS = {
    "Artificial Intelligence": {
        "summary": "Developers are debating how AI changes workflows...",
        "tweets": [
            {"text": "2026 is the year of AI...", "score": 420},
            {"text": "Every company is now an AI company...", "score": 310},
            {"text": "AI agents are not replacing engineers...", "score": 275},
        ],
    },
    ...
}
```

Demo tweets are pre-cleaned and require no LLM polishing before being spoken.

---

## Customisation

- **Change topics** — Edit `TOPIC_SEEDS`. Demo menu and filler speech update automatically.
- **Adjust scoring** — Modify `score_tweet()` to weight metrics differently.
- **Change result count** — Update `max_results=10` in `RECENT_SEARCH_URL` (max 100 on Basic tier).
- **Add time filters** — Append `start_time` to the API query for "this morning's tweets".

---

## Allowed Libraries

This ability uses only OpenHome-approved imports:

| Import | Purpose |
|--------|---------|
| `json` | Preferences file serialisation |
| `re` | Tweet text cleaning (regex) |
| `random` | Random filler phrase selection |
| `requests` | HTTP calls to X API |

No `asyncio`, `concurrent`, `threading`, or `signal` — all blocked by the OpenHome sandbox.

---

## Troubleshooting

**"I couldn't pull up the X feed"**
- Check your API key is correct in `main.py`
- Verify you have API credits remaining
- Check network connectivity in OpenHome settings

**Ability doesn't trigger**
- Verify the trigger words are saved correctly in the OpenHome dashboard
- Try more specific phrases: "What's trending on X" vs just "trending"
- Check ability is enabled and saved

**Ability does not trigger**
- Confirm trigger words in the dashboard match your `config.json`
- Try an explicit phrase: "Twitter trends" or "X news"
- Confirm the ability is enabled and saved

**Token is set but still getting demo data**
- Make sure the token is not still the placeholder `"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"`
- Test manually with `curl`:
  ```bash
  curl -H "Authorization: Bearer YOUR_TOKEN" \
  "https://api.twitter.com/2/tweets/search/recent?query=AI&max_results=10"
  ```

---

## API Reference

**Endpoint:** `GET https://api.twitter.com/2/tweets/search/recent`  
**Auth:** `Authorization: Bearer YOUR_TOKEN`  
**Fields:** `text, public_metrics`  
**Filters:** `-is:retweet -is:reply lang:en`  
**Results:** `max_results=10`

---

**Built for OpenHome** - The open-source voice AI platform  
**Questions?** Join the [OpenHome Discord](https://discord.gg/openhome)
