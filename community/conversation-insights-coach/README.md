# Conversation Insights Coach
![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-Muhammad_Hassan-lightgrey?style=flat-square)

## What It Does

A passive background coach that silently monitors HOW you communicate — not what you say. Tracks filler words, hedging language, vocabulary diversity, question-to-statement ratio, and utterance length. Ask for a report anytime and get a spoken, personalized coaching summary with historical trends, milestones, and actionable tips.

## Trigger Words

- how am I communicating
- communication insights
- my filler words
- speech insights
- speaking report
- coach my speech
- set filler goal
- watch my fillers

## Setup

No external API keys or services needed. Fully self-contained using OpenHome's built-in LLM and TTS.

## How It Works

1. Background daemon starts automatically when your session connects
2. Every 20 seconds it silently analyzes new conversation messages
3. Tracks: filler words, hedging phrases, vocabulary, questions vs statements, utterance length
4. Say **"how am I communicating?"** anytime to get your spoken coaching report
5. Reports compare today with your historical averages and celebrate personal bests

## Features

- **Passive Analysis** — runs silently, zero friction, no trigger words needed during conversation
- **Filler Word Tracking** — detects "um", "uh", "like", "you know", "basically", "I mean", and more
- **Hedging Detection** — tracks "maybe", "I think", "I guess", "sort of" — a proxy for assertiveness
- **Vocabulary Diversity** — unique words vs total words, tracks new vocabulary per session
- **Question Ratio** — balance between asking questions and making statements
- **Historical Trends** — compares today with your 30-day history
- **Streak Tracking** — "You've been improving for 3 days in a row!"
- **Milestone Celebrations** — personal bests are announced in your report
- **Goal Setting** — set a filler target ("set a goal of 10 fillers today")
- **Real-Time Nudges** — optional mode that gives a gentle spoken tip when filler clusters are detected
- **Detail Drill-Down** — ask about specific areas: fillers, vocabulary, assertiveness, questions, pace
- **Coaching Tips** — every report ends with one specific, actionable tip based on your weakest area
- **Session Persistence** — same-day sessions resume after reconnect; daily history saved for 30 days

## What Gets Tracked

| Metric | What it means |
|---|---|
| Filler words | "um", "uh", "like", "you know", "basically", "I mean", "sort of"… |
| Hedging phrases | "maybe", "I think", "I guess", "probably", "sort of"… |
| Vocabulary diversity | Unique words ÷ total words (higher = more varied language) |
| Question ratio | % of utterances that are questions |
| Avg utterance length | Average words per spoken turn |
| New vocabulary | Words you haven't used in previous sessions |

## Example Conversation

**User:** how am I communicating?

**Coach:** You've been on a roll today — 34 utterances with a vocabulary diversity of 58%, which is above your usual average. You used 12 filler words, with 'like' showing up 5 times. That's down from your average of 18, so you're clearly making progress! One thing to try: next time you feel a filler coming, just pause for a beat instead — silence is more powerful than it feels.

**User:** tell me more about my fillers

**Coach:** Your top fillers today were 'like' at 5, 'you know' at 3, and 'basically' at 2. Your filler rate is 3.8% of total words, down from your average of 5.2% — that's a real improvement! Try replacing 'you know' with a brief pause; it makes your sentences land more cleanly.

**User:** set a goal of 8 fillers

**Coach:** Goal set! I'll track your progress toward fewer than 8 filler words today. Ask for a report anytime to see how you're doing.

**User:** watch my fillers

**Coach:** Real-time coaching is on. I'll give you a gentle heads-up whenever I notice a cluster of filler words. You've got this!

## Difficulty / Nudge Settings

- **Silent mode (default)** — analyzes passively, reports on demand only
- **Nudge mode** — say "watch my fillers" to enable gentle real-time tips when 3+ fillers appear in one utterance (max once every 2 minutes to avoid being annoying)
- Turn off nudges anytime: "stop watching my fillers"
