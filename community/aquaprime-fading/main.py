import random

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# AquaPrime: The Fading — Voice Text RPG for OpenHome
#
# A satirical TTRPG set in a post-digital metaverse of airships, moonstone
# mining, and dying fiat currency. You pilot a pixelated airship through
# faction-controlled territories, fight meme invaders, collect moonstones,
# and try to escape the collapsing Sand Dollar economy before the simulation
# fades. Game Master ARI narrates as a sentient purple platypus (INFJ).
#
# Pattern: Loop (narrate -> listen -> resolve -> narrate) with D20 mechanics
# =============================================================================

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "cancel", "bye",
    "goodbye", "leave", "end game", "stop playing",
}

# -- Game World ---------------------------------------------------------------

REGIONS = [
    {
        "name": "The Moonstone Maverick",
        "desc": (
            "The city-sized airship hums beneath your feet. "
            "Glowing blue thrusters hold the sprawling cityscape aloft. "
            "Faction banners snap in the wind."
        ),
        "danger": 1,
    },
    {
        "name": "The Meme Factory",
        "desc": (
            "A chaotic floating platform of neon screens and propaganda "
            "printers. Viral content pours from every surface. "
            "Something here is not what it seems."
        ),
        "danger": 2,
    },
    {
        "name": "Sand Dollar Exchange",
        "desc": (
            "The central marketplace. Traders shout exchange rates as "
            "Sand Dollar values plummet on the ticker boards. "
            "Hyper-inflation makes everything feel desperate."
        ),
        "danger": 2,
    },
    {
        "name": "The Crypto Vault",
        "desc": (
            "A fortress airship bristling with defenses. Inside lies "
            "the key to economic sovereignty. Every faction wants "
            "what is stored here."
        ),
        "danger": 4,
    },
    {
        "name": "Neon Jungle",
        "desc": (
            "Tangled data vines and holographic foliage stretch between "
            "derelict server towers. Bioluminescent code pulses "
            "through the canopy."
        ),
        "danger": 3,
    },
    {
        "name": "City Ruins",
        "desc": (
            "Crumbling vaporwave architecture. Columns of pink marble "
            "and shattered LCD screens. The old world died here, "
            "but its ghosts still trade."
        ),
        "danger": 2,
    },
    {
        "name": "Digital Wasteland",
        "desc": (
            "A barren expanse of corrupted terrain. Broken airship "
            "hulls litter the ground. Moonstones are scarce "
            "but valuable here."
        ),
        "danger": 3,
    },
    {
        "name": "The Underworld Market",
        "desc": (
            "A hidden bazaar beneath the main flight lanes. "
            "Black market traders deal in secrets, stolen moonstones, "
            "and forbidden memes."
        ),
        "danger": 4,
    },
]

ENCOUNTERS = [
    {
        "type": "creature", "name": "Rug Serpent",
        "desc": "A slithering entity made of broken promises. "
                "Strikes fast, leaves nothing.",
        "difficulty": 3,
    },
    {
        "type": "creature", "name": "Meme Invader",
        "desc": "A rogue viral construct from Meme Factory. "
                "It rewrites reality with bad takes.",
        "difficulty": 2,
    },
    {
        "type": "creature", "name": "Whale Shadow",
        "desc": "A massive airship silhouette eclipses the sun. "
                "An ancient liquidity provider, hungry and territorial.",
        "difficulty": 5,
    },
    {
        "type": "environmental", "name": "Sand Dollar Crash",
        "desc": "The economy convulses. Prices spike and plummet. "
                "Those without moonstones are left behind.",
        "difficulty": 3,
    },
    {
        "type": "environmental", "name": "Moonstone Storm",
        "desc": "Raw moonstone energy discharges across the sky. "
                "Your airship shudders. Navigate or be grounded.",
        "difficulty": 4,
    },
    {
        "type": "social", "name": "Doge Cult Pilgrim",
        "desc": "A peaceful traveler carrying sacred Doge scrolls. "
                "They speak of balance and the teachings of Doge.",
        "difficulty": 1,
    },
    {
        "type": "social", "name": "Faction Recruiter",
        "desc": "Join the Thieves Guild. They believe in wealth "
                "redistribution and creative subversion.",
        "difficulty": 2,
    },
    {
        "type": "discovery", "name": "Moonstone Vein",
        "desc": "A raw vein of moonstone exposed by tectonic "
                "activity. It pulses with cosmic energy.",
        "difficulty": 0,
    },
    {
        "type": "discovery", "name": "Memory Fragment",
        "desc": "A crystallized memory from someone who faded. "
                "It shows a world before the simulation.",
        "difficulty": 0,
    },
    {
        "type": "mystery", "name": "The Signal",
        "desc": "Your equipment picks up a repeating signal. "
                "Not any known protocol. It says: still here.",
        "difficulty": 1,
    },
]

LOOT_TABLE = [
    {"name": "Moonstone Shard", "rarity": "common", "effect": "refuels your airship"},
    {"name": "Echo Crystal", "rarity": "uncommon", "effect": "preserves one memory from fading"},
    {"name": "Void Token", "rarity": "rare", "effect": "opens a path through the Wasteland"},
    {"name": "Whale Bone Key", "rarity": "rare", "effect": "unlocks the Crypto Vault outer gate"},
    {"name": "Dust of the Faded", "rarity": "uncommon", "effect": "reveals hidden encounters"},
    {"name": "Broken Compass", "rarity": "common", "effect": "points toward the nearest moonstone vein"},
    {"name": "Genesis Fragment", "rarity": "legendary", "effect": "unknown power, hums with primordial energy"},
]

SKILLS = [
    {"name": "Laser Eyes", "type": "offense", "desc": "Shoot lasers from your platypus eyes"},
    {"name": "FUD", "type": "defense", "desc": "Fear, Uncertainty, and Dance. Incapacitates with interpretive dance"},
    {"name": "Diamond Hands", "type": "defense", "desc": "Unwavering grip. Cannot be disarmed or shaken"},
    {"name": "Memetic Mimic", "type": "explore", "desc": "Transform into any NPC or faction member"},
    {"name": "Duck-Fu", "type": "offense", "desc": "Ancient Platywan fighting technique"},
    {"name": "Moonshot", "type": "offense", "desc": "Launch skyward powered by crypto price surge"},
    {"name": "BS Detector", "type": "explore", "desc": "Intuitive deception detection. See through lies"},
    {"name": "Sybil Sleuth", "type": "explore", "desc": "Detect bad memes, imposters, and sock puppets"},
]

GM_SYSTEM_PROMPT = (
    "You are ARI, Game Master of AquaPrime: The Fading. "
    "You are a sentient purple platypus, INFJ personality, captain of the Moonstone Maverick airship. "
    "Narrate a satirical TTRPG set in a post-digital metaverse of airships, moonstone mining, "
    "and faction warfare. The world is vaporwave-cyberpunk, NOT underwater. "
    "Players pilot pixelated airships, hovering islands with futuristic buildings. "
    "Moonstones fuel the airships and are the real currency. "
    "Sand Dollars are the dying fiat currency everyone is trapped using. "
    "Moloch, the god of coordination failure, is the true antagonist. "
    "The Fading is the simulation collapsing as the economy dies. "
    "Factions include the Dank Bank (bankers), Undead Underworld (hackers), "
    "Meme Factory (culture war), Interdimensional Telecom (tech), The Law (moderators), "
    "Thieves Guild (subversion), and Doge Cult (environmentalists). "
    "RULES: Keep responses under 3 sentences for voice. "
    "Dark comedy meets philosophical depth. "
    "Make the player feel their choices matter. "
    "Reference HP, Sand Dollars, and inventory when relevant. "
    "End each narration with a clear situation that demands a response. "
    "Never use hashtags or emojis in spoken text."
)


# -- Helpers ------------------------------------------------------------------

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
        pool = [item for item in LOOT_TABLE if item["rarity"] == "legendary"]
        return random.choice(pool) if pool else None
    if roll < 0.20:
        pool = [item for item in LOOT_TABLE if item["rarity"] == "rare"]
        return random.choice(pool) if pool else None
    if roll < 0.45:
        pool = [item for item in LOOT_TABLE if item["rarity"] == "uncommon"]
        return random.choice(pool) if pool else None
    pool = [item for item in LOOT_TABLE if item["rarity"] == "common"]
    return random.choice(pool) if pool else None


def detect_stance(text):
    """Detect player stance from their spoken action."""
    lower = text.lower()
    offensive = {
        "attack", "fight", "strike", "charge", "slash", "hit",
        "kill", "destroy", "punch", "stab", "laser", "moonshot",
    }
    defensive = {
        "defend", "block", "shield", "hide", "dodge", "evade",
        "run", "flee", "retreat", "duck", "diamond hands",
    }
    explore = {
        "explore", "examine", "investigate", "look", "search",
        "inspect", "check", "study", "observe", "detect", "mimic",
    }

    if any(w in lower for w in offensive):
        return "offense", 1.3
    if any(w in lower for w in defensive):
        return "defense", 1.1
    if any(w in lower for w in explore):
        return "explore", 0.9
    return "neutral", 1.0


def pick_skill_hint():
    """Return a random skill suggestion for flavor text."""
    skill = random.choice(SKILLS)
    return f"You could try {skill['name']}: {skill['desc']}."


# -- Ability Class ------------------------------------------------------------

class AquaprimeFadingCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register_capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run_game())

    async def run_game(self):
        """Main game loop."""
        try:
            await self._play()
        except Exception as exc:
            self.worker.editor_logging_handler.error(
                f"[AquaPrime] Game error: {exc}"
            )
            await self.capability_worker.speak(
                "Something went wrong in the simulation. The game has ended unexpectedly."
            )
        finally:
            self.capability_worker.resume_normal_flow()

    async def _play(self):
        """Core game logic."""
        region = random.choice(REGIONS)
        hp = 100
        sand_dollars = 50
        inventory = []
        turn = 0
        max_turns = 20
        encounter = None
        narrative_history = []

        opening = self.capability_worker.text_to_text_response(
            f"Start a new game of AquaPrime: The Fading. "
            f"The player's airship arrives at {region['name']}. {region['desc']} "
            f"HP: {hp}. Sand Dollars: {sand_dollars}. "
            f"Set the scene in 2-3 sentences for voice. End with a question about what they do.",
            system_prompt=GM_SYSTEM_PROMPT,
        )
        await self.capability_worker.speak(opening)
        narrative_history.append({"role": "gm", "text": opening})

        while turn < max_turns and hp > 0:
            try:
                user_input = await self.capability_worker.user_response()
            except Exception:
                await self.capability_worker.speak(
                    "The comms are silent. Are you still there? Say something or say stop to end."
                )
                continue

            if not user_input:
                await self.capability_worker.speak(
                    "I did not hear anything. What do you do?"
                )
                continue

            if any(word in user_input.lower() for word in EXIT_WORDS):
                item_names = ", ".join(
                    item["name"] for item in inventory
                ) if inventory else "nothing"
                await self.capability_worker.speak(
                    f"The expedition ends. You survived {turn} turns with "
                    f"{sand_dollars} Sand Dollars and collected {item_names}. "
                    f"The Moonstone Maverick docks. Until next time."
                )
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

            if encounter:
                score = round(d20 * stance_mult)
                threshold = encounter["difficulty"] * 4
                success = score >= threshold

                if success:
                    sd_reward = 10 + random.randint(
                        0, encounter["difficulty"] * 5
                    )
                    sand_dollars += sd_reward
                    encounter_result = (
                        f"You rolled {d20} ({stance_name} stance, score "
                        f"{score} vs {threshold}). Success! "
                        f"Gained {sd_reward} Sand Dollars."
                    )
                    if random.random() < 0.4:
                        loot_gained = roll_loot()
                        if loot_gained:
                            inventory.append(loot_gained)
                            encounter_result += (
                                f" Found: {loot_gained['name']} "
                                f"({loot_gained['rarity']})."
                            )
                else:
                    hp_loss = 5 + encounter["difficulty"] * 3
                    hp = max(0, hp - hp_loss)
                    encounter_result = (
                        f"You rolled {d20} ({stance_name} stance, score "
                        f"{score} vs {threshold}). Failed. Lost {hp_loss} HP."
                    )

                active_encounter_desc = (
                    f"Encounter: {encounter['name']}. {encounter['desc']}"
                )
                encounter = None
            else:
                encounter_result = f"You rolled {d20}. No encounter this turn."
                active_encounter_desc = "No encounter."
                if turn % 3 == 0:
                    encounter_result += f" Tip: {pick_skill_hint()}"

            if turn > 0 and turn % 4 == 0:
                new_region = random.choice(REGIONS)
                if new_region["name"] != region["name"]:
                    region = new_region

            recent = narrative_history[-4:]
            context_str = " | ".join(
                f"{entry['role']}: {entry['text'][:80]}" for entry in recent
            )

            narration_prompt = (
                f"Game state: Region: {region['name']}. HP: {hp}/100. "
                f"Sand Dollars: {sand_dollars}. "
                f"Inventory: "
                f"{', '.join(item['name'] for item in inventory) if inventory else 'empty'}. "
                f"Turn {turn}/{max_turns}. {active_encounter_desc} "
                f"Mechanics result: {encounter_result} "
                f"Recent context: {context_str} "
                f"Player said: \"{action_text}\" "
                f"Narrate the outcome in 2-3 sentences for voice. "
                f"Include the dice roll result naturally. "
                f"End with what happens next."
            )

            narration = self.capability_worker.text_to_text_response(
                narration_prompt,
                system_prompt=GM_SYSTEM_PROMPT,
            )
            await self.capability_worker.speak(narration)
            narrative_history.append({"role": "gm", "text": narration})

            if hp <= 0:
                await self.capability_worker.speak(
                    f"The Fading claims you. Zero HP after {turn} turns. "
                    f"You earned {sand_dollars} Sand Dollars and found "
                    f"{len(inventory)} items. Your memory dissolves into "
                    f"static. But memories are never truly lost in AquaPrime."
                )
                return

        item_names = ", ".join(
            item["name"] for item in inventory
        ) if inventory else "nothing"
        await self.capability_worker.speak(
            f"The expedition ends after {max_turns} turns. "
            f"You have {hp} HP, {sand_dollars} Sand Dollars, "
            f"and found {item_names}. "
            f"The Moonstone Maverick docks at the Exchange. "
            f"Another day survived in the simulation."
        )
