# hacker news reader

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@StressTestor-lightgrey?style=flat-square)

## what it does

Voice-driven Hacker News browser. Hear the top stories, pick one for a summary, or ask what people are saying in the comments. All spoken back naturally, no screen needed.

Uses the official Hacker News API. No keys, no auth, completely free.

## suggested trigger words

- "what's on hacker news"
- "read me hacker news"
- "tech news"
- "hacker news"

## setup

No API keys or external accounts needed. The Hacker News API is public and free.

Requires `requests`:

```bash
pip install requests
```

## how it works

On trigger, it pulls the top 30 stories from HN and reads you the first 5 as spoken headlines. From there you can:

- pick a story number for a summary
- ask for comments on a story to hear what people are saying
- say "next" for more stories
- say "refresh" to pull fresh headlines
- say "done" to exit

The LLM turns raw story data and comments into natural conversational summaries optimized for voice.

## example conversation

> **User:** "what's on hacker news"
> **AI:** "Here's what's trending. Number one, SQLite now supports vector search natively, 842 points and 300 comments. Number two, a developer built a full OS in Rust over a weekend, 631 points..."
> **User:** "tell me more about number one"
> **AI:** "SQLite just shipped built-in vector search, which means you can do similarity queries without bolting on a separate database. Developers are excited because it keeps the single-file simplicity SQLite is known for."
> **User:** "what are people saying"
> **AI:** "The comments are mostly positive. A few people are benchmarking it against pgvector and finding it competitive for smaller datasets. Some concern about memory usage at scale, but the general vibe is that this is a big deal for embedded applications."
> **User:** "next"
> **AI:** "Number six, Google announces..."
> **User:** "done"
> **AI:** "Enjoy your day."

## supported commands

| Command | What it does |
|---------|-------------|
| pick a number (1-5) | get a summary of that story |
| "comments" / "what are people saying" | hear a summary of the discussion |
| "next" | next page of stories |
| "back" / "previous" | previous page |
| "refresh" / "start over" | pull fresh headlines from the top |
| "done" / "exit" | leave the ability |
