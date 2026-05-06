# Dungeon Master Voice Sessions

An OpenHome ability that runs voice-powered D&D sessions with 14 distinct Dungeon Master personalities.

## How It Works

1. **Trigger**: Say "dungeon master", "start D&D", or "summon dungeon master"
2. **Select a DM**: Name a Dungeon Master (fuzzy matched) or say "who's available" for the roster
3. **Play**: Speak your actions and the DM responds in character with full D&D 5e narration
4. **Exit**: Say "done", "goodbye", or "end session" — the DM gives a farewell in character

## Available Dungeon Masters

| Name | Style |
|------|-------|
| Shadow Weaver | Dark enchantress — macabre tales of betrayal and forbidden magic |
| Oracle Priestess | Divine seer — prophetic narration with temple grandeur |
| Dark Narrator | Hooded void entity — clinical doom and inevitable ruin |
| Kaito Shadowstride | Cunning rogue — heist-style adventures and thieves' cant |
| Zephyr Moonwhisper | Nature spirit — gentle guidance through moonlit wilds |
| Malakai Warhorn | Battle veteran — gritty war stories and visceral combat |
| Lyra Astrarium | Astronomer — cosmic wonder and celestial metaphors |
| Nix Sanguine | Vampire queen — dark seduction and aristocratic menace |
| Chaosweaver | Trickster deity — manic chaos and reality-bending antics |
| Ancient Sage | Mountain scholar — measured wisdom and scholarly parables |
| Arcane Wizard | Grand wizard — mystical descriptions and arcane wonder |
| Mystic Sorceress | Elegant witch — velvet-voiced lyrical narration |
| Storyteller Bard | Charismatic performer — theatrical drama and character voices |
| Tavern Keeper | Warm innkeeper — fireside tales with a mug of ale |

## Trigger Words

- "dungeon master"
- "start dnd"
- "start d and d"
- "summon dungeon master"
- "d and d session"

## Files

| File | Purpose |
|------|---------|
| `main.py` | Ability class — DM selection, session loop, Codex integration |
| `dm_personalities.py` | 14 DM personality registry with voice hints |
| `.env` | Optional Codex API URL |
| OpenHome dashboard | Trigger hotwords (platform-managed) |

## Optional: Codex Integration

Set `CODEX_URL` in `.env` to connect to a running Narrator's Codex instance for campaign context (NPCs, scenes, history). The ability works fully standalone without it.

## Upload

Zip `main.py` and `dm_personalities.py` together for upload to the OpenHome dev kit.
