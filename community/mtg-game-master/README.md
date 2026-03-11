# MTG Game Master

Voice-controlled Magic: The Gathering assistant for OpenHome. Looks up cards, answers rules questions, coaches draft strategy, and explains turn structure.

## What It Does

Say something like "help me with my Magic game" and the ability activates. Then ask it anything:

- **Card lookups**: "What does Mulldrifter do?" - fetches card data from Scryfall and reads it aloud
- **Rules questions**: "Can I tap a summoning sick creature for convoke?" - answers using MTG rules knowledge
- **Draft coaching**: "What should I pick first in Lorwyn Eclipsed?" - gives archetype and pick advice
- **Turn guide**: "Walk me through the combat phase" - explains phases and steps

## Setup

None. Scryfall is free with no API key required. Just activate the ability and start asking.

## How It Works

1. Speak a trigger phrase to activate (e.g. "magic the gathering", "rules judge", "card lookup")
2. Ask about cards, rules, drafting, or turn structure
3. The ability classifies your intent and routes to the right handler
4. Card data comes from the Scryfall API; rules answers come from the LLM
5. Cards are cached for the session so repeat lookups are instant
6. Say "exit" or "done" to leave

## Trigger Words

- magic the gathering
- magic game / magic rules / magic draft
- draft setup / draft night / start a draft
- rules judge / rules question
- card lookup / look up a card
- what does this card do
- lorwyn eclipsed
- turn guide / turn structure
- changeling / convoke / blight
- which should I pick / deck building

## API

- Scryfall REST API (https://api.scryfall.com)
- Free, no authentication, no setup
- Rate limited to 10 requests/second (handled automatically)
- Fuzzy card name matching built in (handles voice transcription errors)

## Lorwyn Eclipsed Support

Ships with built-in knowledge of the Lorwyn Eclipsed (ECL) set:

- All 5 primary draft archetypes (Kithkin, Merfolk, Goblins, Elementals, Elves)
- All 5 secondary archetypes (Orzhov counters, Boros counters, Gruul vivid, Simic vivid, Dimir faeries)
- Key mechanics: changeling, blight, vivid, kindred, convoke, evoke, persist
- Pick-Two Draft format for 4 players
- Standard booster draft for 6-8 players

## Example Conversations

**Card lookup:**
> User: "What does Lightning Bolt do?"
> AI: "Lightning Bolt. One red mana. Instant. Lightning Bolt deals 3 damage to any target."

**Rules question:**
> User: "If my creature has hexproof, can my opponent use a board wipe on it?"
> AI: "Yes. Hexproof only prevents targeting. Board wipes like Wrath of God don't target, they just destroy all creatures."

**Draft advice:**
> User: "I'm drafting Lorwyn Eclipsed, what's the best archetype?"
> AI: "BG Elves is the strongest archetype. It grinds better than anything else with graveyard synergies. But it gets contested in experienced pods."

**Turn structure:**
> User: "When do upkeep triggers happen?"
> AI: "Upkeep triggers go on the stack at the beginning of your upkeep step, right after untap. Players get priority to respond before moving to the draw step."

## Persistent Preferences

The ability remembers your experience level across sessions:
- Say "I'm an experienced player" to get shorter, less hand-holdy responses
- Say "I'm a beginner" to get more detailed explanations
- Default set is Lorwyn Eclipsed (ECL)
