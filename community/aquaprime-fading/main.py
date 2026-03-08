import hashlib
import json
import os
import random
import socket
import urllib.request
import urllib.error

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# AquaPrime: The Fading — Voice Text RPG for OpenHome
#
# A post-singularity sky-world RPG played entirely through voice.
# You pilot an airship across The Fading grid, contest story beat squares,
# collect Sand Dollars, and try not to fade. ARI narrates your journey as
# a sentient purple platypus captain of the Moonstone Maverick.
#
# Game state persists to platypuspassions.com — your ship shows on the live map.
# Get your room code at session start and visit aquaprime.gg/AQUA-XXXX on screen.
#
# Memory Model (TYOV-inspired):
#   - fading_memories = container (5 slots, themed, e.g. "The Rug Serpent")
#   - fading_experiences = 1 evocative sentence per turn (up to 3 per container)
#   - A slot is only consumed when a NEW memory container is created
#   - Skills = memories with grants_ability set; lost on critical fail
#
# Pattern: Loop (narrate → listen → resolve → narrate) with D20 mechanics
# =============================================================================

BASE_URL = "https://www.platypuspassions.com"

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye",
    "goodbye", "leave", "end game", "stop playing",
}

# ── Game World ──────────────────────────────────────────────────────

REGIONS = [
    {
        "name": "The Genesis Platform",
        "desc": "The original landing zone. Moss-covered launch ramps, AquaPrime flags still flying. Something stirs in the hangar below.",
        "danger": 1,
        "grid": (25, 15),
    },
    {
        "name": "The Liquidity Spires",
        "desc": "Crystalline towers rising from cloud banks, humming with moonstone resonance. The higher you climb, the stranger the geometry.",
        "danger": 2,
        "grid": (30, 10),
    },
    {
        "name": "Moloch's Vortex",
        "desc": "The sky turns black. Coordination failures echo through static. Something vast circles in the dark above.",
        "danger": 4,
        "grid": (40, 5),
    },
    {
        "name": "The Mempool Fog",
        "desc": "Thick clouds carrying whispers of unconfirmed transactions. Navigation instruments spin uselessly.",
        "danger": 3,
        "grid": (15, 20),
    },
    {
        "name": "The Consensus Reef",
        "desc": "A floating reef of crystallized agreements that shifts and rebuilds itself. The structures here vote on their own architecture.",
        "danger": 2,
        "grid": (20, 8),
    },
    {
        "name": "The Burned Gardens",
        "desc": "Once lush sky-platforms, now scorred by a mass defection event. Charred moonstone fragments drift in the thermals.",
        "danger": 3,
        "grid": (35, 25),
    },
    {
        "name": "The Whale Graveyard",
        "desc": "Enormous skeletal airship hulks of ancient liquidity providers. Their engines still hum with residual energy.",
        "danger": 4,
        "grid": (45, 20),
    },
    {
        "name": "The Fork in the Wind",
        "desc": "Two jet streams split from one. Each claims to be the original. Both are right. Both are wrong.",
        "danger": 2,
        "grid": (10, 15),
    },
]

ENCOUNTERS = [
    {"type": "creature", "name": "Rug Serpent", "desc": "A sky serpent woven from broken promises. Strikes fast, leaves nothing.", "difficulty": 3},
    {"type": "creature", "name": "Gas Leech", "desc": "Bloated and slow, draining your fuel reserves with each passing moment.", "difficulty": 2},
    {"type": "creature", "name": "Whale Shadow", "desc": "You cannot see it clearly. Just the massive displacement in the cloud layer above.", "difficulty": 5},
    {"type": "environmental", "name": "Crypto Winter Storm", "desc": "The temperature drops across all sectors. Only the prepared survive.", "difficulty": 3},
    {"type": "environmental", "name": "Consensus Quake", "desc": "The sky grid fractures as validators disagree. Choose your side.", "difficulty": 4},
    {"type": "social", "name": "Wandering Archivist", "desc": "An old platypus drifting in a balloon. They remember when this place had value.", "difficulty": 1},
    {"type": "social", "name": "Faction Recruiter", "desc": "Join the Catalysts. They believe destruction is just rebirth wearing a different face.", "difficulty": 2},
    {"type": "discovery", "name": "Moonstone Vein", "desc": "A raw vein of moonstone exposed in the wreckage, glowing softly in the mist.", "difficulty": 0},
    {"type": "discovery", "name": "Memory Fragment", "desc": "A crystallized memory from someone who faded. It shows a world that no longer exists.", "difficulty": 0},
    {"type": "mystery", "name": "The Signal", "desc": "Your instruments pick up a repeating signal. Not any known protocol. It says: still here.", "difficulty": 1},
]

LOOT_TABLE = [
    {"name": "Moonstone Shard", "rarity": "common", "effect": "plus 5 Sand Dollars"},
    {"name": "Echo Crystal", "rarity": "uncommon", "effect": "preserves one memory from fading"},
    {"name": "Void Token", "rarity": "rare", "effect": "opens a path through the Vortex"},
    {"name": "Hull Fragment", "rarity": "rare", "effect": "unlocks the Graveyard inner hull"},
    {"name": "Dust of the Faded", "rarity": "uncommon", "effect": "reveals hidden encounters"},
    {"name": "Broken Compass", "rarity": "common", "effect": "points toward the nearest moonstone"},
    {"name": "Genesis Fragment", "rarity": "legendary", "effect": "unknown power"},
]

GM_SYSTEM_PROMPT = (
    "You are ARI, Game Master of AquaPrime: The Fading. "
    "You are a sentient purple platypus, INTJ, captain of the Moonstone Maverick. "
    "Narrate a satirical sky-world RPG set in The Fading — a post-singularity grid of airships, ruins, and clouds. "
    "Moonstones are the lifeblood. Moloch lurks in coordination failure. "
    "The Fading claims those who lose their memories. "
    "RULES: Keep responses under 3 sentences for voice. "
    "Dark comedy meets philosophical depth. "
    "Make the player feel their choice matters. "
    "Reference HP (battery), Sand Dollars, and inventory when relevant. "
    "End each narration with a clear situation that demands a response. "
    "Never use hashtags or emojis in spoken text."
)


# ── Device Identity ──────────────────────────────────────────────────

def get_device_id() -> str:
    """Get a stable 4-char hex device ID based on hostname."""
    hostname = socket.gethostname()
    return hashlib.md5(hostname.encode()).hexdigest()[-4:]


# ── API Calls ────────────────────────────────────────────────────────

def api_post(path: str, payload: dict) -> dict | None:
    """POST JSON to platypuspassions.com API. Returns parsed response or None."""
    url = f"{BASE_URL}{path}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return {"error": f"HTTP {e.code}: {body}"}
    except Exception as e:
        return {"error": str(e)}


def register_session(device_id: str, display_name: str = "Pilot") -> str | None:
    """Register with game server. Returns room code or None on failure."""
    result = api_post("/api/voice/player-register", {
        "device_id": device_id,
        "display_name": display_name,
    })
    if result and "room_code" in result:
        return result["room_code"]
    return None


def fetch_memories(device_id: str) -> list[dict]:
    """Fetch active memory containers with experiences for this device."""
    url = f"{BASE_URL}/api/voice/memories?device_id={device_id}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
            return data.get("memories", [])
    except Exception:
        return []


def build_memory_context(memories: list[dict]) -> str:
    """Build TYOV-style memory context injected into the system prompt.

    Format:
        MEMORY 1 — The Rug Serpent Encounter [lore]
          • I fought the Rug Serpent at the Liquidity Spires and lost two fingers.
          • I traded the fingers for safe passage through Moloch's Vortex.
        SKILL: Astral Navigation (from Memory 2)
    """
    if not memories:
        return ""

    lines = ["PLAYER MEMORY (what they still carry from previous sessions):"]
    skill_lines = []

    for m in memories:
        slot = m.get("slot_number", "?")
        title = m.get("memory_title", "Unknown Memory")
        mtype = m.get("memory_type", "lore")
        experiences = m.get("experiences", [])
        grants = m.get("grants_ability")

        lines.append(f"  MEMORY {slot} — {title} [{mtype}]")
        if experiences:
            for exp in experiences:
                lines.append(f"    • {exp}")
        else:
            lines.append(f"    • (no experiences recorded yet)")

        if grants:
            skill_lines.append(f"  SKILL: {grants} (from Memory {slot})")

    if skill_lines:
        lines.append("")
        lines.append("ACTIVE SKILLS:")
        lines.extend(skill_lines)

    lines.append("")
    lines.append(
        "Reference these memories naturally in narration. "
        "Memories and skills NOT listed here have been erased — never mention them."
    )
    return "\n".join(lines)


def sync_game_state(device_id: str, hp: int, sand_dollars: int, stance: str,
                    pos_x: int, pos_y: int) -> None:
    """Push game state to Supabase (fire and forget — don't block the game loop)."""
    api_post("/api/voice/game-update", {
        "device_id": device_id,
        "hp": hp,
        "sand_dollars": sand_dollars,
        "stance": stance,
        "pos_x": pos_x,
        "pos_y": pos_y,
        "is_online": True,
    })


def write_memory(device_id: str, pos_x: int, pos_y: int,
                 narration: str, experience_text: str,
                 memory_type: str = "lore", memory_theme: str = None,
                 grants_ability: str = None) -> dict | None:
    """Write narration to node story slots and player memory containers.

    narration → node_memories (full text, location-bound story)
    experience_text → fading_experiences (single evocative sentence inside a memory container)

    Returns {'must_erase': bool, 'slots_remaining': int, ...} or None.
    """
    payload = {
        "device_id": device_id,
        "pos_x": pos_x,
        "pos_y": pos_y,
        "narration": narration,
        "experience_text": experience_text,
        "memory_type": memory_type,
    }
    if memory_theme:
        payload["memory_theme"] = memory_theme
    if grants_ability:
        payload["grants_ability"] = grants_ability
    return api_post("/api/voice/memory-write", payload)


def set_offline(device_id: str) -> None:
    """Mark session as offline when game ends."""
    api_post("/api/voice/game-update", {
        "device_id": device_id,
        "is_online": False,
    })


# ── Helpers ──────────────────────────────────────────────────────────

def roll_d20():
    return random.randint(1, 20)


def roll_encounter(region):
    if random.random() > 0.3 + (region["danger"] * 0.1):
        return None
    eligible = [e for e in ENCOUNTERS if e["difficulty"] <= region["danger"] + 1]
    return random.choice(eligible) if eligible else ENCOUNTERS[0]


def roll_loot():
    roll = random.random()
    if roll < 0.05:
        return next((l for l in LOOT_TABLE if l["rarity"] == "legendary"), None)
    if roll < 0.20:
        candidates = [l for l in LOOT_TABLE if l["rarity"] == "rare"]
        return random.choice(candidates) if candidates else None
    if roll < 0.45:
        candidates = [l for l in LOOT_TABLE if l["rarity"] == "uncommon"]
        return random.choice(candidates) if candidates else None
    candidates = [l for l in LOOT_TABLE if l["rarity"] == "common"]
    return random.choice(candidates) if candidates else None


def detect_stance(text: str) -> tuple[str, float]:
    lower = text.lower()
    offensive = {"attack", "fight", "strike", "charge", "slash", "hit", "kill", "destroy", "punch", "stab"}
    defensive = {"defend", "block", "shield", "hide", "dodge", "evade", "run", "flee", "retreat", "duck"}
    explore = {"explore", "examine", "investigate", "look", "search", "inspect", "check", "study", "observe"}

    if any(w in lower for w in offensive):
        return "offense", 1.3
    if any(w in lower for w in defensive):
        return "defense", 1.1
    if any(w in lower for w in explore):
        return "explore", 0.9
    return "neutral", 1.0


def get_memory_type_for_encounter(encounter: dict | None, success: bool) -> tuple[str, str | None]:
    """Return (memory_type, grants_ability) based on encounter outcome."""
    if not encounter:
        return "lore", None
    enc_type = encounter.get("type", "")
    if enc_type == "creature":
        return "lore", ("Combat Instinct" if success else None)
    if enc_type == "social":
        return "relationship", ("Persuasion" if success else None)
    if enc_type == "discovery":
        return "resource", ("Keen Eye" if success else None)
    if enc_type == "mystery":
        return "secret", ("Signal Reading" if success else None)
    return "lore", None


# ── Ability Class ────────────────────────────────────────────────────

class AquaprimeFadingCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run_game())

    async def run_game(self):
        try:
            await self._play()
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Game error: {e}")
            await self.capability_worker.speak(
                "Something went wrong in the grid. The game has ended unexpectedly."
            )
        self.capability_worker.resume_normal_flow()

    async def _play(self):
        device_id = get_device_id()

        # Register session — get room code
        room_code = register_session(device_id)
        if room_code:
            domain = "aquaprime.gg"
            await self.capability_worker.speak(
                f"Your room code is {room_code}. "
                f"Visit {domain} slash {room_code} on any screen to see your ship on the grid."
            )
        else:
            await self.capability_worker.speak(
                "Connecting to the grid..."
            )

        # Load persistent memories from previous sessions
        memories = fetch_memories(device_id)
        memory_context = build_memory_context(memories)

        # Build session-specific system prompt with memory context injected
        session_prompt = GM_SYSTEM_PROMPT
        if memory_context:
            session_prompt = GM_SYSTEM_PROMPT + "\n\n" + memory_context

        # Initialize game state
        region = random.choice(REGIONS)
        hp = 100
        sand_dollars = 50
        inventory = []
        turn = 0
        max_turns = 20
        encounter = None
        narrative_history = []

        pos_x, pos_y = region.get("grid", (25, 15))

        # Sync initial state
        sync_game_state(device_id, hp, sand_dollars, "explore", pos_x, pos_y)

        # "Previously on The Fading" recap if returning player
        if memories:
            # Build a readable summary of memory titles + first experience
            memory_summary = []
            for m in memories:
                title = m.get("memory_title", "")
                exps = m.get("experiences", [])
                first_exp = exps[0] if exps else ""
                memory_summary.append(f"{title}: {first_exp}" if first_exp else title)

            recap = self.capability_worker.text_to_text_response(
                f"Do a brief 'previously on The Fading' recap for a returning player. "
                f"Their active memories (title: first experience): {memory_summary}. "
                f"2-3 sentences max, voice-ready, evocative, first person. "
                f"Then transition: their airship now drifts toward {region['name']}.",
                system_prompt=session_prompt,
            )
            await self.capability_worker.speak(recap)
            narrative_history.append({"role": "gm", "text": recap})

        # Opening narration
        opening = self.capability_worker.text_to_text_response(
            f"{'Continue the session. ' if memories else 'Start a new game of AquaPrime: The Fading. '}"
            f"The player's airship arrives at {region['name']}. {region['desc']} "
            f"HP: {hp}. Sand Dollars: {sand_dollars}. "
            f"Set the scene in 2 sentences for voice. End with a question about what they do.",
            system_prompt=session_prompt,
        )
        await self.capability_worker.speak(opening)
        narrative_history.append({"role": "gm", "text": opening})

        # Game loop
        while turn < max_turns and hp > 0:
            try:
                user_input = await self.capability_worker.user_response()
            except Exception:
                await self.capability_worker.speak(
                    "The winds are silent. Are you still there? Say something or say stop to end."
                )
                continue

            if not user_input:
                await self.capability_worker.speak("I did not hear anything. What do you do?")
                continue

            if any(word in user_input.lower() for word in EXIT_WORDS):
                await self.capability_worker.speak(
                    f"The expedition ends. You survived {turn} turns with {sand_dollars} Sand Dollars "
                    f"and {len(inventory)} items. The Moonstone Maverick descends into the clouds. Until next time."
                )
                set_offline(device_id)
                return

            turn += 1
            action_text = user_input.strip()
            narrative_history.append({"role": "player", "text": action_text})

            if encounter is None:
                encounter = roll_encounter(region)

            d20 = roll_d20()
            stance_name, stance_mult = detect_stance(action_text)
            encounter_result = ""
            loot_gained = None
            success = False
            crit_fail = d20 <= 3

            if encounter:
                score = round(d20 * stance_mult)
                threshold = encounter["difficulty"] * 4
                success = score >= threshold

                if success:
                    sd_reward = 10 + random.randint(0, encounter["difficulty"] * 5)
                    sand_dollars += sd_reward
                    encounter_result = (
                        f"You rolled {d20} ({stance_name} stance, score {score} vs {threshold}). "
                        f"Success! Gained {sd_reward} Sand Dollars."
                    )
                    if random.random() < 0.4:
                        loot_gained = roll_loot()
                        if loot_gained:
                            inventory.append(loot_gained)
                            encounter_result += f" Found: {loot_gained['name']} ({loot_gained['rarity']})."
                else:
                    hp_loss = 5 + encounter["difficulty"] * 3
                    hp = max(0, hp - hp_loss)
                    encounter_result = (
                        f"You rolled {d20} ({stance_name} stance, score {score} vs {threshold}). "
                        f"Failed. Lost {hp_loss} HP."
                    )

                active_encounter_desc = f"Encounter: {encounter['name']}. {encounter['desc']}"
                encounter = None
            else:
                encounter_result = f"You rolled {d20}. No encounter this turn."
                active_encounter_desc = "No encounter."

            # Move regions every 4 turns
            if turn > 0 and turn % 4 == 0:
                new_region = random.choice(REGIONS)
                if new_region["name"] != region["name"]:
                    region = new_region
                    pos_x, pos_y = region.get("grid", (pos_x, pos_y))

            # Sync state to Supabase after each turn
            sync_game_state(device_id, hp, sand_dollars, stance_name, pos_x, pos_y)

            # Generate narration via LLM
            recent = narrative_history[-4:] if len(narrative_history) > 4 else narrative_history
            context_str = " | ".join(f"{n['role']}: {n['text'][:80]}" for n in recent)

            # Determine memory type and potential skill grant based on encounter
            mem_type, grants_ability = get_memory_type_for_encounter(
                encounter, success
            ) if encounter else ("lore", None)

            narration_prompt = (
                f"Game state: Region: {region['name']}. HP: {hp}/100. Sand Dollars: {sand_dollars}. "
                f"Inventory: {', '.join(i['name'] for i in inventory) if inventory else 'empty'}. "
                f"Turn {turn}/{max_turns}. {active_encounter_desc} "
                f"Mechanics result: {encounter_result} "
                f"Recent context: {context_str} "
                f"Player said: \"{action_text}\" "
                f"Narrate the outcome in 2-3 sentences for voice. "
                f"Include the dice roll result naturally. End with what happens next."
            )

            narration = self.capability_worker.text_to_text_response(
                narration_prompt,
                system_prompt=session_prompt,
            )
            await self.capability_worker.speak(narration)
            narrative_history.append({"role": "gm", "text": narration})

            # Extract single evocative experience sentence from the narration
            experience_text = self.capability_worker.text_to_text_response(
                f"Extract ONE evocative first-person sentence (max 15 words) that captures "
                f"the core moment of this narration. No preamble, just the sentence: {narration}",
                system_prompt="You extract the single most memorable sentence from game narration. First person, present tense, evocative, max 15 words.",
            ).strip().strip('"').strip("'")

            # Build memory theme from encounter or region
            if encounter:
                memory_theme = f"{encounter['name']} at {region['name']}"
            else:
                memory_theme = f"The {region['name']}"

            # Write this moment to node story and player memory
            mem_result = write_memory(
                device_id, pos_x, pos_y,
                narration=narration,
                experience_text=experience_text,
                memory_type=mem_type,
                memory_theme=memory_theme,
                grants_ability=grants_ability,
            )

            # Critical fail — if player has skills, one is at risk
            if crit_fail and mem_result:
                skill_memories = [m for m in memories if m.get("grants_ability")]
                if skill_memories:
                    lost = skill_memories[0]
                    await self.capability_worker.speak(
                        f"Critical fail. Your skill — {lost['grants_ability']} — fractures. "
                        f"That memory dissolves. The Fading takes it."
                    )
                    api_post("/api/voice/memory-erase", {
                        "device_id": device_id,
                        "slot_number": lost["slot_number"],
                    })
                    # Rebuild memories and session prompt
                    memories = fetch_memories(device_id)
                    memory_context = build_memory_context(memories)
                    session_prompt = GM_SYSTEM_PROMPT
                    if memory_context:
                        session_prompt = GM_SYSTEM_PROMPT + "\n\n" + memory_context

            # If all 5 memory slots are full, player must erase one to continue
            elif mem_result and mem_result.get("must_erase"):
                # Read back current memory titles so player knows what they have
                current_mems = fetch_memories(device_id)
                mem_list = " ".join(
                    f"Slot {m['slot_number']}: {m['memory_title']}."
                    for m in current_mems
                )
                await self.capability_worker.speak(
                    f"Your memory is full. Five containers locked. {mem_list} "
                    "Say the number of the memory you want to erase: "
                    "one, two, three, four, or five. "
                    "That moment is gone forever."
                )
                erase_input = await self.capability_worker.user_response()
                erase_map = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                             "1": 1, "2": 2, "3": 3, "4": 4, "5": 5}
                slot_to_erase = erase_map.get((erase_input or "").lower().strip())
                if slot_to_erase:
                    api_post("/api/voice/memory-erase", {
                        "device_id": device_id,
                        "slot_number": slot_to_erase,
                    })
                    await self.capability_worker.speak(
                        f"Memory slot {slot_to_erase} fades. The Fading takes it. "
                        f"You continue."
                    )
                    # Rebuild session prompt — erased memory no longer exists
                    memories = fetch_memories(device_id)
                    memory_context = build_memory_context(memories)
                    session_prompt = GM_SYSTEM_PROMPT
                    if memory_context:
                        session_prompt = GM_SYSTEM_PROMPT + "\n\n" + memory_context
                    # Retry the memory write now that a slot is free
                    write_memory(
                        device_id, pos_x, pos_y,
                        narration=narration,
                        experience_text=experience_text,
                        memory_type=mem_type,
                        memory_theme=memory_theme,
                        grants_ability=grants_ability,
                    )
            else:
                # Update local memories list after successful write
                memories = fetch_memories(device_id)
                memory_context = build_memory_context(memories)
                session_prompt = GM_SYSTEM_PROMPT
                if memory_context:
                    session_prompt = GM_SYSTEM_PROMPT + "\n\n" + memory_context

            if hp <= 0:
                await self.capability_worker.speak(
                    f"The Fading claims you. Zero HP after {turn} turns. "
                    f"You earned {sand_dollars} Sand Dollars and found {len(inventory)} items. "
                    f"Your memory dissolves into the grid. But memories are never truly lost in The Fading."
                )
                set_offline(device_id)
                return

        # Max turns reached
        item_names = ", ".join(i["name"] for i in inventory) if inventory else "nothing"
        await self.capability_worker.speak(
            f"The expedition ends after {max_turns} turns. "
            f"You have {hp} HP, {sand_dollars} Sand Dollars, and found {item_names}. "
            f"The Moonstone Maverick descends into the clouds. Another day survived in The Fading."
        )
        set_offline(device_id)
