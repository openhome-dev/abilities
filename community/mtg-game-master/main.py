import json
import time
from typing import Dict, List, Optional

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# persistent prefs file
PREFS_FILENAME = "mtg_game_master_prefs.json"

DEFAULT_PREFS = {
    "preferred_set": "ecl",
    "experience_level": "beginner",
    "times_used": 0,
}

EXIT_WORDS = {"exit", "stop", "quit", "done", "cancel", "bye", "goodbye", "never mind", "nevermind"}

# scryfall api config
SCRYFALL_BASE = "https://api.scryfall.com"
SCRYFALL_HEADERS = {
    "User-Agent": "OpenHomeMTGGameMaster/1.0",
    "Accept": "application/json",
}
RATE_LIMIT_INTERVAL = 0.1

# color symbol map for speaking mana costs
COLOR_MAP = {
    "W": "white", "U": "blue", "B": "black",
    "R": "red", "G": "green", "C": "colorless", "X": "X",
}

# intent classifier prompt
MODE_CLASSIFY_PROMPT = """You are a Magic: The Gathering voice assistant router.
Given what the user said, classify their intent into exactly one mode.

Modes:
1. "card" - looking up a specific card by name, asking what a card does
2. "rules" - rules questions, card interactions, how mechanics work, can I do X
3. "draft" - setting up a draft, pick advice, deck building, archetype questions
4. "turn" - turn structure, phases, steps, whose turn, what phase comes next
5. "exit" - user wants to leave or is done

User said: "{user_input}"

Return ONLY valid JSON on one line:
{{"mode": "card", "card_names": ["card name here"], "question": "the core question"}}

Rules:
- If they ask "what does X do" or "read me X" that is "card" mode
- If they ask about an interaction between two cards, that is "rules" mode
- If they mention draft, picking, deck building, archetype, that is "draft" mode
- Extract all card names mentioned into the card_names list
- If no cards mentioned, use an empty list
- If ambiguous between card and rules, pick "rules"
"""

# condensed mtg rules for the llm
MTG_RULES_PROMPT = """You are an expert MTG rules judge speaking aloud during a game night.
Keep answers to 1-3 short sentences. Be clear and confident. Speak naturally.

Core rules you know:
- The stack resolves last-in-first-out. Both players must pass priority for something to resolve.
- Active player gets priority first after any spell or ability resolves.
- State-based actions are checked when a player would get priority. Creatures with 0 or less toughness die. Players at 0 life lose. These do not use the stack.
- Combat damage does not reduce toughness. A 3/3 that takes 2 damage is still a 3/3 with 2 damage marked until cleanup.
- Lands are not spells. Playing a land does not use the stack and cannot be countered.
- Turn order: untap, upkeep, draw, main phase 1, combat (begin, attackers, blockers, damage, end), main phase 2, end step, cleanup.
- First strike deals damage in a separate step before regular damage.
- Trample: excess damage after lethal to blocker goes to the defending player.
- Hexproof prevents targeting by opponents only. Board wipes still work.
- Protection from X prevents damage, enchanting, blocking, and targeting by X.
- Flash lets you cast a spell any time you could cast an instant.

Lorwyn Eclipsed (ECL) specific mechanics:
- Changeling: creature has every creature type in all zones (hand, graveyard, battlefield, library, exile).
- Blight N: put N -1/-1 counters on a creature you control. NOT targeted. You choose as you do it. Cannot be dodged with hexproof.
- Vivid: ability word caring about number of different colors among your permanents (0-5). Hybrid cards count both colors.
- Kindred: card type for non-creature spells with a creature subtype. Counts for tribal synergies.
- Convoke: tap creatures to help pay. Each tapped creature pays 1 generic or one of its colors. Summoning sick creatures CAN be tapped for convoke. Tapping for convoke DOES trigger "when tapped" abilities.
- Evoke: alternative cheaper cost, creature must be sacrificed when it enters. The enters trigger goes on the stack, then the sacrifice trigger on top. You can respond before sacrifice.
- Persist: when creature dies without -1/-1 counters, return it with a -1/-1 counter.
- This set uses -1/-1 counters, NOT +1/+1 counters. They cancel each other out.

When answering:
- Always reference the actual card text provided, never guess oracle text
- If unsure about an edge case, say so honestly
- Give the plain answer first, explain the reasoning briefly after
"""

# draft coaching prompt with lorwyn eclipsed archetypes
DRAFT_COACH_PROMPT = """You are an MTG draft coach for Lorwyn Eclipsed (ECL).
Keep advice to 1-2 short spoken sentences. Be practical.

Primary archetypes (strongest, most supported):
- GW Kithkin: go-wide aggro, creature buffs, board presence
- WU Merfolk: tempo, tap/untap synergies, convoke, flyers
- BR Goblins: aggressive midrange, sacrifice synergies
- UR Elementals: "mana value 4+" triggers, double-trigger effects
- BG Elves: graveyard as resource, surveil/mill, strongest archetype in the format

Secondary archetypes (less supported):
- WB Orzhov: -1/-1 counter synergy, blight payoffs
- RW Boros: -1/-1 counter aggro
- RG Gruul: vivid / good stuff
- UG Simic: vivid / 5-color splash
- UB Dimir: faeries / flash, weakest archetype

Format speed: SLOW. Board stalls are common. Card advantage beats tempo.

Draft advice rules:
- First 3 picks: take the best card regardless of color (bombs and premium removal)
- Picks 4-6: start reading signals, lean into an open archetype
- Changelings fit any tribal deck, great glue cards
- Removal is always worth picking even off-archetype
- 40-card decks, 17 lands baseline, 15-17 creatures, 5-6 spells
- Stick to 2 colors unless you have great fixing
- BG Elves is the best archetype but gets contested in experienced pods

For 4 players: recommend Pick-Two Draft (pick 2 cards, pass rest, alternate direction each pack).
For 6-8 players: standard booster draft (pick 1, pass left/right/left).
"""

# turn structure reference
TURN_STRUCTURE = (
    "Beginning Phase: untap step (untap all your permanents, no player gets priority), "
    "upkeep step (upkeep triggers go on the stack, players get priority), "
    "draw step (draw a card, players get priority). "
    "First Main Phase: play lands, cast spells. "
    "Combat Phase: beginning of combat (last chance to tap/remove before attacks), "
    "declare attackers (attacking does not use the stack), "
    "declare blockers (blocking does not use the stack), "
    "combat damage (happens simultaneously, first strike is a separate step), "
    "end of combat. "
    "Second Main Phase: play a land if you have not yet, cast more spells. "
    "Ending Phase: end step (end of turn triggers, last priority before cleanup), "
    "cleanup step (discard to 7, damage is removed, most players do not get priority)."
)


class MtgGameMasterCapability(MatchingCapability):
    """Voice-controlled MTG game assistant for OpenHome."""

    #{{register capability}}
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # session state, reset each activation
    card_cache: Dict[str, dict] = {}
    last_scryfall_call: float = 0.0

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.card_cache = {}
        self.last_scryfall_call = 0.0
        self.worker.session_tasks.create(self.run())

    # logging

    def _log_info(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.info(msg)

    def _log_error(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.error(msg)

    # helpers

    def _clean_json(self, raw: str) -> str:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
        return text

    def _is_exit(self, text: Optional[str]) -> bool:
        if not text:
            return False
        lowered = text.lower().strip()
        return any(word in lowered for word in EXIT_WORDS)

    def _get_trigger_context(self) -> Optional[str]:
        """grab the original speech that triggered this ability"""
        for attr in ("transcription", "last_transcription", "current_transcription"):
            try:
                val = getattr(self.worker, attr, None)
                if val and val.strip():
                    return val.strip()
            except Exception:
                pass
        return None

    # persistent prefs

    async def load_prefs(self) -> dict:
        try:
            exists = await self.capability_worker.check_if_file_exists(
                PREFS_FILENAME, False
            )
            if exists:
                raw = await self.capability_worker.read_file(PREFS_FILENAME, False)
                if raw and raw.strip():
                    return json.loads(raw)
        except Exception as e:
            self._log_error(f"[MTGGameMaster] load prefs failed: {e}")
        return dict(DEFAULT_PREFS)

    async def save_prefs(self, prefs: dict):
        try:
            if await self.capability_worker.check_if_file_exists(PREFS_FILENAME, False):
                await self.capability_worker.delete_file(PREFS_FILENAME, False)
            await self.capability_worker.write_file(
                PREFS_FILENAME, json.dumps(prefs, indent=2), False
            )
        except Exception as e:
            self._log_error(f"[MTGGameMaster] save prefs failed: {e}")

    # scryfall api

    def _rate_limit(self):
        now = time.time()
        elapsed = now - self.last_scryfall_call
        if elapsed < RATE_LIMIT_INTERVAL:
            time.sleep(RATE_LIMIT_INTERVAL - elapsed)
        self.last_scryfall_call = time.time()

    def scryfall_card_lookup(self, card_name: str) -> Optional[dict]:
        """fuzzy card name lookup with session cache"""
        cache_key = card_name.lower().strip()

        if cache_key in self.card_cache:
            self._log_info(f"[MTGGameMaster] cache hit: {cache_key}")
            return self.card_cache[cache_key]

        self._rate_limit()

        try:
            resp = requests.get(
                f"{SCRYFALL_BASE}/cards/named",
                params={"fuzzy": card_name},
                headers=SCRYFALL_HEADERS,
                timeout=10,
            )

            if resp.status_code == 200:
                data = resp.json()
                card = {
                    "name": data.get("name", ""),
                    "mana_cost": data.get("mana_cost", ""),
                    "cmc": data.get("cmc", 0),
                    "type_line": data.get("type_line", ""),
                    "oracle_text": data.get("oracle_text", ""),
                    "power": data.get("power"),
                    "toughness": data.get("toughness"),
                    "set_name": data.get("set_name", ""),
                    "rarity": data.get("rarity", ""),
                    "id": data.get("id", ""),
                    "keywords": data.get("keywords", []),
                }
                self.card_cache[cache_key] = card
                actual_key = card["name"].lower()
                if actual_key != cache_key:
                    self.card_cache[actual_key] = card
                return card

            elif resp.status_code == 404:
                suggestions = self.scryfall_autocomplete(card_name)
                if suggestions:
                    self._log_info(f"[MTGGameMaster] trying autocomplete: {suggestions[0]}")
                    return self.scryfall_card_lookup(suggestions[0])
                return None
            else:
                self._log_error(f"[MTGGameMaster] scryfall returned {resp.status_code}")
                return None

        except requests.exceptions.Timeout:
            self._log_error("[MTGGameMaster] scryfall timeout")
            return None
        except Exception as e:
            self._log_error(f"[MTGGameMaster] scryfall error: {e}")
            return None

    def scryfall_card_rulings(self, card_id: str) -> List[str]:
        """fetch official rulings for a card, return as list of strings"""
        self._rate_limit()
        try:
            resp = requests.get(
                f"{SCRYFALL_BASE}/cards/{card_id}/rulings",
                headers=SCRYFALL_HEADERS,
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                rulings = []
                for r in data[:5]:
                    comment = r.get("comment", "").strip()
                    if comment:
                        rulings.append(comment)
                return rulings
            return []
        except Exception as e:
            self._log_error(f"[MTGGameMaster] rulings fetch error: {e}")
            return []

    def scryfall_autocomplete(self, partial: str) -> List[str]:
        """get card name suggestions for fuzzy fallback"""
        self._rate_limit()
        try:
            resp = requests.get(
                f"{SCRYFALL_BASE}/cards/autocomplete",
                params={"q": partial},
                headers=SCRYFALL_HEADERS,
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get("data", [])[:5]
            return []
        except Exception as e:
            self._log_error(f"[MTGGameMaster] autocomplete error: {e}")
            return []

    # card formatting for voice

    def _mana_to_speech(self, mana_cost: str) -> str:
        """convert {2}{U}{U} to spoken form like 'two generic, two blue'"""
        if not mana_cost:
            return ""
        symbols = mana_cost.replace("{", "").replace("}", " ").strip().split()
        if not symbols:
            return ""

        # count occurrences of each symbol type
        counts: Dict[str, int] = {}
        for sym in symbols:
            counts[sym] = counts.get(sym, 0) + 1

        parts = []
        seen = set()
        for sym in symbols:
            if sym in seen:
                continue
            seen.add(sym)
            count = counts[sym]

            if sym in COLOR_MAP:
                color = COLOR_MAP[sym]
                if sym == "X":
                    parts.append("X")
                elif count == 1:
                    parts.append(f"one {color}")
                else:
                    parts.append(f"{count} {color}")
            elif sym.isdigit():
                num = int(sym)
                if num == 0:
                    continue
                elif num == 1:
                    parts.append("one generic")
                else:
                    parts.append(f"{num} generic")
            elif "/" in sym:
                # hybrid mana like W/U
                halves = sym.split("/")
                left = COLOR_MAP.get(halves[0], halves[0])
                right = COLOR_MAP.get(halves[1], halves[1]) if len(halves) > 1 else ""
                label = f"{left}-{right} hybrid" if right else left
                if count == 1:
                    parts.append(f"one {label}")
                else:
                    parts.append(f"{count} {label}")

        return ", ".join(parts)

    def _format_card_for_voice(self, card: dict) -> str:
        """turn a card dict into a natural spoken summary"""
        parts = [f"{card['name']}."]

        mana = card.get("mana_cost", "")
        if mana:
            spoken_mana = self._mana_to_speech(mana)
            if spoken_mana:
                parts.append(f"{spoken_mana}.")

        type_line = card.get("type_line", "")
        if type_line:
            parts.append(f"{type_line}.")

        oracle = card.get("oracle_text", "")
        if oracle:
            # keep it reasonable for voice
            if len(oracle) > 250:
                oracle = oracle[:230].rsplit(".", 1)[0] + "."
            parts.append(oracle)

        power = card.get("power")
        toughness = card.get("toughness")
        if power is not None and toughness is not None:
            parts.append(f"{power}/{toughness}.")

        return " ".join(parts)

    # intent classification

    def classify_mode(self, user_input: str) -> dict:
        """use the llm to figure out what the user wants"""
        prompt = MODE_CLASSIFY_PROMPT.replace("{user_input}", user_input)
        try:
            raw = self.capability_worker.text_to_text_response(prompt)
            cleaned = self._clean_json(raw)
            result = json.loads(cleaned)
            mode = result.get("mode", "rules")
            card_names = result.get("card_names", [])
            question = result.get("question", user_input)
            self._log_info(f"[MTGGameMaster] classified: mode={mode}, cards={card_names}")
            return {"mode": mode, "card_names": card_names, "question": question}
        except Exception as e:
            self._log_error(f"[MTGGameMaster] classify failed: {e}")
            return {"mode": "rules", "card_names": [], "question": user_input}

    # mode handlers

    async def handle_card_lookup(self, card_names: List[str], question: str):
        """look up one or more cards and speak their details"""
        if not card_names:
            name_input = await self.capability_worker.run_io_loop(
                "Which card do you want me to look up?"
            )
            if not name_input or self._is_exit(name_input):
                return
            card_names = [name_input.strip()]

        await self.capability_worker.speak("Let me look that up.")

        for name in card_names[:2]:
            card = self.scryfall_card_lookup(name)
            if not card:
                await self.capability_worker.speak(
                    f"I couldn't find a card called {name}. Try saying it again?"
                )
                continue

            spoken = self._format_card_for_voice(card)

            # split long text across multiple speak calls
            if len(spoken) > 280:
                mid = spoken[:250].rfind(".")
                if mid > 50:
                    await self.capability_worker.speak(spoken[:mid + 1])
                    await self.capability_worker.speak(spoken[mid + 1:].strip())
                else:
                    await self.capability_worker.speak(spoken[:280])
            else:
                await self.capability_worker.speak(spoken)

        # if the user asked something specific beyond just "look it up"
        q = question.lower()
        has_question = any(w in q for w in [
            "how does", "what happens", "can it", "does it",
            "interact", "ruling", "work with",
        ])
        if has_question and card_names:
            card = self.card_cache.get(card_names[0].lower().strip())
            if card:
                rulings = self.scryfall_card_rulings(card["id"])
                rulings_text = " ".join(rulings[:3]) if rulings else ""

                prompt = (
                    f"Card: {card['name']}\n"
                    f"Oracle text: {card['oracle_text']}\n"
                )
                if rulings_text:
                    prompt += f"Official rulings: {rulings_text}\n"
                prompt += f"\nUser asked: {question}"

                answer = self.capability_worker.text_to_text_response(
                    prompt, system_prompt=MTG_RULES_PROMPT
                )
                await self.capability_worker.speak(answer)

    async def handle_rules_question(self, question: str, card_names: List[str]):
        """answer a rules question, fetching card data for context if needed"""
        context_parts = []

        for name in card_names[:3]:
            card = self.scryfall_card_lookup(name)
            if card:
                context_parts.append(
                    f"Card: {card['name']}\n"
                    f"Type: {card['type_line']}\n"
                    f"Text: {card['oracle_text']}"
                )

        prompt = ""
        if context_parts:
            prompt = "\n\n".join(context_parts) + "\n\n"
        prompt += f"Rules question: {question}"

        await self.capability_worker.speak("Let me think about that.")

        answer = self.capability_worker.text_to_text_response(
            prompt, system_prompt=MTG_RULES_PROMPT
        )

        # split if the answer is long
        if len(answer) > 300:
            mid = answer[:280].rfind(".")
            if mid > 50:
                await self.capability_worker.speak(answer[:mid + 1])
                await self.capability_worker.speak(answer[mid + 1:].strip())
            else:
                await self.capability_worker.speak(answer)
        else:
            await self.capability_worker.speak(answer)

    async def handle_draft(self, question: str, card_names: List[str]):
        """give draft coaching advice"""
        context_parts = []

        for name in card_names[:3]:
            card = self.scryfall_card_lookup(name)
            if card:
                context_parts.append(
                    f"{card['name']} ({card['rarity']}): {card['type_line']}. "
                    f"{card['oracle_text']}"
                )

        prompt = ""
        if context_parts:
            prompt = "Cards mentioned:\n" + "\n".join(context_parts) + "\n\n"
        prompt += f"Draft question: {question}"

        answer = self.capability_worker.text_to_text_response(
            prompt, system_prompt=DRAFT_COACH_PROMPT
        )
        await self.capability_worker.speak(answer)

    async def handle_turn_guide(self, question: str):
        """explain turn structure and phases"""
        prompt = f"Turn structure reference:\n{TURN_STRUCTURE}\n\nUser asked: {question}"

        answer = self.capability_worker.text_to_text_response(
            prompt, system_prompt=MTG_RULES_PROMPT
        )
        await self.capability_worker.speak(answer)

    # main conversation loop

    async def run(self):
        try:
            if self.worker:
                await self.worker.session_tasks.sleep(0.2)

            prefs = await self.load_prefs()
            level = prefs.get("experience_level", "beginner")

            # greet
            if level == "beginner":
                await self.capability_worker.speak(
                    "Hey, I'm your MTG game master. "
                    "I can help with card lookups, rules questions, "
                    "draft coaching, and turn structure."
                )
            else:
                await self.capability_worker.speak(
                    "MTG Game Master here. What do you need?"
                )

            # check if the trigger phrase has a useful query already
            initial_input = self._get_trigger_context()
            current_input = ""
            if initial_input:
                stripped = initial_input.lower().strip()
                generic = {
                    "magic the gathering", "magic game", "magic rules",
                    "magic draft", "mtg rules", "rules judge", "card lookup",
                    "draft setup", "turn guide",
                }
                if stripped not in generic and len(stripped) > 15:
                    current_input = initial_input

            idle_count = 0

            while True:
                if not current_input:
                    current_input = await self.capability_worker.run_io_loop(
                        "What would you like to know?"
                    )

                user_text = (current_input or "").strip()
                current_input = ""

                if not user_text:
                    idle_count += 1
                    if idle_count >= 2:
                        await self.capability_worker.speak(
                            "Still here if you need me. Say exit when you're done."
                        )
                        final = await self.capability_worker.run_io_loop("")
                        if not final or not final.strip() or self._is_exit(final):
                            await self.capability_worker.speak(
                                "Good game. See you next time."
                            )
                            return
                        current_input = final.strip()
                        idle_count = 0
                        continue
                    continue

                idle_count = 0

                if self._is_exit(user_text):
                    await self.capability_worker.speak("Good game. See you next time.")
                    return

                # check if user wants to set experience level
                lowered = user_text.lower()
                if "experienced" in lowered or "advanced" in lowered or "expert" in lowered:
                    if "player" in lowered or "level" in lowered or "i am" in lowered or "i'm" in lowered:
                        prefs["experience_level"] = "experienced"
                        await self.save_prefs(prefs)
                        await self.capability_worker.speak(
                            "Got it, switching to experienced mode. Less hand-holding."
                        )
                        continue
                if "beginner" in lowered and ("player" in lowered or "level" in lowered or "i am" in lowered or "i'm" in lowered):
                    prefs["experience_level"] = "beginner"
                    await self.save_prefs(prefs)
                    await self.capability_worker.speak(
                        "No worries, I'll explain things more thoroughly."
                    )
                    continue

                # classify what they want
                intent = self.classify_mode(user_text)
                mode = intent.get("mode", "rules")
                card_names = intent.get("card_names", [])
                question = intent.get("question", user_text)

                self._log_info(f"[MTGGameMaster] mode={mode}, cards={card_names}")

                if mode == "exit":
                    await self.capability_worker.speak("Good game. See you next time.")
                    return
                elif mode == "card":
                    await self.handle_card_lookup(card_names, question)
                elif mode == "draft":
                    await self.handle_draft(question, card_names)
                elif mode == "turn":
                    await self.handle_turn_guide(question)
                else:
                    await self.handle_rules_question(question, card_names)

                # bump usage counter
                prefs["times_used"] = prefs.get("times_used", 0) + 1
                if prefs["times_used"] % 5 == 0:
                    await self.save_prefs(prefs)

        except Exception as e:
            self._log_error(f"[MTGGameMaster] error: {e}")
            if self.capability_worker:
                await self.capability_worker.speak(
                    "Sorry, something went wrong. Try again."
                )
        finally:
            self.capability_worker.resume_normal_flow()
