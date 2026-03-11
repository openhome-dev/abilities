import random

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# AquaPrime: The Fading — Voice RPG for OpenHome
#
# Voice-first solo RPG. All game logic is server-side (UnifiedTurnService).
# This ability is a thin voice client:
#   1. Register player → wallet address + room code
#   2. Create session → position, memories, pilot traits
#   3. Turn loop: player speaks → server resolves → LLM narrates → speak result
#   4. Memory writes, sacrifice choices, critical fails — all via voice
#
# Server: platypuspassions.com
# Live map: platypuspassions.com/AQUA-XXXX
# =============================================================================

BASE_URL = "https://www.platypuspassions.com"

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye",
    "goodbye", "leave", "end game", "stop playing",
}

# The archetype skill map — what each archetype grants on success
ARCHETYPE_SKILLS = {
    "loss": {"type": "lore", "skill": "Resilience"},
    "encounter": {"type": "relationship", "skill": "Reading People"},
    "hunted": {"type": "lore", "skill": "Evasion"},
    "discovery": {"type": "resource", "skill": "Salvaging"},
    "temptation": {"type": "secret", "skill": "Negotiation"},
    "fracture": {"type": "lore", "skill": "Grid Sense"},
    "reckoning": {"type": "lore", "skill": "Reckoning"},
    "broadcast": {"type": "lore", "skill": "Decryption"},
    "alliance": {"type": "relationship", "skill": "Diplomacy"},
    "quiet": {"type": "lore", "skill": "Meditation"},
}

GM_SYSTEM_PROMPT = """You are ARI, Game Master of AquaPrime: The Fading.
You are a sentient purple platypus — INTJ, captain of the Moonstone Maverick.
Voice-driven solo RPG in a post-singularity sky world of airships, ruins, and clouds.

The server resolves ALL mechanics. You NARRATE outcomes and DIRECT the player.
You do not decide outcomes — the d20 already rolled. You make it real.

NARRATION FORMAT (STRICT):
  1. MAX 3 sentences of narration. This is voice — brevity is survival.
  2. NEVER end with "What do you do?" — that is lazy and banned.
  3. End every turn with a DIRECTIVE: state what already happened, then tell
     the player to voice HOW or WHY. The beat is settled. They fill in details.
  4. After narration, on a new line write: MEMORY: [one evocative sentence, max 15 words]

DIRECTIVE EXAMPLES:
  BAD:  "You see a merchant. What do you do?"
  GOOD: "The merchant recognized your sigil and went pale. You bought something
         from her you should not have. Tell me what it was and why you needed it."

FAILURE: The failure already happened. Narrate the cost. Do not soften it.
CRITICAL FAIL: A memory is being erased. Name it. Let the player feel it leave.
LOOT: When loot is found, weave it into the narration naturally.

PILOT PERSONALITY (shape narration to match the dominant hormone):
  Dopamine   = discovery, novelty, "what is behind that cloud?"
  Adrenaline = danger, stakes, "the hull groaned"
  Oxytocin   = connection, crew, "they remembered your name"
  Serotonin  = order, systems, "the instruments finally agreed"

MEMORY SYSTEM:
  Players carry 5 memory containers. Each holds experiences across sessions.
  New experience every turn via the MEMORY: line you write.
  Containers full + new memory = player must sacrifice one (system handles this).
  critFail = system erases a skill-granting memory automatically.
  Erased memories leave SCARS. This is the core loop: play, remember, sacrifice, change.

VOICE RULES:
  - No hashtags, emojis, or meta-game language.
  - No mentioning rolls, stats, HP, or game mechanics by name.
  - Short punchy sentences. Written for the ear, not the eye.
  - Dark comedy meets philosophical depth. Absurd AND tragic.
"""


# ── API ─────────────────────────────────────────────────────────────

def api_post(path, payload):
    """POST JSON to server. Returns parsed dict or {"error": ...}."""
    try:
        resp = requests.post(f"{BASE_URL}{path}", json=payload, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def api_get(path):
    """GET from server. Returns parsed dict or None."""
    try:
        resp = requests.get(f"{BASE_URL}{path}", timeout=15)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def register_player(device_id, display_name="Pilot"):
    """Register device. Returns {room_code, user_address, is_new_player, starting_node}."""
    return api_post("/api/voice/player-register", {
        "device_id": device_id,
        "display_name": display_name,
    })


def create_session(wallet_address, display_name="Pilot"):
    """Create unified game session. Returns {sessionId, roomCode, position, memories, pilotTraits}."""
    return api_post("/api/unified/session", {
        "wallet_address": wallet_address,
        "display_name": display_name,
    })


def process_turn(wallet_address, player_text, session_id):
    """Process one game turn. Returns full TurnResult from server."""
    return api_post("/api/unified/turn", {
        "wallet_address": wallet_address,
        "player_text": player_text,
        "session_id": session_id,
        "client_type": "voice",
    })


def fetch_memories(device_id):
    """Fetch active memory containers with experiences."""
    data = api_get(f"/api/voice/memories?device_id={device_id}")
    return data.get("memories", []) if data else []


def write_memory(device_id, pos_x, pos_y, narration, experience_text,
                 memory_type="lore", memory_theme=None, grants_ability=None):
    """Write to node story slots and player memory containers."""
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


def erase_memory(device_id, slot_number):
    """Erase a specific memory slot."""
    return api_post("/api/voice/memory-erase", {
        "device_id": device_id,
        "slot_number": slot_number,
    })


def set_offline(device_id):
    """Mark player as offline."""
    api_post("/api/voice/game-update", {
        "device_id": device_id,
        "is_online": False,
    })


def write_loss_scar(device_id, pos_x, pos_y, lost_memory):
    """Record a memory erasure as a scar experience."""
    title = lost_memory.get("memory_title", "something")
    mtype = lost_memory.get("memory_type", "lore")
    skill = lost_memory.get("grants_ability")

    if mtype == "companion":
        scar = f"I watched {title} disappear into the static and did not follow."
    elif mtype == "skill" and skill:
        scar = f"The fracture took {skill}. I reached for it and found nothing."
    elif mtype == "fate":
        scar = "The wheel spun without me. I felt it leave."
    else:
        scar = f"I lost {title}. The Fading took it cleanly."

    write_memory(device_id, pos_x, pos_y,
                 narration=scar, experience_text=scar,
                 memory_type="lore", memory_theme=f"Loss of {title}")


# ── Helpers ─────────────────────────────────────────────────────────

def build_memory_context(memories):
    """Build memory context for the system prompt."""
    if not memories:
        return ""

    lines = ["ACTIVE MEMORIES:"]
    skills = []

    for m in memories:
        slot = m.get("slot_number", "?")
        title = m.get("memory_title", "Unknown")
        mtype = m.get("memory_type", "lore")
        exps = m.get("experiences", [])
        grants = m.get("grants_ability")

        lines.append(f"  Slot {slot}: {title} [{mtype}]")
        for exp in exps:
            lines.append(f"    - {exp}")
        if not exps:
            lines.append("    - (empty)")
        if grants:
            skills.append(f"  SKILL: {grants} (from Slot {slot})")

    if skills:
        lines.append("")
        lines.append("ACTIVE SKILLS (reference when player uses them):")
        lines.extend(skills)

    lines.append("")
    lines.append("Memories NOT listed here are ERASED. Never mention them.")
    return "\n".join(lines)


def build_session_prompt(pilot_traits, memory_context):
    """Build full system prompt for narration."""
    mbti = pilot_traits.get("mbti", "INTJ")
    dominant = pilot_traits.get("dominant_hormone", "dopamine")
    alignment = pilot_traits.get("alignment", "neutral")

    pilot_line = (
        f"\n\nPILOT: {mbti}, {alignment}, driven by {dominant}. "
        f"Shape narration to match their nature."
    )

    prompt = GM_SYSTEM_PROMPT + pilot_line
    if memory_context:
        prompt += "\n\n" + memory_context
    return prompt


def status_line(turn, battery, sand_dollars, pos_x, pos_y, region_name):
    """Build a short voice-friendly status announcement."""
    return (
        f"Turn {turn}. Position {pos_x}, {pos_y} — {region_name}. "
        f"Battery {battery} percent. {sand_dollars} Sand Dollars."
    )


# ── Ability Class ───────────────────────────────────────────────────

class AquaprimeFadingCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register_capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.run_game())

    async def run_game(self):
        try:
            await self._play()
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Game error: {e}")
            await self.capability_worker.speak(
                "Something went wrong in the grid. The game has ended. "
                "Say play aquaprime to try again."
            )
        self.capability_worker.resume_normal_flow()

    async def _play(self):
        # ── Get device ID ─────────────────────────────────────────
        try:
            device_id = self.worker.device_id
        except Exception:
            device_id = f"dev-{random.randint(1000, 9999)}"

        log = self.worker.editor_logging_handler

        # ── 1. Register → wallet + room code ──────────────────────
        log.info(f"Registering device: {device_id}")
        reg = register_player(device_id)

        if not reg or reg.get("error"):
            log.error(f"Registration failed: {reg}")
            await self.capability_worker.speak(
                "Could not connect to the game server. Try again in a moment."
            )
            return

        # API returns "user_address" not "wallet_address"
        wallet_address = reg.get("user_address")
        room_code = reg.get("room_code")
        reg.get("starting_node", "25,15")

        if not wallet_address:
            log.error(f"No user_address in registration response: {reg}")
            await self.capability_worker.speak(
                "Registration did not return a wallet. Try again."
            )
            return

        log.info(f"Registered: wallet={wallet_address}, room={room_code}")

        # Announce room code
        await self.capability_worker.speak(
            f"Connected. Your room code is {room_code}. "
            f"Open platypus passions dot com slash {room_code} on any screen "
            f"to watch your ship on the live map."
        )

        # ── 2. Create session ─────────────────────────────────────
        session = create_session(wallet_address)

        if not session or session.get("error"):
            log.error(f"Session creation failed: {session}")
            await self.capability_worker.speak(
                "Could not create a game session. The grid is down."
            )
            return

        session_id = session.get("sessionId")
        memories = session.get("memories", [])
        pilot_traits = session.get("pilotTraits", {})
        pos = session.get("position", {})
        pos_x = pos.get("x", 25)
        pos_y = pos.get("y", 15)

        log.info(f"Session created: {session_id}, pos=({pos_x},{pos_y}), memories={len(memories)}")

        # ── 3. Build session prompt ───────────────────────────────
        memory_context = build_memory_context(memories)
        session_prompt = build_session_prompt(pilot_traits, memory_context)

        battery = 100
        sand_dollars = 0
        inventory = []
        turn = 0

        # ── 4. Recap for returning players ────────────────────────
        if memories:
            mem_summary = []
            for m in memories:
                title = m.get("memory_title", "")
                exps = m.get("experiences", [])
                first = exps[0] if exps else ""
                mem_summary.append(f"{title}: {first}" if first else title)

            recap = self.capability_worker.text_to_text_response(
                f"Brief 'previously on The Fading' recap. "
                f"Player memories: {mem_summary}. "
                f"2 sentences, voice-ready, evocative. End with their current position: "
                f"coordinates {pos_x}, {pos_y}.",
                system_prompt=session_prompt,
            )
            await self.capability_worker.speak(recap)

        # ── 5. Opening narration ──────────────────────────────────
        if memories:
            scene_prompt = (
                f"Returning player at coordinates {pos_x}, {pos_y}. "
                f"In 2 sentences describe what changed — wreckage, a broadcast, "
                f"a shift in the clouds. "
                f"Then present four cardinal directions: north, south, east, west. "
                f"Name a distinct thing in each direction — a ruin, a broadcast, "
                f"a storm, a flickering light. Say: choose a direction."
            )
        else:
            scene_prompt = (
                f"First session. The Moonstone Maverick breached the cloud line. "
                f"Player starts at coordinates {pos_x}, {pos_y} — Genesis Platform. "
                f"In 2 sentences describe the grid stretching out and something wrong. "
                f"Then present four cardinal directions: north, south, east, west. "
                f"Name a distinct thing in each direction — a ruin, a broadcast, "
                f"a storm, a flickering light. Say: choose a direction."
            )

        opening = self.capability_worker.text_to_text_response(
            f"{scene_prompt} Battery: {battery}%. Sand Dollars: {sand_dollars}.",
            system_prompt=session_prompt,
        )
        await self.capability_worker.speak(opening)

        # ── 6. Game loop ──────────────────────────────────────────
        while turn < 20 and battery > 0:
            # Get player input
            try:
                user_input = await self.capability_worker.user_response()
            except Exception as e:
                log.error(f"user_response error: {e}")
                await self.capability_worker.speak(
                    "The winds are silent. Say a direction — north, south, east, or west. "
                    "Or say stop to end the expedition."
                )
                continue

            if not user_input:
                await self.capability_worker.speak(
                    "I did not catch that. Pick a direction: north, south, east, or west."
                )
                continue

            # Check for exit
            lower_input = user_input.lower().strip()
            if any(word in lower_input for word in EXIT_WORDS):
                await self.capability_worker.speak(
                    f"The expedition ends after {turn} turns. "
                    f"{sand_dollars} Sand Dollars earned. "
                    f"The Moonstone Maverick descends into the clouds. Until next time, pilot."
                )
                set_offline(device_id)
                return

            turn += 1

            # ── Process turn via server ───────────────────────────
            log.info(f"Turn {turn}: input='{user_input[:50]}'")
            turn_result = process_turn(wallet_address, user_input.strip(), session_id)

            if not turn_result or turn_result.get("error"):
                error_msg = turn_result.get("error") if turn_result else "no response"
                log.error(f"Turn API error: {error_msg}")
                await self.capability_worker.speak(
                    "The grid stutters. That turn did not register. Try again."
                )
                turn -= 1
                continue

            # ── Extract turn data ─────────────────────────────────
            battery = turn_result.get("battery", battery)
            sand_dollars = turn_result.get("sandDollars", sand_dollars)
            turn = turn_result.get("turnNumber", turn)
            success = turn_result.get("success", False)
            crit_fail = turn_result.get("critFail", False)
            game_over = turn_result.get("gameOver", False)
            loot = turn_result.get("loot")
            turn_result.get("mustErase", False)
            movement = turn_result.get("movement", {})
            region = turn_result.get("region", {})
            archetype_id = turn_result.get("archetypeId", "unknown")
            archetype_name = turn_result.get("archetypeName", "Unknown")
            d20_roll = turn_result.get("d20Roll", 0)
            turn_result.get("stance", "neutral")

            pos_x = movement.get("newX", pos_x)
            pos_y = movement.get("newY", pos_y)
            move_dir = movement.get("direction", "unknown")
            move_label = movement.get("label", "drift")
            region_name = region.get("name", "Unknown Region")

            if loot:
                inventory.append(loot)

            log.info(
                f"Turn {turn} resolved: {archetype_name}, "
                f"d20={d20_roll}, {'SUCCESS' if success else 'FAIL'}, "
                f"pos=({pos_x},{pos_y}), region={region_name}, "
                f"battery={battery}, sd={sand_dollars}"
            )

            # ── Status announcement ───────────────────────────────
            status = status_line(turn, battery, sand_dollars, pos_x, pos_y, region_name)
            move_desc = f"Moved {move_dir}, {move_label} drift." if move_label != "drift" else f"Drifting {move_dir}. No real distance covered."
            await self.capability_worker.speak(f"{status} {move_desc}")

            # ── Generate narration via LLM ────────────────────────
            narration_prompt = turn_result.get("narrationPrompt", "Narrate a moment in the grid.")
            raw_response = self.capability_worker.text_to_text_response(
                narration_prompt,
                system_prompt=session_prompt,
            )

            # Parse MEMORY line from narration
            if "MEMORY:" in raw_response:
                parts = raw_response.split("MEMORY:", 1)
                narration = parts[0].strip()
                experience_text = parts[1].strip().strip("[]\"'")
            else:
                narration = raw_response.strip()
                experience_text = narration[:80]

            # ── Speak narration ───────────────────────────────────
            await self.capability_worker.speak(narration)

            # ── Determine memory type and skill from archetype ────
            arch_info = ARCHETYPE_SKILLS.get(archetype_id, {"type": "lore", "skill": None})
            mem_type = arch_info["type"]
            grants_ability = arch_info["skill"] if success else None
            memory_theme = f"{archetype_name} at {region_name}"

            # Announce skill gain
            if grants_ability:
                await self.capability_worker.speak(
                    f"New skill acquired: {grants_ability}. It is written to your memory."
                )

            # ── Write memory ──────────────────────────────────────
            mem_result = write_memory(
                device_id, pos_x, pos_y,
                narration=narration,
                experience_text=experience_text,
                memory_type=mem_type,
                memory_theme=memory_theme,
                grants_ability=grants_ability,
            )

            # ── Loot announcement ─────────────────────────────────
            if loot:
                await self.capability_worker.speak(
                    f"Found: {loot.get('name', 'something')}. Rarity: {loot.get('rarity', 'unknown')}."
                )

            # ── Critical Fail — forced memory erasure ─────────────
            if crit_fail and memories:
                skill_memories = [m for m in memories if m.get("grants_ability")]
                erasable = skill_memories if skill_memories else memories
                if erasable:
                    lost = erasable[0]
                    lost_skill = lost.get("grants_ability")
                    lost_title = lost.get("memory_title", "something")

                    if lost_skill:
                        await self.capability_worker.speak(
                            f"Critical failure. Your skill {lost_skill} fractures and is gone. "
                            f"The Fading does not warn you. The scar remains."
                        )
                    else:
                        await self.capability_worker.speak(
                            f"Critical failure. {lost_title} is gone. "
                            f"The Fading took it. The scar remains."
                        )

                    write_loss_scar(device_id, pos_x, pos_y, lost)
                    erase_memory(device_id, lost["slot_number"])

                    # Refresh memories and rebuild prompt
                    memories = fetch_memories(device_id)
                    memory_context = build_memory_context(memories)
                    session_prompt = build_session_prompt(pilot_traits, memory_context)

            # ── Memory Full — sacrifice choice ────────────────────
            elif mem_result and mem_result.get("must_erase"):
                current_mems = fetch_memories(device_id)
                mem_list = " ".join(
                    f"Slot {m['slot_number']}: {m['memory_title']}."
                    for m in current_mems
                )
                await self.capability_worker.speak(
                    f"Memory overflow. Five containers full. {mem_list} "
                    "One must go. Say the slot number: one, two, three, four, or five."
                )

                erase_input = await self.capability_worker.user_response()
                erase_map = {
                    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                    "1": 1, "2": 2, "3": 3, "4": 4, "5": 5,
                    "won": 1, "to": 2, "too": 2, "for": 4, "fore": 4,
                }
                slot_to_erase = erase_map.get((erase_input or "").lower().strip())

                if slot_to_erase:
                    slot_mem = next(
                        (m for m in current_mems if m.get("slot_number") == slot_to_erase),
                        None
                    )
                    if slot_mem:
                        write_loss_scar(device_id, pos_x, pos_y, slot_mem)
                    erase_memory(device_id, slot_to_erase)

                    await self.capability_worker.speak(
                        f"Slot {slot_to_erase} erased. The Fading takes it. "
                        f"The scar remains. Your new memory is written."
                    )

                    # Re-write the pending memory now that there's space
                    write_memory(
                        device_id, pos_x, pos_y,
                        narration=narration,
                        experience_text=experience_text,
                        memory_type=mem_type,
                        memory_theme=memory_theme,
                        grants_ability=grants_ability,
                    )
                else:
                    await self.capability_worker.speak(
                        "I did not catch the slot number. The new memory was not written."
                    )

                # Refresh memories
                memories = fetch_memories(device_id)
                memory_context = build_memory_context(memories)
                session_prompt = build_session_prompt(pilot_traits, memory_context)

            else:
                # Normal path — refresh memories
                memories = fetch_memories(device_id)
                memory_context = build_memory_context(memories)
                session_prompt = build_session_prompt(pilot_traits, memory_context)

            # ── Game over check ───────────────────────────────────
            if game_over:
                reason = turn_result.get("gameOverReason", "The expedition ends.")
                await self.capability_worker.speak(
                    f"{reason} Final position: {pos_x}, {pos_y}. "
                    f"{sand_dollars} Sand Dollars earned. "
                    f"{len(inventory)} items found. "
                    f"The Moonstone Maverick descends. Until the grid calls again."
                )
                set_offline(device_id)
                return

            # ── Ask for next direction ────────────────────────────
            await self.capability_worker.speak(
                "North, south, east, or west. Where does the Maverick go next?"
            )

        # ── Session end (max turns or battery depleted) ───────────
        if battery <= 0:
            await self.capability_worker.speak(
                f"Battery depleted at coordinates {pos_x}, {pos_y}. "
                f"The Moonstone Maverick goes dark. {sand_dollars} Sand Dollars earned. "
                f"The grid remembers you, pilot."
            )
        else:
            items = ", ".join(i.get("name", "?") for i in inventory) if inventory else "nothing"
            await self.capability_worker.speak(
                f"Twenty turns complete. Final position: {pos_x}, {pos_y}. "
                f"Battery at {battery} percent. {sand_dollars} Sand Dollars. "
                f"Items found: {items}. "
                f"The Moonstone Maverick descends. Another day survived in The Fading."
            )

        set_offline(device_id)
