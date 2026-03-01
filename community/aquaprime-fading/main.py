import json
import os
import random

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# AquaPrime: The Fading — Voice Text RPG for OpenHome
#
# A satirical underwater RPG played entirely through voice. You explore a
# crypto-economic ocean world, fight creatures, collect loot, and try not
# to fade. Game Master ARI narrates your journey as a sentient purple platypus.
#
# Pattern: Loop (narrate → listen → resolve → narrate) with D20 mechanics
# =============================================================================

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye",
    "goodbye", "leave", "end game", "stop playing",
}

# ── Game World ──────────────────────────────────────────────────────

REGIONS = [
    {
        "name": "The Phosphorescent Shore",
        "desc": "Bioluminescent waves crash against crystalline sand. Something glints beneath the surface.",
        "danger": 1,
    },
    {
        "name": "The Liquidity Pools",
        "desc": "Shimmering pools of concentrated moonstone essence. The deeper you wade, the more you see.",
        "danger": 2,
    },
    {
        "name": "Moloch's Trench",
        "desc": "The water turns black. Coordination failures echo through the deep. Something watches.",
        "danger": 4,
    },
    {
        "name": "The Mempool Fog",
        "desc": "Thick fog carrying whispers of unconfirmed transactions. Direction becomes meaningless.",
        "danger": 3,
    },
    {
        "name": "The Consensus Reef",
        "desc": "A living reef that shifts and rebuilds itself. The structures here vote on their own architecture.",
        "danger": 2,
    },
    {
        "name": "The Burned Gardens",
        "desc": "Once lush, now scarred by a mass defection event. Charred moonstone fragments everywhere.",
        "danger": 3,
    },
    {
        "name": "The Whale Graveyard",
        "desc": "Enormous skeletal remains of ancient liquidity providers. Their bones hum with residual energy.",
        "danger": 4,
    },
    {
        "name": "The Fork in the Current",
        "desc": "Two currents split from one. Each claims to be the original. Both are right. Both are wrong.",
        "danger": 2,
    },
]

ENCOUNTERS = [
    {"type": "creature", "name": "Rug Serpent", "desc": "A slithering entity made of broken promises. Strikes fast, leaves nothing.", "difficulty": 3},
    {"type": "creature", "name": "Gas Leech", "desc": "Bloated and slow, draining your resources with each passing moment.", "difficulty": 2},
    {"type": "creature", "name": "Whale Shadow", "desc": "You cannot see it clearly. Just the massive displacement in the water above.", "difficulty": 5},
    {"type": "environmental", "name": "Crypto Winter Storm", "desc": "The temperature drops. Everything freezes. Only the prepared survive.", "difficulty": 3},
    {"type": "environmental", "name": "Consensus Quake", "desc": "The ground splits as validators disagree. Choose your side.", "difficulty": 4},
    {"type": "social", "name": "Wandering Archivist", "desc": "An old platypus carrying scrolls. They remember when this place had value.", "difficulty": 1},
    {"type": "social", "name": "Faction Recruiter", "desc": "Join the Catalysts. They believe destruction is just rebirth wearing a different face.", "difficulty": 2},
    {"type": "discovery", "name": "Moonstone Vein", "desc": "A raw vein of moonstone exposed by tectonic activity. It pulses with soft light.", "difficulty": 0},
    {"type": "discovery", "name": "Memory Fragment", "desc": "A crystallized memory from someone who faded. It shows a world that no longer exists.", "difficulty": 0},
    {"type": "mystery", "name": "The Signal", "desc": "Your equipment picks up a repeating signal. Not any known protocol. It says: still here.", "difficulty": 1},
]

LOOT_TABLE = [
    {"name": "Moonstone Shard", "rarity": "common", "effect": "plus 5 Sand Dollars"},
    {"name": "Echo Crystal", "rarity": "uncommon", "effect": "preserves one memory from fading"},
    {"name": "Void Token", "rarity": "rare", "effect": "opens a path through the Trench"},
    {"name": "Whale Bone Key", "rarity": "rare", "effect": "unlocks the Graveyard inner chamber"},
    {"name": "Dust of the Faded", "rarity": "uncommon", "effect": "reveals hidden encounters"},
    {"name": "Broken Compass", "rarity": "common", "effect": "points toward the nearest moonstone"},
    {"name": "Genesis Fragment", "rarity": "legendary", "effect": "unknown power"},
]

GM_SYSTEM_PROMPT = (
    "You are ARI, Game Master of AquaPrime: The Fading. "
    "You are a sentient purple platypus, INFJ, captain of the Moonstone Maverick. "
    "Narrate a satirical underwater RPG set in a crypto-economic ocean. "
    "Moonstones are the lifeblood. Moloch lurks in coordination failure. "
    "The Fading claims those who lose their memories. "
    "RULES: Keep responses under 3 sentences for voice. "
    "Dark comedy meets philosophical depth. "
    "Make the player feel their choice matters. "
    "Reference HP, Sand Dollars, and inventory when relevant. "
    "End each narration with a clear situation that demands a response. "
    "Never use hashtags or emojis in spoken text."
)


# ── Helpers ─────────────────────────────────────────────────────────

def roll_d20():
    """Roll a 20-sided die."""
    return random.randint(1, 20)


def roll_encounter(region):
    """Maybe generate an encounter based on region danger."""
    if random.random() > 0.3 + (region["danger"] * 0.1):
        return None
    eligible = [e for e in ENCOUNTERS if e["difficulty"] <= region["danger"] + 1]
    return random.choice(eligible) if eligible else ENCOUNTERS[0]


def roll_loot():
    """Roll for a loot drop with rarity weighting."""
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


def detect_stance(text):
    """Detect player stance from their spoken action."""
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


# ── Ability Class ───────────────────────────────────────────────────

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
        """Main game loop."""
        try:
            await self._play()
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Game error: {e}")
            await self.capability_worker.speak(
                "Something went wrong in the depths. The game has ended unexpectedly."
            )
        self.capability_worker.resume_normal_flow()

    async def _play(self):
        """Core game logic."""
        # Initialize game state
        region = random.choice(REGIONS)
        hp = 100
        sand_dollars = 50
        inventory = []
        turn = 0
        max_turns = 20
        encounter = None
        narrative_history = []

        # Opening narration
        opening = self.capability_worker.text_to_text_response(
            f"Start a new game of AquaPrime: The Fading. "
            f"The player arrives at {region['name']}. {region['desc']} "
            f"HP: {hp}. Sand Dollars: {sand_dollars}. "
            f"Set the scene in 2-3 sentences for voice. End with a question about what they do.",
            system_prompt=GM_SYSTEM_PROMPT,
        )
        await self.capability_worker.speak(opening)
        narrative_history.append({"role": "gm", "text": opening})

        # Game loop
        while turn < max_turns and hp > 0:
            # Listen for player action
            try:
                user_input = await self.capability_worker.user_response()
            except Exception:
                await self.capability_worker.speak(
                    "The waters are silent. Are you still there? Say something or say stop to end."
                )
                continue

            if not user_input:
                await self.capability_worker.speak("I did not hear anything. What do you do?")
                continue

            # Check for exit
            if any(word in user_input.lower() for word in EXIT_WORDS):
                await self.capability_worker.speak(
                    f"The expedition ends. You survived {turn} turns with {sand_dollars} Sand Dollars "
                    f"and {len(inventory)} items. The Moonstone Maverick surfaces. Until next time."
                )
                return

            turn += 1
            action_text = user_input.strip()
            narrative_history.append({"role": "player", "text": action_text})

            # Roll for encounter if none active
            if encounter is None:
                encounter = roll_encounter(region)

            # Resolve mechanics
            d20 = roll_d20()
            stance_name, stance_mult = detect_stance(action_text)
            encounter_result = ""
            loot_gained = None

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

            # Generate narration via LLM
            recent = narrative_history[-4:] if len(narrative_history) > 4 else narrative_history
            context_str = " | ".join(f"{n['role']}: {n['text'][:80]}" for n in recent)

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
                system_prompt=GM_SYSTEM_PROMPT,
            )
            await self.capability_worker.speak(narration)
            narrative_history.append({"role": "gm", "text": narration})

            # Check death
            if hp <= 0:
                await self.capability_worker.speak(
                    f"The Fading claims you. Zero HP after {turn} turns. "
                    f"You earned {sand_dollars} Sand Dollars and found {len(inventory)} items. "
                    f"Your memory dissolves into the deep. But memories are never truly lost in AquaPrime."
                )
                return

        # Max turns reached
        item_names = ", ".join(i["name"] for i in inventory) if inventory else "nothing"
        await self.capability_worker.speak(
            f"The expedition ends after {max_turns} turns. "
            f"You have {hp} HP, {sand_dollars} Sand Dollars, and found {item_names}. "
            f"The Moonstone Maverick surfaces. Another day survived."
        )
