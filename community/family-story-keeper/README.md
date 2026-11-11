# Family Story Keeper

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@hassan1731996-lightgrey?style=flat-square)

## What It Does
Turns your speaker into a patient family historian. It interviews a grandparent, a parent or you about their life, a few questions at a time, and works through the chapters of a life one session after another. Later, anyone at home can ask "how did Grandpa meet Grandma?" and hear the answer. With Google linked, it plays back the storyteller's own voice. Without Google, it reads the answer from the transcript.

## Suggested Trigger Words
- "family stories"
- "story keeper"
- "record a family story"
- "record grandpa's stories" / "interview mum"
- "play a family story"

Avoid "tell me a story". Bedtime Stories already uses it.

## Setup
- **Optional: link Google** in Settings → Linked Accounts. Recordings are then saved to your own Google Drive in a folder called `OpenHome Family Stories`, with one subfolder per storyteller. Nothing is uploaded anywhere else.
- Without Google linked, it still works and keeps the transcripts only. No audio is recorded.
- No API keys. Works in the Live Editor and on any device.

## How It Works

| You say | Family Story Keeper does |
|---|---|
| "Record Grandpa's stories" | Asks one question that covers who is speaking and the recording notice: "I'll record Grandpa's stories again and keep the recordings in your Google Drive. Say stop anytime. Ready?" You can answer "no, it's Nani" to switch person. Then it asks 3 questions, each followed by one curious follow-up about a detail the storyteller mentioned. Questions come from the least-covered chapter: childhood, family, school days, work, love, places, hard times, proud moments and advice. After 3 questions it asks "Shall we keep going?", for up to 9 questions in one sitting. |
| Pauses and short answers | A pause gets "Take your time, there's no rush." A short answer like "Lahore." gets "Tell me a little more about that." and both parts are kept. "Skip" or "I'd rather not talk about that" moves to another chapter. |
| "Family stories" | The first time, it goes straight to "Whose stories are we recording today?". If Social Memory knows an older relative, it suggests them ("Abdul, your grandfather?"). Once stories exist, it asks "Would you like to record a new story, or hear one?". Just saying a name works. |
| "Record my stories" | Uses your name from your OpenHome profile instead of asking. |
| "How did Grandpa meet Grandma?" | Finds the best-matching saved story and plays the recording. If there's no recording, it reads up to 60 words of the transcript. Then it asks "Want to hear another?" |
| "Ask Grandpa about his first car next time" | Turns that into a warm interview question and confirms it with you. You can say yes, no, or change it. The next interview asks it first. |
| "What haven't we covered?" | Says how many stories each person has, the chapters still open, and how many family questions are waiting. |
| "Delete that story" / "Delete all of Grandma's stories" | Asks first, then removes the stories and their Drive recordings. |
| "Keep the stories private" / "Share the highlights" | Turns the assistant highlights (below) off or on. |

Say "stop", "done" or "goodbye" to leave. Exit phrases only count as the whole reply, so "that's all I remember" never cuts a storyteller off. Longer requests like "let's stop for today, I'm tired" are recognised from the answer itself and are not saved as a story.

### Reuses what OpenHome already knows
It reads, and never writes, what the household has already shared, so it asks less and asks better:
- `user_profile.md`, `user_summary.md` and Memory Mirror's `memory_mirror_corrections.md` give your name and family context.
- **Social Memory**'s `social_memory.json` supplies relatives' names and relationships. "Grandpa" becomes "Grandpa Abdul", and questions get personal ("What was your first flight as a pilot like?").

All of it is fenced off as untrusted data in prompts, never read aloud verbatim and never logged. Voice Journal and other private notes are deliberately not read.

### The assistant learns the family
Unless you say "keep the stories private", the skill writes a short `family_story_keeper.md` note: who has been recorded and the 5 newest one-line highlights. The note stays under 180 words. OpenHome adds it to the assistant's context, so everyday conversation can reflect the family's history.

### Safety and privacy
- **Consent first.** Every interview starts with a spoken recording notice and needs a "yes".
- **Your recordings stay in your own Drive.** Context Storage keeps the transcript, a one-line summary and the Drive file ID for each story. Audio is downloaded only when someone asks to hear it.
- **Deleting is real.** Deleting a person removes their Drive folder and every recording in it.
- **Stories are treated as data.** Transcripts are fenced off with random markers in every prompt, and highlights that look like instructions are never written to the assistant note.
- **Logs never contain stories.** They record intents and counts only.
- **Limits:** 6 storytellers, 50 stories each, 10 queued questions. Transcripts are capped at 1,200 characters, and recordings over about 10 MB are kept as text only.

### How it differs from existing options
- **Voice Journal**, **Voice Memory Capture** and **Private Notes** store notes you dictate about yourself. Family Story Keeper *interviews* someone, follows up, and keeps track of which parts of a life are still untold.
- **Future Letter Writer** saves a message to yourself for a future date. **Bedtime Stories** invents fiction.
- It is the only community ability that records and replays a real person's voice.

## Example Conversation
> **User:** "Record Grandpa's stories."
> **AI:** "I'll start Grandpa's story collection and keep the recordings in your Google Drive. Say stop anytime. Ready?"
> **Grandpa:** "Ready."
> **AI:** "What did the street you grew up on look and sound like on a summer evening?"
> **Grandpa:** "Lahore."
> **AI:** "Tell me a little more about that."
> **Grandpa:** "Near the canal. Every evening the kids played cricket until the mosquitoes chased us in..."
> **AI:** "Cricket by the canal sounds wonderful. Who was the best player on your street?"
> *(two more questions later)*
> **AI:** "That's 4 stories so far. Shall we keep going?"
> **Grandpa:** "Not today."
> **AI:** "Lovely. I saved 4 stories from Grandpa, about childhood and work. Thank you."
>
> *A week later:*
> **User:** "Play a family story about Grandpa's childhood."
> **AI:** "Here's Grandpa, on Cricket by the Canal." *(plays the recording)* "Want to hear another?"
