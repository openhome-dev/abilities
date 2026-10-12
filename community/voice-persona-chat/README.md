# Voice Persona Chat

Have a real voice conversation with AI characters via Venice.ai — Einstein, Socrates, Alan Watts, and whoever Venice features next. The characters respond in their authentic style using Venice's native character engine, not a generic LLM with a system prompt.

## What Makes This Different

| | voice-persona-chat | dungeon-master-voice |
|---|---|---|
| Character engine | Venice `character_slug` (native persona) | System prompt injected into generic LLM |
| Character roster | Live — fetched from Venice at runtime | Static, hardcoded |
| Fast path | Name in trigger → instant connect | Always requires explicit selection step |
| Returning users | Remembers last character, offers one-tap resume | No memory between sessions |
| Character count | 10+ and growing (Venice's catalog) | 14 fixed DM archetypes |

## Trigger Phrases

- "talk to Einstein"
- "chat with Socrates"
- "let me talk to Alan Watts"
- "voice persona"
- "persona chat"
- "connect me to Shakespeare"
- "character chat"
- "conversation with Tesla"

If you include a character name in the trigger, you skip the selection step entirely.

## Setup

1. Get a Venice API key from [venice.ai/settings/api/keys](https://venice.ai/settings/api/keys)
2. Add it to OpenHome settings under the key name: `venice_api_key`

No other setup required. The character roster is fetched live from Venice each session.

## How a Session Works

```
User: "talk to Einstein"
Assistant: Connecting you to Albert Einstein. Ready?
User: "yes"
Einstein: Ah, a curious mind reaches out! I am Albert Einstein — physicist, philosopher of science, and eternal questioner. What would you like to explore?
User: "what do you think about black holes?"
Einstein: [responds in Einstein's authentic voice and perspective]
...
User: "goodbye"
Einstein: [in-character farewell]
```

If you trigger without a name:
```
User: "voice persona"
Assistant: I can connect you to Alan Watts, Albert Einstein, Socrates, and three others. Who would you like to talk to?
User: "Einstein"
Assistant: You want to talk to Albert Einstein?
User: "yes"
Einstein: [greeting]
```

Returning session:
```
User: "persona chat"
Assistant: Want to talk to Albert Einstein again?
User: "yes"
Einstein: [greeting, no selection step]
```

## Notes

- Conversation history is kept in memory for the session only — not persisted
- The character roster updates automatically as Venice adds new characters
- Say "stop", "quit", "goodbye", or "that's all" to end the conversation
- The character gives a proper in-character farewell on exit
