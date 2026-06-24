# Wikipedia Lookup Template — OpenHome Ability
![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Template](https://img.shields.io/badge/Type-Template-blue?style=flat-square)

## What This Is
**This is a template ability** that answers "what is …" questions by looking up a topic on Wikipedia and speaking back a short summary. It uses Wikipedia's free public summary API — **no API key, no account, and no setup required.**

This is the simplest "fetch and tell" pattern: listen → extract a topic → call an API → speak the result → exit. It's a great starting point for any ability that reads from a public, keyless API.

## What You Can Build
Examples of abilities you could create with this template:
- **Quick-facts assistant** — answer "what is …" questions from Wikipedia
- **Definition lookup** — explain terms, people, places, or concepts
- **Trivia / fact-of-the-day** — pull a summary and read it aloud
- **Glossary helper** — define jargon for a specific domain
- **Any keyless public API reader** — swap Wikipedia for another open API

## Template Trigger Words
This template is designed around "what is …" phrasing — **customize the triggers** for your ability:
- "what is gravity" / "what is a black hole" / "what is photosynthesis"
- Configure your own trigger words in the OpenHome dashboard or when creating your ability.

## Requirements
- No API key and no account needed — Wikipedia's summary API is free and open.
- `requests` for the HTTP call (already available in the OpenHome runtime).
- Internet access from the agent.

## Using This Template

### 1. Get the Template
Add the Wikipedia template to your agent from:
- OpenHome Dashboard abilities library, OR
- [GitHub Repository](https://github.com/OpenHome-dev/abilities)

### 2. Customize for Your Use Case
- Set your trigger words in the dashboard.
- Adjust `extract_topic()` if you want phrasing other than "what is …".
- Tune how much of the summary is spoken (the template trims to the first two sentences).

## How the Template Works

### Template Flow
1. User triggers the ability and asks a "what is …" question
2. `wait_for_complete_transcription()` captures the full question
3. `extract_topic()` strips "what is" and leading articles ("a", "an", "the") to get the bare topic
4. The ability speaks an acknowledgement ("Let me look up … for you.")
5. `query_wikipedia()` calls the Wikipedia summary API and trims the result to two sentences
6. The summary is spoken — or a fallback message if nothing was found
7. `resume_normal_flow()` returns control to the Agent

### Key Components

**1. Topic Extraction:**
```python
def extract_topic(self, msg: str) -> str:
    msg = msg.lower().strip()
    if "what is" in msg:
        topic = msg.split("what is", 1)[1].strip()
        topic = re.sub(r"^(a|an|the)\s+", "", topic).strip()
        return topic
    return msg
```
- Turns "what is a black hole" into "black hole".

**2. Wikipedia Query:**
```python
WIKIPEDIA_API_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/"

response = requests.get(
    f"{self.WIKIPEDIA_API_URL}{topic.replace(' ', '_')}",
    headers={"User-Agent": "BrainSkillBot/1.0"},
)
```
- Wikipedia expects underscores instead of spaces.
- Reads the `extract` field (plain-text summary) and trims to the first two sentences for spoken brevity.
- Returns an empty string on `404` (topic not found) or any error, which triggers the spoken fallback.

**3. Resume Normal Flow:**
```python
self.capability_worker.resume_normal_flow()  # ← CRITICAL: always called
```
- Runs after both the success and fallback paths so control always returns to the Agent.

## Template Usage Examples

> **User:** "what is gravity"
> **AI:** "Let me look up gravity for you."
> **AI:** "Here is what I found about gravity."
> **AI:** *(two-sentence Wikipedia summary)*

> **User:** "what is a flibbertigibbet widget"
> **AI:** "Let me look up flibbertigibbet widget for you."
> **AI:** "Sorry, I could not find anything about flibbertigibbet widget on Wikipedia. Please try a different word."

## Customizing the Template

### 1. Change the Question Pattern
Edit `extract_topic()` to handle phrasings like "tell me about …" or "who is …".

### 2. Speak More or Less
The template keeps the first two sentences (`sentences[:2]`). Increase this for more detail, or summarize with `text_to_text_response()` for a more conversational answer.

### 3. Swap the API
Replace `WIKIPEDIA_API_URL` and the parsing in `query_wikipedia()` to read from any other keyless public API — the rest of the flow stays the same.

## Best Practices
- Always wrap API calls in `try/except` (the template does).
- Always log errors with `self.worker.editor_logging_handler`.
- Always call `resume_normal_flow()` on every exit path.

## Links & Resources
- [Dashboard](https://app.openhome.com/dashboard)
- [Abilities Library](https://app.openhome.com/dashboard/abilities)
- [Developer Docs](https://docs.openhome.com)
- [Wikipedia REST API](https://en.wikipedia.org/api/rest_v1/)

## Final Reminder
⚠️ **This template is a starting point, not a finished product.** Customize the trigger words, topic extraction, and response length for your specific use case.
