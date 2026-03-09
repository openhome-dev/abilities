import datetime
import hashlib
import json
import os
import random
import socket
import urllib.request
import urllib.error

# ── Fate day-tracking (process-level, resets each boot) ──────────────
_fate_used_date: str | None = None


def fate_used_today() -> bool:
    return _fate_used_date == datetime.date.today().isoformat()


def mark_fate_used() -> None:
    global _fate_used_date
    _fate_used_date = datetime.date.today().isoformat()

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
#   - fading_memories = container (5 slots, themed)
#   - fading_experiences = 1 evocative sentence per turn (up to 3 per container)
#   - A slot is only consumed when a NEW memory container is created
#   - Skills = memories with grants_ability set; lost on critical fail
#
# Narrative Engine (Prompt Archetype System):
#   - Each turn draws one of 10 narrative archetypes
#   - Archetypes are MANDATES — the beat always happens
#   - Player's pilot NFT traits weight which archetype fires
#   - Player's voice phrasing determines mechanic: fate / recall / act
#   - d20 = movement (how far your ship travels), not success/fail resolution
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
        "desc": "Once lush sky-platforms, now scorched by a mass defection event. Charred moonstone fragments drift in the thermals.",
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

# ── Prompt Archetype System ──────────────────────────────────────────
#
# Each archetype is a NARRATIVE MANDATE — the beat always fires.
# The d20 roll determines HOW it resolves (severity, quality of outcome).
# Archetypes are weighted by the pilot's hormone levels and memory count.
#
# hormone_weights: multipliers applied to each hormone's 0.0-1.0 value.
#   e.g. {"adrenaline": 2.0} means high-adrenaline pilots see this 2x more.
# difficulty: threshold for the d20 check (score = d20 * stance_mult).
# requires_memories: if True, archetype cannot fire if player has 0 memories.

PROMPT_ARCHETYPES = [
    {
        "id": "loss",
        "directive": (
            "Something slips away this turn — a resource, a relationship, or a capability. "
            "The player does not get a choice about whether they lose it. "
            "The roll determines only how much, and what they understand about the loss."
        ),
        # Voice prompt to close the beat — names the consequence, tells the player to SPEAK the memory sentence
        "player_directive": {
            "success": "Something is gone. You're keeping your footing. Speak the loss — one sentence, first person. Make it specific.",
            "fail": "It took more than you had ready. Speak what's gone — one sentence, first person. Don't soften it.",
        },
        "memory_type": "lore",
        "triggers_skill_check": True,
        "skill_name": "Resilience",
        "hormone_weights": {"adrenaline": 1.5, "dopamine": 1.5},
        "difficulty": 12,
    },
    {
        "id": "encounter",
        "directive": (
            "A stranger arrives connected to the pilot's nature or past. "
            "If the pilot has memories, reference one. "
            "The roll determines whether this connection is useful or threatening."
        ),
        "player_directive": {
            "success": "Someone showed up who knew something about you. Speak the memory of the meeting — one sentence, first person.",
            "fail": "You gave something away before you understood the trade. Speak what you lost in that exchange — one sentence, first person.",
        },
        "memory_type": "relationship",
        "triggers_skill_check": False,
        "skill_name": "Reading People",
        "hormone_weights": {"oxytocin": 2.0},
        "difficulty": 8,
    },
    {
        "id": "hunted",
        "directive": (
            "Something has followed the player to this node. It knows their name. "
            "It may be a creature, a faction, or an echo of a past choice. "
            "The roll determines whether they escape, survive, or learn who hunts them."
        ),
        "player_directive": {
            "success": "You got out. Speak the memory of it — one sentence, first person. How you ran.",
            "fail": "It found you. Speak what it took — one sentence, first person. Don't say you fought back.",
        },
        "memory_type": "lore",
        "triggers_skill_check": True,
        "skill_name": "Evasion",
        "hormone_weights": {"adrenaline": 2.0},
        "difficulty": 14,
    },
    {
        "id": "discovery",
        "directive": (
            "This node holds a crystallized memory from someone who faded here before. "
            "The roll determines how much they can read — a clue, warning, or revelation."
        ),
        "player_directive": {
            "success": "You're carrying a secret out of this node that wasn't yours. Speak it — one sentence, first person. What it was.",
            "fail": "You got a fragment before it closed. Speak the fragment — one sentence, first person. Incomplete is fine.",
        },
        "memory_type": "secret",
        "triggers_skill_check": False,
        "skill_name": "Keen Eye",
        "hormone_weights": {"dopamine": 2.0},
        "difficulty": 6,
    },
    {
        "id": "temptation",
        "directive": (
            "Something is offered — power, safety, knowledge, or relief. "
            "The cost is not immediately visible. "
            "The roll determines whether they resist, and what refusing or accepting costs them."
        ),
        "player_directive": {
            "success": "You refused. Speak the refusal — one sentence, first person. What you said no to, and what it cost to say it.",
            "fail": "You took it. Speak the acceptance — one sentence, first person. Name what you accepted, not the cost.",
        },
        "memory_type": "resource",
        "triggers_skill_check": False,
        "skill_name": "Willpower",
        "hormone_weights": {"dopamine": 1.5, "adrenaline": 1.5},
        "difficulty": 10,
    },
    {
        "id": "fracture",
        "directive": (
            "The grid is wrong here. Navigation fails, instruments lie, physics bends. "
            "The roll determines whether the pilot reads the fracture or gets lost inside it."
        ),
        "player_directive": {
            "success": "You read the break. Speak what you saw in the gap — one sentence, first person. The thing that shouldn't be there.",
            "fail": "The fracture got inside you. Speak what you lost track of — one sentence, first person. You won't notice it missing until later.",
        },
        "memory_type": "lore",
        "triggers_skill_check": True,
        "skill_name": "Grid Navigation",
        "hormone_weights": {"adrenaline": 1.5, "serotonin": 0.5},
        "difficulty": 13,
    },
    {
        "id": "reckoning",
        "directive": (
            "A past action has consequences the player is only now seeing. "
            "REQUIRED: Reference one of the player's existing memory titles or experiences by name. "
            "Do not invent history — use only what is listed in PLAYER MEMORY above. "
            "The roll determines the severity of the reckoning."
        ),
        "player_directive": {
            "success": "It caught up with you and you were ready. Speak the moment you faced it — one sentence, first person.",
            "fail": "It was worse than you planned for. Speak what the reckoning took — one sentence, first person. Name the specific thing.",
        },
        "memory_type": "lore",
        "triggers_skill_check": False,
        "skill_name": "Pattern Recognition",
        "hormone_weights": {"serotonin": 1.5},
        "difficulty": 10,
        "requires_memories": True,
    },
    {
        "id": "signal",
        "directive": (
            "Something is trying to reach the pilot — a transmission, a pattern, a presence. "
            "It is not hostile. It may not be real. "
            "The roll determines how much they understand."
        ),
        "player_directive": {
            "success": "The signal resolved. Speak what it said — one sentence, first person. Just the content, not your reaction.",
            "fail": "You got fragments. Speak the fragment — one sentence, first person. Incomplete on purpose.",
        },
        "memory_type": "secret",
        "triggers_skill_check": False,
        "skill_name": "Signal Reading",
        "hormone_weights": {"serotonin": 2.0},
        "difficulty": 7,
    },
    {
        "id": "alliance",
        "directive": (
            "Someone wants to use the pilot, or be used by them. "
            "Reference the pilot's alignment or dominant hormone to flavor who this is. "
            "Trust is the currency. The roll determines who comes out ahead."
        ),
        "player_directive": {
            "success": "The deal held. Speak it — one sentence, first person. What you agreed to, not what you kept back.",
            "fail": "They walked away with more than the deal. Speak what they took — one sentence, first person. Be specific.",
        },
        "memory_type": "relationship",
        "triggers_skill_check": False,
        "skill_name": "Negotiation",
        "hormone_weights": {"oxytocin": 2.0, "serotonin": 1.5},
        "difficulty": 9,
    },
    {
        "id": "quiet",
        "directive": (
            "Nothing hunts the pilot today. The grid is still. "
            "What do they think about? What do they notice when the noise stops? "
            "The roll determines the quality of what they find in the silence."
        ),
        "player_directive": {
            "success": "The stillness gave you something. Speak it — one sentence, first person. What you noticed when there was nothing left to fight.",
            "fail": "The quiet was heavier than the danger. Speak what you couldn't stop thinking about — one sentence, first person.",
        },
        "memory_type": "lore",
        "triggers_skill_check": False,
        "skill_name": "Clarity",
        "hormone_weights": {"serotonin": 2.0, "oxytocin": 1.5},
        "difficulty": 5,
    },
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
    "Reference battery (0-100, depleted by the grid, refilled by burning MSTN), Sand Dollars, and inventory when relevant. "
    "CRITICAL: Never end a turn with 'What do you do?' — that is a lazy question. "
    "Instead, end with a specific mandate that names what the player GAINS or LOSES and tells them exactly what to narrate next. "
    "The beat has already happened. The player is voicing HOW it happened, not deciding IF. "
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


def fetch_pilot_traits(device_id: str) -> dict:
    """Fetch pilot NFT traits for archetype weighting and narrative flavor.

    Returns normalized hormone values (0.0-1.0), MBTI, alignment, hand trait.
    Falls back to neutral defaults if no NFT is linked to this device.
    """
    url = f"{BASE_URL}/api/voice/pilot-traits?device_id={device_id}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read())
    except Exception:
        return {
            "mbti": "INTJ",
            "alignment": "neutral",
            "dominant_hormone": "dopamine",
            "hormones": {"dopamine": 0.5, "serotonin": 0.5, "oxytocin": 0.5, "adrenaline": 0.5},
            "hand_trait": None,
            "hand_trait_desc": None,
        }


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
            lines.append("    • (no experiences recorded yet)")

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


def sync_game_state(device_id: str, battery: int, sand_dollars: int, stance: str,
                    pos_x: int, pos_y: int) -> None:
    """Push game state to Supabase (fire and forget — don't block the game loop)."""
    api_post("/api/voice/game-update", {
        "device_id": device_id,
        "hp": battery,
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
    experience_text → fading_experiences (single evocative sentence)
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


def has_memory_type(memories: list[dict], mtype: str) -> dict | None:
    """Return the first memory of the given type, or None."""
    return next((m for m in memories if m.get("memory_type") == mtype), None)


def fate_available(memories: list[dict]) -> bool:
    """Spinner available only if player carries a 'fate' memory and hasn't spun today."""
    return has_memory_type(memories, "fate") is not None and not fate_used_today()


def roll_movement() -> tuple[str, int]:
    """Roll d20 for node movement. Returns (label, distance in nodes).

    1-5   drift  — stay at current node (conditions worsen)
    6-10  short  — 1 node in chosen direction
    11-15 full   — 2 nodes in chosen direction
    16-20 surge  — 3 nodes; may push into high-danger region
    """
    roll = random.randint(1, 20)
    if roll <= 5:
        return ("drift", 0)
    if roll <= 10:
        return ("short", 1)
    if roll <= 15:
        return ("full", 2)
    return ("surge", 3)


def detect_action(text: str, memories: list[dict]) -> str:
    """Detect which mechanic the player is invoking.

    Returns: "fate" | "recall" | "act"

    "fate"   = invoke fate spinner (requires fate memory + once/day)
    "recall" = invoke a skill memory (auto-succeed if matching skill exists)
    "act"    = default (d20 movement roll, always available)
    """
    lower = text.lower()
    if any(w in lower for w in {"spin", "wheel", "spinner", "fate"}):
        return "fate"
    if any(w in lower for w in {"recall", "remember", "invoke", "use my skill", "my training", "i know"}):
        return "recall"
    return "act"


def write_loss_memory(device_id: str, pos_x: int, pos_y: int,
                      lost_memory: dict) -> None:
    """When a memory is erased, record the loss as a new lore experience.

    Loss generates story — the scar replaces the thing that was lost.
    This lore experience persists at the node for other players to find.
    """
    lost_title = lost_memory.get("memory_title", "something")
    lost_type = lost_memory.get("memory_type", "lore")
    lost_skill = lost_memory.get("grants_ability")

    if lost_type == "companion":
        experience = f"I watched {lost_title} disappear into the static and did not follow."
    elif lost_type == "skill" and lost_skill:
        experience = f"The fracture took {lost_skill}. I reached for it and found nothing."
    elif lost_type == "fate":
        experience = f"The wheel spun without me. I felt it leave."
    elif lost_type == "prisoner":
        experience = f"{lost_title} was gone before I decided what to do with them."
    else:
        experience = f"I lost {lost_title}. The Fading took it cleanly."

    write_memory(
        device_id, pos_x, pos_y,
        narration=experience,
        experience_text=experience,
        memory_type="lore",
        memory_theme=f"Loss of {lost_title}",
        grants_ability=None,
    )


def detect_direction(text: str) -> tuple[int, int]:
    """Parse cardinal direction from player input. Returns (dx, dy) delta."""
    lower = text.lower()
    if any(w in lower for w in {"north", "northward", "go up", "head up"}):
        return (0, -1)
    if any(w in lower for w in {"south", "southward", "go down", "head down"}):
        return (0, 1)
    if any(w in lower for w in {"east", "eastward", "go right", "head right"}):
        return (1, 0)
    if any(w in lower for w in {"west", "westward", "go left", "head left"}):
        return (-1, 0)
    return (0, 0)


def match_skill(player_input: str, memories: list[dict]) -> dict | None:
    """Return memory with grants_ability if player's recall input references it.

    If player mentions a specific skill name, return that memory.
    If player just says "recall" / "remember" without specifics, return first skill.
    """
    skill_memories = [m for m in memories if m.get("grants_ability")]
    if not skill_memories:
        return None
    lower = player_input.lower()
    for m in skill_memories:
        skill_words = m["grants_ability"].lower().split()
        if any(word in lower for word in skill_words):
            return m
    # Generic recall → use first available skill
    if any(w in lower for w in {"recall", "remember", "my training", "i know"}):
        return skill_memories[0]
    return None


def draw_archetype(memories: list[dict], pilot_traits: dict,
                   last_archetype_id: str | None = None) -> dict:
    """Select a narrative archetype using weighted random selection.

    Weights are biased by:
    - Pilot hormone levels (high adrenaline → more hunted/fracture, etc.)
    - Memory count (reckoning weighted 3x when 2+ memories exist)
    - No-repeat guard (same archetype cannot fire twice in a row)
    """
    hormones = pilot_traits.get("hormones", {})
    memory_count = len(memories)

    weights = []
    for a in PROMPT_ARCHETYPES:
        # Can't reckoning without memories to reference
        if a.get("requires_memories") and memory_count == 0:
            weights.append(0.0)
            continue
        # No immediate repeat
        if a["id"] == last_archetype_id:
            weights.append(0.0)
            continue

        w = 1.0

        # Boost reckoning heavily once enough memories exist
        if a["id"] == "reckoning" and memory_count >= 2:
            w *= 3.0

        # Hormone-based weighting: each hormone's deviation from 0.5 is amplified
        for hormone, mult in a.get("hormone_weights", {}).items():
            h_val = hormones.get(hormone, 0.5)
            w *= 1.0 + (h_val - 0.5) * (mult - 1.0)

        weights.append(max(0.01, w))

    return random.choices(PROMPT_ARCHETYPES, weights=weights, k=1)[0]


def build_pilot_prompt_line(pilot_traits: dict) -> str:
    """One-line pilot flavor for the narration prompt."""
    mbti = pilot_traits.get("mbti", "INTJ")
    dominant = pilot_traits.get("dominant_hormone", "dopamine")
    alignment = pilot_traits.get("alignment", "neutral")
    line = f"PILOT: {mbti} ({alignment}), dominant {dominant}."
    hand = pilot_traits.get("hand_trait")
    if hand:
        line += f" Hand trait: {hand}."
    return line


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
            await self.capability_worker.speak("Connecting to the grid...")

        # Load persistent memories and pilot traits
        memories = fetch_memories(device_id)
        pilot_traits = fetch_pilot_traits(device_id)
        memory_context = build_memory_context(memories)

        # Build session-specific system prompt
        mbti = pilot_traits.get("mbti", "INTJ")
        dominant = pilot_traits.get("dominant_hormone", "dopamine")
        alignment = pilot_traits.get("alignment", "neutral")

        pilot_flavor = (
            f"\n\nPILOT PROFILE: This pilot is {mbti}, {alignment} alignment, "
            f"driven by {dominant}. "
            f"Narration should reflect their nature: "
            f"dopamine craves novelty and discovery, adrenaline courts danger, "
            f"oxytocin seeks connection, serotonin seeks structure and order."
        )
        hand_trait = pilot_traits.get("hand_trait")
        if hand_trait:
            pilot_flavor += f" Their hand trait: {hand_trait} — {pilot_traits.get('hand_trait_desc', '')}."

        session_prompt = GM_SYSTEM_PROMPT + pilot_flavor
        if memory_context:
            session_prompt += "\n\n" + memory_context

        # Initialize game state
        region = random.choice(REGIONS)
        battery = 100
        sand_dollars = 50
        inventory = []
        turn = 0
        max_turns = 20
        last_archetype_id = None
        narrative_history = []
        companion_saved = False  # companion absorbs battery loss once per session

        pos_x, pos_y = region.get("grid", (25, 15))
        sync_game_state(device_id, battery, sand_dollars, "explore", pos_x, pos_y)

        # "Previously on The Fading" recap if returning player
        if memories:
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
            f"Battery: {battery}%. Sand Dollars: {sand_dollars}. "
            f"Set the scene in 2 sentences for voice. End with a question about what they do.",
            system_prompt=session_prompt,
        )
        await self.capability_worker.speak(opening)
        narrative_history.append({"role": "gm", "text": opening})

        # ── Game Loop ───────────────────────────────────────────────
        while turn < max_turns and battery > 0:
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

            # ── Movement (d20 = how far you travel) ─────────────────
            move_label, distance = roll_movement()
            if distance > 0:
                dx, dy = detect_direction(action_text)
                if dx == 0 and dy == 0:
                    dx, dy = random.choice([(0, -1), (0, 1), (1, 0), (-1, 0)])
                pos_x = max(0, min(50, pos_x + dx * distance))
                pos_y = max(0, min(50, pos_y + dy * distance))

            # Region shifts on surge into new territory
            region_danger = region.get("danger", 2)
            if move_label == "surge" and random.random() < 0.5:
                candidates = [r for r in REGIONS if r.get("danger", 2) >= region_danger]
                if candidates:
                    region = random.choice(candidates)
                    pos_x, pos_y = region.get("grid", (pos_x, pos_y))
                    region_danger = region.get("danger", 2)

            # ── Archetype Draw ──────────────────────────────────────
            archetype = draw_archetype(memories, pilot_traits, last_archetype_id)
            last_archetype_id = archetype["id"]

            # ── Action Detection ────────────────────────────────────
            action = detect_action(action_text, memories)
            gm_context = ""
            crit_fail = False
            success = False
            encounter_result = ""
            sd_reward = 0
            loot_gained = None

            # ── Fate (spinner — requires fate memory, once/day) ─────
            if action == "fate":
                if fate_available(memories):
                    mark_fate_used()
                    spin_result = api_post("/api/voice/spin", {"device_id": device_id})
                    if spin_result and not spin_result.get("error"):
                        cat = spin_result.get("category", "fortune")
                        name = spin_result.get("name", "fate")
                        hint = spin_result.get("gm_hint", "")
                        if cat == "fortune":
                            battery_gain = random.randint(20, 40)
                            battery = min(100, battery + battery_gain)
                            sd_reward = random.randint(15, 30)
                            sand_dollars += sd_reward
                            encounter_result = f"Fate: {name}. +{battery_gain}% battery, +{sd_reward} SD."
                        elif cat == "misfortune":
                            battery_loss = random.randint(5, 15)
                            battery = max(0, battery - battery_loss)
                            encounter_result = f"Fate: {name}. -{battery_loss}% battery."
                        else:
                            sd_reward = random.randint(5, 50)
                            sand_dollars += sd_reward
                            encounter_result = f"Fate: {name}. +{sd_reward} SD."
                        gm_context = f"Fate spun: {name}. {hint} "
                        if spin_result.get("narrative_twist"):
                            gm_context += spin_result["narrative_twist"] + " "
                    success = True
                else:
                    fate_mem = has_memory_type(memories, "fate")
                    if not fate_mem:
                        gm_context = "The wheel does not recognize this pilot — no fate memory carried. "
                    else:
                        gm_context = "Fate already spun today. The wheel is still. "
                    action = "act"

            # ── Recall (skill memory — auto-succeed if match) ───────
            if action == "recall":
                skill_mem = match_skill(action_text, memories)
                if skill_mem:
                    success = True
                    gm_context += f"Invokes memory: {skill_mem.get('memory_title', 'unknown')}. Auto-success. "
                    encounter_result = f"Recalled {skill_mem.get('grants_ability', 'skill')}. Automatic success."
                    sd_reward = 10 + random.randint(0, 15)
                    sand_dollars += sd_reward
                else:
                    action = "act"

            # ── Act (default — d20 vs archetype difficulty) ─────────
            if action == "act":
                d20 = roll_d20()
                threshold = archetype["difficulty"] + (region_danger - 2)
                stance_name, stance_mult = detect_stance(action_text)
                score = round(d20 * stance_mult)
                success = score >= threshold
                crit_fail = d20 <= 3

                if not success and not companion_saved:
                    companion_mem = has_memory_type(memories, "companion")
                    if companion_mem:
                        companion_saved = True
                        companion_name = companion_mem.get("memory_title", "your companion")
                        gm_context += f"{companion_name} steps between you and it. Battery protected. "
                        encounter_result = (
                            f"Rolled d20: {d20} ({stance_name}, score {score} vs {threshold}). "
                            f"Companion shields you."
                        )
                        success = True
                    else:
                        battery_loss = 5 + threshold // 2
                        battery = max(0, battery - battery_loss)
                        encounter_result = (
                            f"Moved {move_label} ({distance} nodes). "
                            f"Rolled d20: {d20} ({stance_name}, score {score} vs {threshold}). "
                            f"Failed. -{battery_loss}% battery."
                        )
                elif success:
                    sd_reward = 10 + random.randint(0, archetype["difficulty"] * 3)
                    sand_dollars += sd_reward
                    loot_gained = roll_loot() if random.random() < 0.30 else None
                    if loot_gained:
                        inventory.append(loot_gained)
                    encounter_result = (
                        f"Moved {move_label} ({distance} nodes). "
                        f"Rolled d20: {d20} ({stance_name}, score {score} vs {threshold}). "
                        f"Success! +{sd_reward} SD."
                        + (f" Found {loot_gained['name']}." if loot_gained else "")
                    )

            # ── Memory Write ─────────────────────────────────────────
            mem_type = archetype["memory_type"]
            grants_ability = archetype["skill_name"] if (success and archetype["triggers_skill_check"]) else None
            memory_theme = f"{archetype['id'].title()} at {region['name']}"

            # ── Build memory type context for ARI ────────────────────
            asset_lines = []
            c_mem = has_memory_type(memories, "companion")
            if c_mem:
                asset_lines.append(f"COMPANION ON SHIP: {c_mem.get('memory_title', 'unknown')} — reference them naturally")
            p_mem = has_memory_type(memories, "prisoner")
            if p_mem:
                asset_lines.append(f"PRISONER/VISITOR: {p_mem.get('memory_title', 'unknown')} — leverage available")
            f_mem = has_memory_type(memories, "fate")
            if f_mem:
                asset_lines.append(f"FATE MEMORY: {f_mem.get('memory_title', 'unknown')} — they carry the wheel")
            if action == "recall" and success:
                asset_lines.append(f"SKILL INVOKED: {skill_mem.get('grants_ability', 'skill')}")
            asset_context = "\n".join(asset_lines)

            # ── Narration Prompt ─────────────────────────────────────
            recent = narrative_history[-4:] if len(narrative_history) > 4 else narrative_history
            context_str = " | ".join(f"{n['role']}: {n['text'][:80]}" for n in recent)

            narration_prompt = (
                f"NARRATIVE DIRECTIVE: {archetype['directive']}\n"
                f"{build_pilot_prompt_line(pilot_traits)}\n"
                f"Movement: {move_label} ({distance} nodes). Region: {region['name']} (danger {region_danger}/4).\n"
                + (f"{asset_context}\n" if asset_context else "")
                + f"{gm_context}"
                f"Game state: Battery: {battery}%. Sand Dollars: {sand_dollars}. "
                f"Turn {turn}/{max_turns}.\n"
                f"Mechanics result: {encounter_result}\n"
                f"Recent context: {context_str}\n"
                f"Player said: \"{action_text}\"\n"
                f"Narrate the outcome in 2-3 sentences. "
                f"Use companions/prisoners/skills listed above naturally — don't announce them, just use them. "
                f"IMPORTANT: Do NOT end with 'What do you do?' — end with this exact mandate for the player to voice: "
                f"\"{archetype['player_directive']['success' if success else 'fail']}\"\n"
                f"Then on a new line write exactly: MEMORY: [one evocative first-person sentence, max 15 words]"
            )

            raw_response = self.capability_worker.text_to_text_response(
                narration_prompt,
                system_prompt=session_prompt,
            )

            # Split narration from embedded MEMORY tag
            if "MEMORY:" in raw_response:
                parts = raw_response.split("MEMORY:", 1)
                narration = parts[0].strip()
                experience_text = parts[1].strip().strip("[]").strip('"').strip("'")
            else:
                narration = raw_response.strip()
                experience_text = narration[:100]

            # Sync state to Supabase
            stance_label = detect_stance(action_text)[0]
            sync_game_state(device_id, battery, sand_dollars, stance_label, pos_x, pos_y)

            # Write memory
            mem_result = write_memory(
                device_id, pos_x, pos_y,
                narration=narration,
                experience_text=experience_text,
                memory_type=mem_type,
                memory_theme=memory_theme,
                grants_ability=grants_ability,
            )

            # ── Critical Fail — lose a memory, gain its scar ─────────
            if crit_fail and mem_result:
                # Prefer to lose a skill memory; fall back to any memory
                skill_memories = [m for m in memories if m.get("grants_ability")]
                erasable = skill_memories if skill_memories else memories
                if erasable:
                    lost = erasable[0]
                    lost_type = lost.get("memory_type", "lore")
                    lost_title = lost.get("memory_title", "something")
                    lost_skill = lost.get("grants_ability")
                    # Write the scar before erasing — loss generates story
                    write_loss_memory(device_id, pos_x, pos_y, lost)
                    await self.capability_worker.speak(
                        f"Critical fail. "
                        + (f"Your skill — {lost_skill} — fractures. " if lost_skill else f"{lost_title} is gone. ")
                        + "The Fading takes it. But the loss leaves a mark — you carry the scar."
                    )
                    api_post("/api/voice/memory-erase", {
                        "device_id": device_id,
                        "slot_number": lost["slot_number"],
                    })
                    memories = fetch_memories(device_id)
                    memory_context = build_memory_context(memories)
                    session_prompt = GM_SYSTEM_PROMPT + pilot_flavor
                    if memory_context:
                        session_prompt += "\n\n" + memory_context

            # ── Memory Full — player must erase ─────────────────────
            elif mem_result and mem_result.get("must_erase"):
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
                    # Write the scar before erasing
                    slot_mem = next((m for m in current_mems if m.get("slot_number") == slot_to_erase), None)
                    if slot_mem:
                        write_loss_memory(device_id, pos_x, pos_y, slot_mem)
                    api_post("/api/voice/memory-erase", {
                        "device_id": device_id,
                        "slot_number": slot_to_erase,
                    })
                    await self.capability_worker.speak(
                        f"Memory slot {slot_to_erase} fades. The Fading takes it. "
                        f"But the loss leaves a mark — you carry the scar."
                    )
                    memories = fetch_memories(device_id)
                    memory_context = build_memory_context(memories)
                    session_prompt = GM_SYSTEM_PROMPT + pilot_flavor
                    if memory_context:
                        session_prompt += "\n\n" + memory_context
                    write_memory(
                        device_id, pos_x, pos_y,
                        narration=narration,
                        experience_text=experience_text,
                        memory_type=mem_type,
                        memory_theme=memory_theme,
                        grants_ability=grants_ability,
                    )

            else:
                memories = fetch_memories(device_id)
                memory_context = build_memory_context(memories)
                session_prompt = GM_SYSTEM_PROMPT + pilot_flavor
                if memory_context:
                    session_prompt += "\n\n" + memory_context

            await self.capability_worker.speak(narration)
            narrative_history.append({"role": "gm", "text": narration})

            if battery <= 0:
                await self.capability_worker.speak(
                    f"Battery depleted. The grid takes you after {turn} turns. "
                    f"You earned {sand_dollars} Sand Dollars and found {len(inventory)} items. "
                    f"Your signal dissolves into the static. But signals are never truly lost in The Fading."
                )
                set_offline(device_id)
                return

        # Max turns reached
        item_names = ", ".join(i["name"] for i in inventory) if inventory else "nothing"
        await self.capability_worker.speak(
            f"The expedition ends after {max_turns} turns. "
            f"Battery at {battery}%. {sand_dollars} Sand Dollars. Found: {item_names}. "
            f"The Moonstone Maverick descends into the clouds. Another day survived in The Fading."
        )
        set_offline(device_id)
