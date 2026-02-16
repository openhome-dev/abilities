# X News Feed Analysis

A voice-powered OpenHome ability that searches and reads aloud trending topics and news from X (Twitter).

## What It Does

This ability lets you stay updated on what's trending on X through natural voice commands. It can:

- **Read trending topics** - Get the top trending topics on X with tweet counts
- **Quick mode** - Top 3 trends with option to hear more
- **Full mode** - All 5 trends with interactive Q&A follow-ups
- **Topic deep-dives** - Ask for more details on any specific trending topic (by number)
- **Smart exit handling** - Multiple ways to exit naturally

## Trigger Words

Say any of these phrases to activate the ability:

**For Quick Mode (Top 3):**
- "What's trending on X?"
- "Twitter trends"
- "X news"
- "Show me X trends"
- "X trends"
- "Latest from X"

**For Full Mode (All 5 with Q&A):**
- "All trends"
- "All five trends"
- "X trending topics"
- "What is trending on X?"

The ability automatically detects whether you want a quick update or a full interactive session based on which trigger phrase you use.

## Setup

### 1. Get an API Key (Optional but Recommended)

For live X/Twitter data, you'll need an X API Bearer Token:

**Option A: X Developer Portal (Official)**
1. Go to [X Developer Portal](https://developer.twitter.com/en/portal/dashboard)
2. Create a project and app
3. Generate Bearer Token
4. Copy your Bearer Token

**Option B: RapidAPI Twitter154 (Easier)**
1. Go to [RapidAPI Twitter154 API](https://rapidapi.com/omarmhaimdat/api/twitter154/)
2. Sign up for a free account
3. Subscribe to the free tier
4. Copy your API key

### 2. Configure the Ability

Open `main.py` and add your API key:

```python
# Replace this line:
X_API_BEARER_TOKEN = "REPLACE_WITH_YOUR_KEY"

# With your actual Bearer Token:
X_API_BEARER_TOKEN = "your_bearer_token_here"
```

**Note:** The ability works without an API key using demo trending data for testing. This is perfect for development, demonstration, and your Loom video.

### 3. Upload to OpenHome

1. Create a new ability in your OpenHome dashboard
2. Upload the `main.py` file
3. Set trigger words (suggestions in `config.json`)
4. Test using "Start Live Test"

## How It Works

### Quick Mode

When you ask a specific question like "What's trending on X?" or "Twitter trends", the ability:

1. Speaks a filler phrase ("One sec, checking what's hot on X")
2. Fetches the top 5 trending topics
3. Reads the top 3 aloud with tweet counts
4. Asks "Want to hear more, or are you all set?"
5. If you say "more" or "continue" → reads the remaining 2 trends
6. Exits cleanly when you say "done", "bye", or similar

**Example:**
```
You: "What's trending on X?"
Ability: "One sec, checking what's hot on X..."
Ability: "Hey there, here are the top 3 trending topics right now:"
Ability: "Number 1: Artificial Intelligence, with 125 thousand posts."
Ability: "Number 2: Climate Summit 2026, with 98 thousand posts."
Ability: "Number 3: Mars Mission Update, with 87 thousand posts."
Ability: "Want to hear more, or are you all set?"
You: "Continue"
Ability: "Here are the remaining trends:"
Ability: "Number 4: Tech Innovation Awards, with 76 thousand posts."
Ability: "Number 5: Global Markets Rally, with 65 thousand posts."
Ability: "That's all 5. Anything else?"
You: "All good"
Ability: "Take care!"
```

### Full Mode

When you ask for a briefing like "All trends" or "All five trends", the ability:

1. Speaks a filler phrase
2. Fetches the top 5 trending topics
3. Reads all 5 aloud with tweet counts
4. Opens an interactive Q&A session
5. You can ask about specific topics by number ("Tell me about number 2")
6. You can ask to hear them again ("Read them again")
7. Exits when you say "done" or after 2 idle responses

**Example:**
```
You: "All trends"
Ability: "One sec, checking what's hot on X..."
Ability: "Hey there, here's your full rundown of the top 5 trending topics on X:"
Ability: "Number 1: Artificial Intelligence, with 125 thousand posts."
Ability: "Number 2: Climate Summit 2026, with 98 thousand posts."
Ability: "Number 3: Mars Mission Update, with 87 thousand posts."
Ability: "Number 4: Tech Innovation Awards, with 76 thousand posts."
Ability: "Number 5: Global Markets Rally, with 65 thousand posts."
Ability: "Want to know more about any of these? Ask away, or say done when you're finished."
You: "Tell me about number two"
Ability: "About Climate Summit 2026: [LLM-generated 2-sentence explanation of why it's trending]"
Ability: "What else would you like to know?"
You: "Goodbye"
Ability: "Stay curious!"
```

## Voice Design Principles

This ability follows OpenHome's voice-first design guidelines:

- **Short responses** - 1-2 sentences per turn, progressive disclosure
- **Filler speech** - "One sec, pulling up the latest from X" before API calls
- **Natural numbers** - "125 thousand" instead of "125,000"
- **Exit handling** - Multiple ways to exit: "done", "stop", "bye", "that's all"
- **Idle detection** - Offers to sign off after 2 silent responses
- **Confirmation-free** - Reading data doesn't need confirmation (low stakes)

## SDK Usage

### Core Patterns Used

**Critical: Capturing User Input**
```python
# IMPORTANT: Wait for user input FIRST before processing
user_input = await self.capability_worker.wait_for_complete_transcription()
```
This ensures the trigger phrase is properly captured before the ability starts processing.

**Speaking:**
```python
await self.capability_worker.speak("Message to user")
```

**Listening:**
```python
user_input = await self.capability_worker.user_response()
```

**LLM for Classification & Analysis:**
```python
# No await! This is synchronous
response = self.capability_worker.text_to_text_response(prompt)
```

**API Calls with asyncio.to_thread:**
```python
import asyncio
response = await asyncio.to_thread(
    requests.get, url, headers=headers, params=params, timeout=10
)
```

**Patient Input Waiting:**
```python
# Custom helper that polls patiently for user input
user_input = await self.wait_for_input(max_attempts=5, wait_seconds=3.0)
```

**Exit:**
```python
self.capability_worker.resume_normal_flow()  # Always call this when done!
```

### Architecture Highlights

- **Input capture fix** - Uses `wait_for_complete_transcription()` to ensure trigger phrase is captured
- **Mode detection from trigger** - Analyzes the actual user input to determine quick vs full mode
- **Patient input polling** - Custom `wait_for_input()` helper that retries multiple times
- **File persistence** - Saves user preferences across sessions using the file storage API
- **Demo data fallback** - Works without API key for testing/demos
- **LLM-powered topic analysis** - Uses the LLM to generate explanations for trending topics
- **Contextual goodbyes** - LLM generates natural sign-off messages

## API Information

**Provider:** X (Twitter) Official API  
**Endpoint:** `https://api.twitter.com/1.1/trends/place.json`  
**Authentication:** Bearer Token  
**Rate Limits:** Depends on your X API tier (Free tier: 500 requests/month)  
**Required Header:** `Authorization: Bearer YOUR_TOKEN`

### Demo Data

The ability includes demo trending data that's used when no API key is configured:

```python
DEMO_TRENDS = [
    {"name": "Artificial Intelligence", "tweet_count": 125000},
    {"name": "Climate Summit 2026", "tweet_count": 98000},
    {"name": "Mars Mission Update", "tweet_count": 87000},
    {"name": "Tech Innovation Awards", "tweet_count": 76000},
    {"name": "Global Markets Rally", "tweet_count": 65000}
]
```

This lets you:
- Test the full conversation flow without API costs
- Demonstrate the ability in videos
- Develop and iterate without rate limits
- Submit working code to GitHub

Replace with live data when ready by adding your Bearer Token.

## Customization Ideas

- **Add time context** - "This morning's trending topics" vs "Tonight's buzz"
- **Filter by category** - Tech, sports, politics, entertainment
- **Save favorites** - Use file storage to remember topics user cares about
- **Reading preferences** - Let users set how many topics to read (3, 5, 10)
- **Tweet summaries** - Fetch and summarize actual tweets about trending topics
- **Personalized greetings** - Use saved user name from preferences file

## Technical Notes

### Critical Input Capture Fix

This ability includes an important fix for a common OpenHome issue where abilities would miss the user's trigger phrase. The solution:

```python
async def capture_user_input(self):
    """Wait for and capture the user's input that triggered this ability."""
    user_input = await self.capability_worker.wait_for_complete_transcription()
    if user_input and user_input.strip():
        self.trigger_phrase = user_input.strip().lower()
```

This ensures the trigger phrase is captured **before** any processing begins, allowing for accurate mode detection and context-aware responses.

### Patient Input Polling

The ability uses a custom `wait_for_input()` helper that patiently polls for user responses:

```python
async def wait_for_input(self, max_attempts: int = 5, wait_seconds: float = 3.0):
    """Poll for user input patiently. Returns first non-empty response."""
    for attempt in range(max_attempts):
        await self.worker.session_tasks.sleep(wait_seconds)
        user_input = await self.capability_worker.user_response()
        if user_input and user_input.strip():
            return user_input.strip()
    return ""
```

This handles voice transcription delays gracefully without timing out prematurely.

## Testing Without API Key

The ability includes mock trending data for testing:

```python
def get_mock_trending_data(self) -> list:
    return [
        {"name": "AI Safety Summit", "tweet_count": 125000},
        {"name": "Climate Action", "tweet_count": 98000},
        # ... more topics
    ]
```

This lets you:
- Test the full conversation flow
- Demonstrate the ability in videos
- Develop without API costs

Replace with live data when ready by adding your API key.

## Troubleshooting

**"I couldn't pull up the X feed"**
- Check your API key is correct in `main.py`
- Verify you have API credits remaining
- Check network connectivity in OpenHome settings

**Ability doesn't trigger**
- Verify trigger words in dashboard match `config.json`
- Try more specific phrases: "What's trending on X" vs just "trending"
- Check ability is enabled and saved

**Response is too long/robotic**
- Adjust `format_trending_summary()` to be more concise
- Reduce number of topics read (currently 3 for quick, 5 for full)
- Simplify number formatting in `format_number_for_speech()`

## Contributing

Found a bug or have an improvement? Here's how to help:

1. Fork the OpenHome abilities repo
2. Make your changes to this ability
3. Test thoroughly using "Start Live Test"
4. Submit a PR with:
   - Clear description of what changed
   - Why the change improves the ability
   - Test results showing it works

## License

Open source under the same license as the OpenHome project.

---

**Built for OpenHome** - The open-source voice AI platform  
**Questions?** Join the [OpenHome Discord](https://discord.gg/openhome)