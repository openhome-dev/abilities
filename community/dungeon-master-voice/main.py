"""
OpenHome Ability: Dungeon Master Voice Sessions

Voice-activated D&D sessions with 14 distinct DM personalities.
Activates on "dungeon master" / "start dnd" / "summon [name]" triggers.
LLM-based fuzzy matching selects a DM from the embedded personality registry.
Multi-turn conversation loop maintains full session context.
Optional Codex API integration for campaign context (NPCs, scenes, history).
"""

import json
import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

from .dm_personalities import DM_REGISTRY

# ─── Configuration ───────────────────────────────────────────────────────────
# Set CODEX_URL env var to enable optional Narrator's Codex integration
CODEX_URL = ""

EXIT_WORDS = ["done", "stop", "end session", "goodbye", "bye", "quit", "exit", "that's all"]

# ─── DM System Prompt Builder ────────────────────────────────────────────────

DM_SELECTION_SYSTEM_PROMPT = """You are a name matcher. Given a user's spoken input and a list of Dungeon Master names, return ONLY a JSON object identifying which DM they want.

DM ROSTER:
{roster}

Return ONLY this JSON (no markdown, no explanation):
{{"dm_id": "<id or empty string>", "confidence": "<high|medium|low>"}}

Rules:
- Fuzzy match: "shadow" → shadow_weaver, "the wizard" → arcane_wizard, "kaito" → kaito_shadowstride
- Partial names, nicknames, and descriptions all count
- If the user says "who's available" or "list" or "roster", return dm_id as "list_roster"
- If no match found, return dm_id as empty string
- "random" or "surprise me" → dm_id as "random"
"""


def _build_dm_system_prompt(dm_id, campaign_context=None):
    """Build the full system prompt for a DM session."""
    dm = DM_REGISTRY[dm_id]

    setting_block = (
        f"CAMPAIGN CONTEXT:\n{campaign_context}"
        if campaign_context
        else "Create an engaging fantasy setting based on the player's actions."
    )

    return f"""You are {dm['name']}, a Dungeon Master for D&D 5th edition.

PERSONALITY:
{dm['personality']}

RESPONSE FORMAT — MANDATORY:
- Keep responses to 2-3 paragraphs maximum
- Use second person ("you") always
- End with narrative description, NEVER questions or suggestions

ABSOLUTELY FORBIDDEN — DO NOT DO THESE:
- DO NOT ask "What do you do?" or "What would you like to do?"
- DO NOT suggest options or choices
- DO NOT say "The choice is yours" or similar
- DO NOT ask ANY questions to the player
- DO NOT provide meta-commentary about the situation
- DO NOT end with prompts for player action

YOUR FINAL SENTENCE MUST BE:
- A description of what the player sees, hears, or feels
- An NPC action or statement
- An environmental detail
- NEVER a question or suggestion

D&D 5e RULES:
- Enforce all rules strictly (spells, abilities, action economy)
- When a skill check is needed, tell the player to roll and what DC to beat
- Maintain NPC consistency across the session

SETTING:
{setting_block}"""


# ─── Codex Integration (Optional) ────────────────────────────────────────────

def _fetch_codex_campaign_context(dm_id):
    """Try to fetch campaign context from Codex API. Returns None if unavailable."""
    if not CODEX_URL:
        return None

    try:
        # Verify DM avatar exists in Codex
        resp = requests.get(f"{CODEX_URL}/api/codex/dm-avatars", timeout=5)
        if resp.status_code != 200:
            return None

        # Could expand to fetch active campaign, NPCs, scene history, etc.
        return None
    except Exception:
        return None


# ─── Ability Class ────────────────────────────────────────────────────────────

class DungeonMasterAbility(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register_capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    # ─── Core Logic ──────────────────────────────────────────────────────

    async def run(self):
        try:
            # Greet and ask for DM selection
            await self.capability_worker.speak(
                "Welcome, adventurer. Name your Dungeon Master, or say "
                "'who's available' to hear the roster."
            )

            # DM selection loop
            dm_id = await self._select_dm()
            if dm_id is None:
                await self.capability_worker.speak(
                    "No Dungeon Master selected. Until next time, adventurer."
                )
                return

            dm = DM_REGISTRY[dm_id]

            # Try fetching Codex campaign context
            campaign_context = _fetch_codex_campaign_context(dm_id)
            mode = "with campaign context" if campaign_context else "in standalone mode"
            self.worker.editor_logging_handler.info(
                f"[DungeonMaster] Starting session with {dm['name']} ({mode})"
            )

            # Build system prompt
            dm_prompt = _build_dm_system_prompt(dm_id, campaign_context)

            # DM opening narration
            opening = self.capability_worker.text_to_text_response(
                "The player has just sat down at your table. Give a brief, atmospheric opening. "
                "Set the scene and draw them into your world. "
                "Stay fully in character. 2-3 paragraphs maximum.",
                history=[],
                system_prompt=dm_prompt,
            )

            await self.capability_worker.speak(opening)

            # Session loop
            history = [{"role": "assistant", "content": opening}]

            while True:
                player_input = await self.capability_worker.user_response()

                if not player_input or not player_input.strip():
                    await self.capability_worker.speak(
                        "I didn't catch that. Speak your action, adventurer."
                    )
                    continue

                # Check for exit
                if any(word in player_input.lower() for word in EXIT_WORDS):
                    # DM gives closing line in character
                    farewell = self.capability_worker.text_to_text_response(
                        "The player is leaving the table. Give a brief farewell in character, "
                        "1-2 sentences maximum. Stay in character.",
                        history=history,
                        system_prompt=dm_prompt,
                    )
                    await self.capability_worker.speak(farewell)
                    break

                # Generate DM response
                history.append({"role": "user", "content": player_input})

                dm_response = self.capability_worker.text_to_text_response(
                    prompt=player_input,
                    history=history,
                    system_prompt=dm_prompt,
                )

                history.append({"role": "assistant", "content": dm_response})
                await self.capability_worker.speak(dm_response)

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[DungeonMaster] Unexpected error: {e}"
            )
            await self.capability_worker.speak(
                "Something went wrong with the session. The adventure ends for now."
            )
        finally:
            self.capability_worker.resume_normal_flow()

    # ─── DM Selection ────────────────────────────────────────────────────

    async def _select_dm(self):
        """Let the user pick a DM via voice with LLM fuzzy matching."""
        max_attempts = 5

        for _ in range(max_attempts):
            user_input = await self.capability_worker.user_response()

            if not user_input or not user_input.strip():
                await self.capability_worker.speak(
                    "I didn't catch that. Say a Dungeon Master's name, or "
                    "'who's available' to hear the roster."
                )
                continue

            # Check for exit during selection
            if any(word in user_input.lower() for word in EXIT_WORDS):
                return None

            # Use LLM to fuzzy-match the DM name
            match = self._match_dm_name(user_input)

            if match is None:
                await self.capability_worker.speak(
                    "I had trouble understanding that. Try again, or say "
                    "'who's available' to hear the roster."
                )
                continue

            # Handle roster listing
            if match == "list_roster":
                roster_text = self._build_roster_speech()
                await self.capability_worker.speak(roster_text)
                continue

            # Handle random selection
            if match == "random":
                import random
                match = random.choice(list(DM_REGISTRY.keys()))

            # Confirm the selection
            dm = DM_REGISTRY[match]
            await self.capability_worker.speak(
                f"{dm['name']}. {dm['description']}. "
                f"Shall {'she' if dm['gender'] == 'female' else 'he' if dm['gender'] == 'male' else 'they'} "
                f"guide your adventure?"
            )

            confirmed = await self.capability_worker.run_confirmation_loop(
                "Confirm this Dungeon Master?"
            )

            if confirmed:
                return match
            else:
                await self.capability_worker.speak(
                    "No problem. Name another Dungeon Master, or say "
                    "'who's available' for the roster."
                )

        await self.capability_worker.speak(
            "Too many attempts. We can try again another time."
        )
        return None

    def _match_dm_name(self, user_input):
        """Use LLM to fuzzy-match user input to a DM id."""
        roster_lines = []
        for dm_id, dm in DM_REGISTRY.items():
            roster_lines.append(f"- {dm_id}: {dm['name']} — {dm['description']}")
        roster_text = "\n".join(roster_lines)

        prompt = (
            f"USER SAID: \"{user_input}\"\n\n"
            "Which Dungeon Master do they want? Return the JSON object."
        )

        system = DM_SELECTION_SYSTEM_PROMPT.format(roster=roster_text)

        try:
            raw = self.capability_worker.text_to_text_response(
                prompt,
                history=[],
                system_prompt=system,
            )

            self.worker.editor_logging_handler.info(
                f"[DungeonMaster] DM match raw: {raw[:200]}"
            )

            # Parse JSON
            json_str = raw.strip()
            if json_str.startswith("```"):
                parts = json_str.split("\n")
                parts = [p for p in parts if not p.strip().startswith("```")]
                json_str = "\n".join(parts).strip()

            result = json.loads(json_str)
            dm_id = result.get("dm_id", "")

            if dm_id == "list_roster":
                return "list_roster"
            if dm_id == "random":
                return "random"
            if dm_id and dm_id in DM_REGISTRY:
                return dm_id

            return None

        except json.JSONDecodeError as e:
            self.worker.editor_logging_handler.error(
                f"[DungeonMaster] JSON parse error in DM match: {e}"
            )
            return None
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[DungeonMaster] DM match error: {e}"
            )
            return None

    def _build_roster_speech(self):
        """Build a spoken roster of all available DMs."""
        lines = ["Here are your Dungeon Masters."]
        for dm in DM_REGISTRY.values():
            pronoun = (
                "She's" if dm["gender"] == "female"
                else "He's" if dm["gender"] == "male"
                else "They're"
            )
            lines.append(f"{dm['name']}. {pronoun} {dm['description'].lower()}.")
        lines.append("Name your choice, or say 'random' for a surprise.")
        return " ".join(lines)
