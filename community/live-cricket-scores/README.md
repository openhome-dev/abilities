# Live Cricket Scores – OpenHome Ability

Live Cricket Scores is a voice-enabled OpenHome ability that provides real-time cricket match information using the Cricbuzz API via RapidAPI. Users can ask natural questions like “What matches are live?” or “What’s the current score?” and receive concise, voice-friendly responses.

---

## 🚀 Features

- Fetches **live cricket matches**
- Reads **current match status**
- Optimized for **voice-first interaction**
- Handles follow-up questions naturally
- Designed for OpenHome speakers and dashboard testing

---

## 🎙 Example Voice Queries

- “Live cricket scores”
- “What matches are live today?”
- “Which teams are playing right now?”
- “What’s the current match status?”
- “Who is batting?”
- “What’s the required run rate?”

---

## 🔑 API Setup (Required)

This ability uses the **Cricbuzz API via RapidAPI**.

### 👉 Get your API key from:
**https://rapidapi.com/cricketapilive/api/cricbuzz-cricket**

Once you have your API key:

1. Open `main.py`
2. Replace the placeholder with your key:
   ```python
   RAPIDAPI_KEY = "YOUR_RAPIDAPI_KEY_HERE"
   ```
3. Press the Save button
4. Test the ability using Live Test

## 🧠 Technical Overview
- Language: Python
- Framework: OpenHome Abilities SDK
- API Provider: Cricbuzz (via RapidAPI)
- Endpoint used:
```bash
GET /matches/v1/live
```

## 🧪 Current Behavior
When triggered, the ability:
1. Fetches live match data from Cricbuzz
2. Extracts team names and match status
3. Speaks a short, TTS-friendly update
4. Returns control back to the main assistant

## 🔮 Future Goals
Support detailed scorecards (runs, overs, wickets)
- Add match-specific follow-ups (batting team, required run rate)
- Support team-based queries (e.g. “India score”)
- Add tournament context (World Cup / League standings)
- Enable background polling for automatic score updates
- Improve handling of qualification and points table questions

## 📌 Notes
- This ability is intentionally lightweight for fast voice responses
- Designed to work even when default LLMs lack live sports data
- Ideal for sports-focused OpenHome deployments

## 📬 Author
Built by [Bilal](https://github.com/bilalmohib)
NextJS Developer at SmartlyQ,React JS | React Redux | Next JS | VueJS | React Native | Firebase | Supabase | Firestore Software Developer

