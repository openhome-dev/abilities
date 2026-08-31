# Wikipedia Deep Dive

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@hasni1731996-lightgrey?style=flat-square)

A voice-native learning companion. Say "learn about black holes", get a concise spoken intro, then keep going deeper — layer by layer — or pivot to related topics mid-session. Sessions are saved so you can pick up where you left off.

## What Makes It Different

| | Base LLM | Wikipedia template | Wikipedia Deep Dive |
|---|---|---|---|
| Source | Training data (may hallucinate) | Live Wikipedia | Live Wikipedia |
| Depth | One answer | One summary, then exits | Layer-by-layer drilling |
| Follow-ups | Yes, but stateless | No | Yes, with full history |
| Topic switching | Manual re-trigger | No | Inline, mid-session |
| Session memory | No | No | Yes — resumes across conversations |
| Setup required | None | None | None |

## Trigger Phrases

- `learn about` / `teach me about`
- `deep dive` / `deep dive into`
- `wikipedia`
- `explain in depth`
- `tell me about`

## Example Conversations

**Inline trigger (no extra prompt):**
> "Learn about black holes"
> → "Looking that up."
> → "A black hole is a region of spacetime where gravity is so strong that nothing — not even light — can escape. They form when massive stars collapse at the end of their lives. The boundary of a black hole is called the event horizon."
> → "Want to go deeper, explore something related, or say done?"

**Drilling deeper:**
> "Deeper"
> → "Beyond the event horizon lies the singularity — a point of infinite density where our current physics breaks down. Stephen Hawking showed that black holes slowly emit radiation, now called Hawking radiation, which means they can eventually evaporate. This raised a deep puzzle: does information get destroyed when a black hole dies?"
> → "Want to keep going, explore something related, or say done?"

**In-session pivot:**
> "What about neutron stars?"
> → "Switching to neutron stars."
> → [new topic intro]

**Saving and resuming:**
> "Save this"
> → "Saved. I'll remember what we covered."

> [new session] "Wikipedia"
> → "Want to continue where we left off on black holes?"

**Topic not found:**
> "Learn about flibbertigibbet quantum"
> → "I couldn't find that exactly. Did you mean quantum entanglement, quantum field theory, or quantum computing?"

## Exit Phrases

`done` · `stop` · `bye` · `goodbye` · `that's all` · `all done` · `never mind`

## Setup

None. Wikipedia's API is free and requires no key.

## How It Works

1. Strips trigger phrase to extract the topic inline (no extra prompt needed)
2. Fetches Wikipedia summary endpoint → LLM condenses to 2-3 spoken sentences
3. Fetches full article text for depth drilling on demand
4. LLM intent classifier routes each response: deeper / related / new topic / save / exit
5. Sessions stored in context storage — most recent offered on re-trigger within 7 days
6. On 404: Wikipedia search API returns 3 suggestions, spoken as alternatives

## Notes

- Depth cap at 3 layers per topic — after that, pivoting to related topics is suggested
- In-session topic switching works naturally: just say the new topic mid-conversation
- Up to 5 sessions saved; oldest pruned automatically

## Author

Muhammad Hassan
