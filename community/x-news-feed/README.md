# X News Feed Analysis

A voice-powered OpenHome ability that fetches the top tweet from each of five curated topics on X (Twitter), scores them by engagement, and reads AI-generated summaries aloud.

## What It Does

This ability keeps you updated on what's happening across five key topics on X through natural voice commands. It can:

- **Fetch top tweets per topic** — For each topic in `TOPIC_SEEDS`, it pulls 10 recent tweets and picks the single most-engaged one using a weighted public metrics score
- **AI-generated summaries** — The winning tweet for each topic is sent to the LLM, which produces a short, conversational trend-style summary
- **Quick mode** — Top 3 topic summaries with option to hear more
- **Full mode** — All 5 topic summaries with an interactive Q&A follow-up session
- **Topic deep-dives** — Ask for more detail on any topic by number
- **Smart exit handling** — Multiple natural ways to end the session

## How Topics Are Selected

Rather than relying on the X Trends API (which doesn't reliably return tweet counts on all subscription tiers), this ability uses the **Recent Search API** with a fixed set of topic seeds:

```python
TOPIC_SEEDS = [
    "Artificial Intelligence",
    "Crypto",
    "Climate",
    "Tech Innovation",
    "Global Markets",
]
```

For each topic it:
1. Fetches 10 recent tweets (`-is:retweet -is:reply lang:en`)
2. Scores every tweet using weighted public metrics:
   ```
   likes ×3  |  retweets ×2  |  quotes ×2  |  replies ×1  |  bookmarks ×1
   ```
3. Selects the highest-scoring tweet as the topic representative
4. Sends all 5 winning tweets to the LLM for a trend-style summary each

All 5 topics are fetched **concurrently** using `asyncio.gather()`, so the wait time is roughly the duration of the slowest single call rather than 5× sequential waits.

## Trigger Words

Say any of these phrases to activate the ability:

**Quick Mode (Top 3):**
- "What's trending on X?"
- "Twitter trends"
- "X news"
- "Show me X trends"
- "X trends"
- "Latest from X"

**Full Mode (All 5 with Q&A):**
- "All trends"
- "All five trends"
- "Catch me up"
- "Full briefing"
- "Tell me everything"
- "Deep dive"

The ability automatically detects whether you want a quick update or a full interactive session based on which trigger phrase you use.

## What You'll Hear While Fetching

Instead of a generic filler, the ability now names the exact topics it is fetching. One of these phrases is spoken at random:

> *"Let me fetch the top tweets on Artificial Intelligence, Crypto, Climate, Tech Innovation, and Global Markets — just a moment."*

> *"Give me a second, grabbing the top tweets on Artificial Intelligence, Crypto, Climate, Tech Innovation, and Global Markets."*

This is driven by `FILLER_INTRO_TEMPLATES` and built dynamically from `TOPIC_SEEDS`, so it stays accurate if you ever change the topic list.

## Setup

### 1. Get an API Key (Optional but Recommended)

For live X/Twitter data, you need an X API Bearer Token with access to the **v2 Recent Search** endpoint.

**Option A: X Developer Portal (Official)**
1. Go to [X Developer Portal](https://developer.twitter.com/en/portal/dashboard)
2. Create a project and app
3. Generate a Bearer Token
4. Copy your Bearer Token

**Option B: RapidAPI Twitter154 (Easier)**
1. Go to [RapidAPI Twitter154 API](https://rapidapi.com/omarmhaimdat/api/twitter154/)
2. Sign up for a free account
3. Subscribe to the free tier
4. Copy your API key

### 2. Configure the Ability

Open `main.py` and set your token:

```python
# Replace this:
X_API_BEARER_TOKEN = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# With your actual Bearer Token:
X_API_BEARER_TOKEN = "your_bearer_token_here"
```

**Note:** The ability works without an API key using built-in demo data. This is ideal for development, testing, and demonstrations.

### 3. Upload to OpenHome

1. Create a new ability in your OpenHome dashboard
2. Upload `main.py`
3. Set trigger words (suggestions in `config.json`)
4. Test using "Start Live Test"

## How It Works

### Quick Mode

When you ask something like "What's trending on X?", the ability:

1. Speaks a filler phrase naming each topic being fetched
2. Concurrently fetches 10 tweets per topic (5 topics = 5 parallel API calls)
3. Picks the highest-engagement tweet per topic using the scoring formula
4. Asks the LLM to summarise each winning tweet into a 1–2 sentence insight
5. Reads the top 3 summaries aloud
6. Asks "Want to hear more, or are you all set?"
7. If you say "more" → reads summaries 4 and 5
8. Exits cleanly when you say "done", "bye", or similar

**Example:**
```
You:     "What's trending on X?"
Ability: "Give me a second, grabbing the top tweets on Artificial Intelligence,
          Crypto, Climate, Tech Innovation, and Global Markets."
Ability: "Hey there, here are the top 3 trending topics right now:"
Ability: "Number 1: Artificial Intelligence. Developers are debating how AI
          changes workflows across every seniority level, from building basics
          to orchestrating full agent teams."
Ability: "Number 2: Crypto. Real-world asset tokenisation is gaining momentum,
          with developers blending physical infrastructure and digital tokens
          into new hybrid ecosystems."
Ability: "Number 3: Climate. Climate Summit 2026 has produced a landmark
          multi-nation commitment on emissions, reigniting optimism about
          coordinated global climate action."
Ability: "Want to hear more, or are you all set?"
You:     "More"
Ability: "Here are the remaining topics:"
Ability: "Number 4: Tech Innovation. Distributed GPU rendering is turning heads,
          with new platforms making high-end graphics accessible on everyday hardware."
Ability: "Number 5: Global Markets. Better-than-expected inflation figures sparked
          a broad rally, lifting both equities and digital assets simultaneously."
Ability: "That's all 5. Anything else?"
You:     "All good"
Ability: "Take care!"
```

### Full Mode

When you ask for a full briefing like "Catch me up" or "All trends", the ability:

1. Speaks the filler phrase naming all topics
2. Fetches, scores, and summarises all 5 topics (same pipeline as Quick Mode)
3. Reads all 5 summaries aloud
4. Opens an interactive Q&A session
5. You can ask about a specific topic by number ("Tell me about number 2")
6. You can ask to hear them again ("Read them again")
7. Exits after you say "done" or after 2 idle responses

**Example:**
```
You:     "Catch me up"
Ability: "One moment — fetching top tweets on Artificial Intelligence, Crypto,
          Climate, Tech Innovation, and Global Markets."
Ability: "Hey there, here's your full rundown of the top 5 trending topics on X:"
Ability: "Number 1: Artificial Intelligence. [LLM summary]"
...
Ability: "Want to know more about any of these? Ask away, or say done when finished."
You:     "Tell me about number three"
Ability: "More on Climate: [LLM-generated follow-up insight using the top tweet as context]"
Ability: "What else would you like to know?"
You:     "Goodbye"
Ability: "Stay informed!"
```

## Voice Design Principles

This ability follows OpenHome's voice-first design guidelines:

- **Named filler speech** — "Fetching top tweets on Artificial Intelligence, Crypto…" instead of a generic "one sec"
- **Short responses** — 1–2 sentences per turn, progressive disclosure
- **Natural language** — Conversational summaries instead of raw tweet text or numerical counts
- **Exit handling** — Multiple natural ways to exit: "done", "stop", "bye", "that's all"
- **Idle detection** — Offers to sign off after 2 silent responses
- **Concurrent fetching** — All 5 topics fetched in parallel to minimise wait time

## SDK Usage

### Core Patterns Used

**Capturing user input (critical — must run first):**
```python
user_input = await self.capability_worker.wait_for_complete_transcription()
```

**Speaking:**
```python
await self.capability_worker.speak("Message to user")
```

**Listening:**
```python
user_input = await self.capability_worker.user_response()
```

**LLM for summarisation and Q&A (synchronous — no await):**
```python
response = self.capability_worker.text_to_text_response(prompt)
```

**Concurrent API calls:**
```python
tasks = [self._fetch_top_tweet_for_topic(topic) for topic in TOPIC_SEEDS]
results = await asyncio.gather(*tasks, return_exceptions=True)
```

**Blocking HTTP inside async:**
```python
resp = await asyncio.to_thread(requests.get, url, headers=headers, timeout=10)
```

**Patient input polling:**
```python
user_input = await self.wait_for_input(max_attempts=5, wait_seconds=3.0)
```

**Exit:**
```python
self.capability_worker.resume_normal_flow()  # Always call this when done!
```

## API Information

**Provider:** X (Twitter) Official API  
**Endpoint:** `https://api.twitter.com/2/tweets/search/recent`  
**Authentication:** Bearer Token  
**Fields requested:** `text, public_metrics`  
**Filters applied:** `-is:retweet -is:reply lang:en`  
**Results per topic:** `max_results=10`  
**Required Header:** `Authorization: Bearer YOUR_TOKEN`

### Engagement Scoring Formula

Each of the 10 fetched tweets is scored as follows:

| Metric | Weight | Reason |
|--------|--------|--------|
| `like_count` | ×3 | Strongest positive signal |
| `retweet_count` | ×2 | Indicates shareworthy content |
| `quote_count` | ×2 | Signals conversation-worthy content |
| `reply_count` | ×1 | Engagement but can be negative |
| `bookmark_count` | ×1 | Quiet saves, moderate signal |
| `impression_count` | ×0 | Excluded — reflects reach, not quality |

The tweet with the highest score wins and is passed to the LLM for summarisation.

### Demo Data

The ability includes demo data used when no API key is configured. Each entry mirrors the live data structure exactly:

```python
DEMO_TRENDS = [
    {
        "name": "Artificial Intelligence",
        "top_tweet": "2026 is the year of AI...",
        "score": 42,
        "summary": "Developers are debating how AI changes workflows..."
    },
    ...
]
```

This lets you test the full conversation flow, demonstrate the ability, and develop without API costs or rate limits.

## Customisation

- **Change topics** — Edit `TOPIC_SEEDS` to track any subjects you care about. The filler speech updates automatically.
- **Adjust scoring weights** — Modify `score_tweet()` to weight engagement signals differently.
- **Change result count** — Update `max_results=10` in `RECENT_SEARCH_URL` (max 100 on Basic tier).
- **Add time context** — Append `start_time` to the API query for "this morning's tweets" vs "this week's".
- **Reading preferences** — Let users configure how many topics to read via the preferences file.

## Troubleshooting

**"I'm having trouble reaching X right now"**
- Check your Bearer Token is correct in `main.py`
- Verify you have API credits remaining (Free tier: 500 requests/month)
- Confirm network connectivity in your OpenHome settings

**Ability doesn't trigger**
- Verify trigger words in the dashboard match `config.json`
- Try more explicit phrases: "What's trending on X" rather than just "trending"
- Confirm the ability is enabled and saved

**All topics fall back to demo data**
- Check the API token is not still set to the placeholder value `"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"`
- Run a manual `curl` test against the endpoint to confirm your token has v2 Recent Search access

## Contributing

1. Fork the OpenHome abilities repo
2. Make your changes
3. Test thoroughly using "Start Live Test"
4. Submit a PR with a clear description of what changed and why

## License

Open source under the same license as the OpenHome project.

---

**Built for OpenHome** — The open-source voice AI platform  
**Questions?** Join the [OpenHome Discord](https://discord.gg/openhome)