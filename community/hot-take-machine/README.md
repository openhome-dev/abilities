# Hot Take Machine 🔥

A voice-driven OpenHome Ability that drops scorching hot takes on random topics and argues back when you push it.

## What it does

1. Say "hot take" or "hot take machine" to activate
2. It delivers a spicy, controversial hot take on a random topic
3. You say agree or disagree
4. If you agree, it hypes the discussion
5. If you disagree, it roasts you and defends its take
6. After 4 rounds it wraps up dramatically

## Trigger Words

- "hot take"
- "hot take machine"

## Example

> You: hot take
> HTM: Activated.
> HTM: Sleep is overrated, the most successful people I know run on spite and caffeine.
> HTM: Agree or disagree?
> You: disagree, sleep is essential
> HTM: Oh you wanna fight? Bet. Bring it.

## Stopping / Exiting

Say any of these to end the debate early: "stop", "exit", "cancel", "quit", "goodbye", "bye", "done", "i give up", "you win", "fine", or "end".

## Score Persistence

Your lifetime score (Hot Take Machine vs. You) is saved across sessions using OpenHome's key/value storage, so the intro line always reflects your real running score.

## Built with

- OpenHome SDK
- CapabilityWorker for voice I/O
- Built in LLM via text_to_text_response

## Author

Muhammad Asad Kashif
