# Open Trivia

Open Trivia is a voice-powered trivia experience built using the Open Home SDK and its built-in LLM.

It delivers a conversational, game-show-style trivia session where users can answer questions, ask for repeats, change questions, or quit at any time.

The goal is to make trivia feel natural, engaging, and human — not scripted or robotic.

---

## Trigger words

- Trivia
- Open Trivia
- Challenge me 

---

## What the App Does

- Welcomes users into a live trivia session  
- Dynamically generates multiple-choice questions using the platform’s LLM  
- Understands user intent (quit, repeat, change question, continue)  
- Evaluates answers in real time  
- Provides energetic, natural feedback  
- Allows continuous play until the user decides to stop  

---

## Demo

https://www.loom.com/share/f42d4c4d06e84661b2fbe911913f9742
---

## What It Uses

Open Trivia is built with:

- `MatchingCapability` for activation  
- `CapabilityWorker` for conversation handling  
- `speak()` and `text_to_speech()` for responses  
- `user_response()` to capture player input  
- `text_to_text_response()` to leverage the platform’s LLM  

The platform’s LLM powers:

- Trivia question generation  
- Intent classification  
- Dynamic feedback generation  
- Conversational flow control  

---

## Future Possible Production Features

- Category selection (science, movies, sports, etc.)
- Adaptive difficulty (gets harder or easier based on performance)
- Score tracking
- Streak system (“3 in a row!” energy boosts)
- Leaderboards (local or global)
- Daily challenges
- Timed questions (adds excitement)
- Hints (50/50 option, small clue, etc.)
- Sound effects or dramatic pauses
- Multiplayer / challenge a friend mode
- Achievement badges
- Progress levels (Beginner → Expert)
- Personalized question themes
- Performance summary at the end of session
- Smart encouragement based on player mood
- Save progress between sessions
- Seasonal or event-based trivia themes
- User speaking mid sentence will cause for the app to listen again