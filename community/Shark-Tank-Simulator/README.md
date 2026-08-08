Shark Tank Simulator

Pitch your startup to three AI investors in a live, voice-only Shark Tank style session — Pakistan edition, with deals in Pakistani rupees (PKR).

The Sharks

SharkStyleSana the SkepticCold and doubting — attacks risk, competition, and weak pointsHarris the HypeAbsurdly overexcited — big vision, growth, how huge can this getNadia the NumbersCalm and surgical — price, cost, revenue, margins, and the ask

How a Session Works


The host welcomes you and asks for a 45-second pitch, including your ask (an amount in PKR for a percent of equity).
If you forget the ask, Nadia stops you and demands it before the grilling begins.
The sharks grill you for two rounds (six questions total). Every question is generated live from what you actually said — vague answers get called out, missing numbers get demanded.
Each shark delivers a final verdict — OFFER or OUT — quoting your own details, and the Tank rates your pitch out of ten.
Your pitch count and best-offer record persist between sessions, so returning founders get a personalized welcome.


Say "stop", "exit", or "leave the tank" at any time to end the session (Urdu also works: "bas", "band karo", "ruk jao").

Multi-Voice Sharks (optional — ElevenLabs)

Each shark can speak with a distinct ElevenLabs voice:


Get an API key from elevenlabs.io.
In main.py, set ELEVEN_API_KEY in your own OpenHome upload. Never commit a real key to this repository — keep the placeholder.
Optionally swap VOICE_SKEPTIC, VOICE_HYPE, and VOICE_NUMBERS for your favorite voice IDs.


Without a key, the Ability still works end to end — shark lines fall back to the default agent voice, prefixed with the shark's name. MAX_CONCURRENT_TTS caps parallel ElevenLabs requests to match your plan (Free 2, Starter 3, Creator 5).

Configuration


GRILL_ROUNDS — rounds of questioning (default 2, i.e. six questions).
CURRENCY_NAME / CURRENCY_CODE — localize the currency used in prompts and verdicts.
PITCH_WINDOW_SECONDS, ANSWER_WINDOW_SECONDS, LINGER_SECONDS — how patiently the sharks wait for you to speak and finish.


Robustness Notes

Built for noisy, real-world voice sessions: the listener ignores empty finished-speaking bursts and duplicate re-queued transcriptions, detects echoes of the sharks' own lines, and lingers briefly after you speak so a mid-answer pause doesn't cut you off. If question or verdict generation ever fails, canned fallbacks keep the show running.

API Required: ElevenLabs (optional, only for multi-voice sharks).