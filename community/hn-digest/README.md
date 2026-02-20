# HN Digest

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![API](https://img.shields.io/badge/API-Algolia%20HN-ff6600?style=flat-square)
![No Key Required](https://img.shields.io/badge/API%20Key-None%20Required-brightgreen?style=flat-square)

> Get a crisp spoken summary of the top Hacker News stories — plus instant deep-dives on any story or topic you're curious about.

---

## What It Does

HN Digest fetches real, live stories directly from the [Algolia Hacker News API](https://hn.algolia.com/api) and delivers them as a concise voice briefing. You can then ask for details on any story by number, search any tech topic on HN, or request a longer list — all hands-free.

**The experience:**
1. Trigger the ability
2. Hear a 5-story digest of today's Hacker News front page (real data, no generative hallucination)
3. Say a number to get an expanded 2-sentence take on any story
4. Say a topic to search HN for it instantly
5. Say "done" to exit

---

## Suggested Trigger Words

- `"HN digest"`
- `"Hacker News"`
- `"hacker news digest"`
- `"tech digest"`
- `"what's on Hacker News"`
- `"HN today"`
- `"top tech stories"`

*(Set your preferred triggers in the OpenHome dashboard)*

---

## Setup

**No API key required.** HN Digest uses the free, public [Algolia Hacker News Search API](https://hn.algolia.com/api) — no sign-up, no rate-limit token needed for normal usage. The API allows up to **10,000 requests per hour** from a single IP.

| API | Endpoint | Key Required |
|-----|----------|--------------|
| Algolia HN Search | `hn.algolia.com/api/v1/search` | No |
| Algolia HN Items | `hn.algolia.com/api/v1/items/:id` | No |

---

## How It Works

### Conversation Flow

```
Trigger → Fetch front page (Algolia) → LLM-narrated digest
         ↓
    Interactive loop:
      1–10       → expand that story (fetches full item if needed)
      topic word → search HN for it → LLM summary
      "more"     → re-fetch top 10 stories instead of 5
      "done"     → exit
```

### API Usage

| Algolia Parameter | Value | Purpose |
|-------------------|-------|---------|
| `tags=front_page` | — | Current HN front page stories |
| `tags=story`      | + `query=<topic>` | Topic search |
| `hitsPerPage`     | 5 or 10 | Stories per digest |
| Items endpoint    | `:id` | Full story text for expansion |

### LLM Role

The LLM is used **only for narration** — the actual story data (titles, URLs, points, comments) comes directly from the Algolia API. This avoids hallucination and keeps the digest grounded in real content.

---

## Example Conversations

### Morning Tech Briefing

```
User:    "What's on Hacker News?"
Speaker: "Fetching today's top Hacker News stories."
Speaker: "First, a new open-source LLM from Mistral is making waves with 10,000 context length.
          Second, PostgreSQL 17 shipped with major performance wins for large tables.
          Third, a viral thread asks whether AI pair programming actually slows senior devs down.
          Fourth, a solo dev launched a profitable SaaS in 30 days and shared the full breakdown.
          Fifth, WASM is quietly becoming the runtime of choice for edge functions."
Speaker: "Say a number to hear more about that story, search a topic, or say done."

User:    "Tell me about number three"
Speaker: "A Hacker News thread sparked debate after a senior engineer claimed AI autocomplete
          introduces more review overhead than it saves. The post has 400+ comments with a
          roughly even split between enthusiastic adopters and skeptics."
Speaker: "Want another story, or say done?"

User:    "Done"
Speaker: "Catch you next time."
```

### Topic Deep-Dive

```
User:    "HN digest about Rust"
Speaker: "Searching Hacker News for Rust."
Speaker: "Found 5 stories on Rust: most discuss the 2025 memory safety report citing Rust
          adoption in the Linux kernel, plus a crate called Axum hitting 1M downloads."
Speaker: "Want to hear more on this, or say done?"
```

### Getting More Stories

```
User:    "More stories"
Speaker: "Fetching today's top Hacker News stories."
         [Speaks a 10-story digest]
Speaker: "Say a number for details, or done to finish."
```

---

## SDK Methods Used

| Method | Purpose |
|--------|---------|
| `speak()` | Deliver the digest and responses |
| `run_io_loop()` | Prompt and listen for user's next command |
| `text_to_text_response()` | Narrate raw API data conversationally |
| `resume_normal_flow()` | Return control to Personality on exit |
| `editor_logging_handler` | Log API errors (never `print()`) |
| `session_tasks.create()` | Launch the async run loop |

---

## Architecture Notes

- **Real data**: Story titles, URLs, points, and comment counts come directly from the Algolia HN API. The LLM only rewrites them for speech.
- **Graceful degradation**: If the API is unreachable, the ability says so and exits cleanly without crashing.
- **Fallback narration**: If the LLM call fails, raw titles are read aloud directly.
- **Max 8 interaction turns** to prevent runaway sessions.
- **All exit paths call `resume_normal_flow()`**.
