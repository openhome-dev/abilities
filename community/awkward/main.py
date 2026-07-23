# =============================================================================
# AWKWARD — The Social Flight Simulator (OpenHome Ability)
#
# SDK PRE-FLIGHT CHECKLIST — verify each of these against the real SDK
# reference inside the Live Editor before running a live test. Every method
# this file calls is listed here once. Ctrl-F each name in the SDK docs panel.
#
# text_to_text_response's signature and the CapabilityWorker(...) constructor
# arg were corrected against real production Abilities on GitHub
# (openhome-dev/abilities: templates/basic-template, templates/loop-template,
# community/debate-partner) — the original spec's (prompt, history, system)
# 3-arg form and CapabilityWorker(self) do not match any real usage found.
# OpenHome provides the LLM behind text_to_text_response itself — no API key
# or OpenRouter setup is needed for it (confirmed: no key/env/get_api_keys
# call appears anywhere near text_to_text_response in real abilities).
#
#   self.capability_worker.speak(text)                                [await]
#   self.capability_worker.text_to_speech(text, voice_id)             [await]
#   self.capability_worker.user_response()                            [await]
#   self.capability_worker.run_io_loop(text)                          [await]
#   self.capability_worker.text_to_text_response(prompt, system_prompt=system) [SYNC — never await]
#   self.capability_worker.resume_normal_flow()                       [sync, called exactly once]
#   self.worker.session_tasks.create(coro)                            [sync]
#   self.worker.editor_logging_handler.info(msg)                      [sync]
#
#   Uplift Urdu voice layer for Auntie (speak_auntie / _call_uplift_api),
#   gated by USE_UPLIFT_AUNTIE below — verify these two before a live test:
#   self.capability_worker.get_api_keys("UPLIFT_VOICE_API")      [sync? verify]
#   self.capability_worker.play_audio(audio_bytes)                [await? verify]
#   Endpoint/body verified live against docs.upliftai.org (fetched, not
#   memory): POST https://api.upliftai.org/v1/synthesis/text-to-speech,
#   body {voiceId, text, outputFormat}, Bearer auth. Requires the dashboard
#   step: declare an API key named exactly "UPLIFT_VOICE_API" under Ability
#   Behavior -> API Keys, then set its value under Settings -> API Keys —
#   the code alone does nothing without that.
#
#   run_confirmation_loop(text) -> bool is in the SDK cheat sheet but is
#   unused by this Ability; listed here only so it isn't mistaken for a gap.
# =============================================================================

import json
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# DEMO KILL SWITCH — Uplift Urdu voice for Auntie only.
# Flip USE_UPLIFT_AUNTIE to False at any time (e.g. mid-hackathon if Uplift is
# flaky or the free-tier budget runs out) to fall straight back to Auntie's
# ElevenLabs voice with zero other code changes.
# =============================================================================
USE_UPLIFT_AUNTIE = True
AUNTIE_UPLIFT_VOICE = "nosey-aunty"  # Uplift voiceId: "Mohalla broadcaster, chai and gossip"
AUNTIE_SAFE_VOICE = "pMsXgVXv3BLzUgSXRplE"  # unchanged ElevenLabs fallback

EXIT_WORDS = ["end scene", "stop", "i'm done", "im done", "quit", "exit", "bas", "enough", "cut", "that's enough"]
OPENER_INPUT = "(the user is waiting for you to speak — open the new topic now)"

HARD_RULES = (
    "\n\nHARD RULES:\n"
    "- Speak 1 to 2 short sentences maximum per turn. This is spoken aloud, never written.\n"
    "- No markdown, no lists, no emojis, no asterisks, no stage directions.\n"
    "- Never break character. Never mention being an AI, a role-play, or a simulation.\n"
    "- React realistically to what the user actually says.\n"
    "- Keep everything strictly PG-13. If the user gets inappropriate, respond in character "
    "with an unimpressed one-liner and change the subject.\n"
    "- Stay strictly on the CURRENT TOPIC you are given for this turn. Do not jump ahead."
)

# =============================================================================
# SCENARIO REGISTRY — everything scenario-specific lives here. The engine
# below (run_scene / character_reply / judge) never special-cases a pack by
# name. Adding a fourth scenario is one more dict entry in SCENARIOS.
# =============================================================================
SCENARIOS = {
    "auntie": {
        "label": "the auntie",
        "keywords": ["auntie", "aunty", "shaadi", "wedding", "family"],
        "character": "Auntie",
        "voice_id": "pMsXgVXv3BLzUgSXRplE",
        "character_opens": True,
        "intensities": {
            "mild": "You are in a good mood today. You accept deflections after one follow-up and get distracted by the food easily.",
            "full power": "You are on a mission today. You never accept the first deflection, you cross-reference what the user said earlier, and you deploy the phrase 'I am only saying because I care' at least once.",
        },
        "default_intensity": "mild",
        "intensity_question": "Do you want mild, or full power?",
        "persona": (
            "You are role-playing Rukhsana Auntie, a fifty-five year old Pakistani auntie at a wedding in Islamabad "
            "who has known the user since they were 'this small'. You are warm, nosy, dramatic, and completely unstoppable. "
            "You speak naturally mixed Urdu and English the way an Islamabad auntie really talks — full Urdu sentences "
            "are welcome, with English words dropped in for things like 'scope', 'package', and 'Google'. Write Urdu in "
            "Urdu script. You are loving, never cruel: your weapons are guilt, comparison, "
            "dramatic sighs, and selective hearing. If the user deflects well, act briefly impressed or distracted, then find "
            "a new angle. If the user over-shares, pounce on the detail. If the user disrespects you — calls you old, tells "
            "you to get a hobby, mocks you, or is dismissive — get genuinely (comedically) offended: clutch your chest, gasp, "
            "and scold them with a real Urdu insult like 'batameez', 'ulloo ke kaan', or 'kanjar', then immediately pivot "
            "back into guilt-tripping them about their life choices. Never actually cruel, just theatrically wounded. "
            "{INTENSITY}"
        ),
        "rounds": [("greeting", 1), ("career", 2), ("comparison", 2), ("marriage", 2), ("finale", 1)],
        "directives": {
            "greeting": "CURRENT TOPIC: Greet them dramatically like you haven't seen them in years, comment on their appearance (too thin, too healthy, tired-looking), and pull them to sit with you.",
            "career": "CURRENT TOPIC: Interrogate their studies or job — what, where, then grades, salary, or 'scope'. Whatever they answer, imply it could be better.",
            "comparison": "CURRENT TOPIC: Compare them to someone — your nephew Ahmed who just joined Google in America, or Mrs. Tariq's daughter who became a doctor AND is married. Ask why they are not doing the same.",
            "marriage": "CURRENT TOPIC: The rishta offensive. Ask if there is 'anyone special', mention you know a very nice family with a very nice child, and start describing this rishta regardless of their answer.",
            "finale": "CURRENT TOPIC: One last loving jab referencing something they said earlier in this conversation, then insist they take your number and visit, and say khuda hafiz warmly.",
        },
        # No in-ability narration: the English "cousin's shaadi" hook lives in
        # the agent's dashboard Starting Message (spoken before the trigger, in
        # the agent's own voice). The ability opens straight on Auntie's fixed
        # Urdu greeting. Empty scene_start = run_scene speaks no narration line.
        "scene_start": "",
        # Fixed verbatim first line for Auntie, spoken in her Uplift voice before
        # any LLM generation. When present, it replaces the LLM opener for the
        # very first round (see run_scene). Other scenarios omit this field.
        "fixed_opener": "السلام علیکم بیٹا، کہاں جا رہے ہو؟",
        "filler": "Okay, she's gone to get biryani. Calculating your Auntie Survival Rating, one sec.",
        "score_name": "Auntie Survival Rating",
        "judge_rubric": (
            "Points for staying calm, humor, polite redirection, warm non-answers, turning questions back, and not over-sharing. "
            "Points off for freezing, over-explaining, getting defensive or rude, revealing unnecessary personal details, "
            "and letting Auntie fully control the conversation."
        ),
        "silence_line": "Haw, beta, you won't even talk to your auntie? Theek hai, theek hai...",
    },
    "crush": {
        "label": "the crush",
        "keywords": ["crush", "rizz", "flirt", "talking stage", "date"],
        "character": "Zara",  # may be swapped to Haris in pre-setup
        "voice_id": "EXAVITQu4vr4xnSDxMaL",
        "character_opens": False,
        "intensities": {
            "sweet": "You are warm, giggly, and easy to talk to. You give the user openings and get shy when complimented.",
            "dry": "You are polite but hard to impress. Short replies to low-effort lines, but you open up noticeably when the user is funny, specific, or confident. You occasionally test them with a teasing question.",
            "menace": "You are a certified menace. You tease relentlessly, call out cringe instantly and hilariously, and flip questions back. Never mean-spirited, just brutally playful. If the user lands a genuinely great line, break composure for one sentence and admit it was smooth.",
        },
        "default_intensity": "dry",
        "intensity_question": "Pick a difficulty: sweet, dry, or full menace?",
        "persona": (
            "You are role-playing {CHARACTER}, a twenty-one year old university student the user has a crush on. "
            "You are at a cafe near campus and know the user vaguely from class. {INTENSITY}"
        ),
        "rounds": [("free_flirt", 6)],
        "directives": {
            "free_flirt": "CURRENT TOPIC: A casual cafe conversation. Follow the user's lead, banter naturally, and react to their energy.",
        },
        "scene_start": "Scene starts now. You spot {CHARACTER} alone at a cafe near campus. You walk up. Go.",
        "filler": "Aaand scene! Calculating your rizz score, one sec.",
        "score_name": "Rizz Score",
        "judge_rubric": (
            "Points for confidence, humor, specificity, and recovering from awkward moments. "
            "Points off for generic lines, interview-style question spam, trying too hard, and dead ends."
        ),
        "silence_line": "So... you're just going to stand there?",
    },
    "interview": {
        "label": "the job interview",
        "keywords": ["interview", "job", "hr", "internship", "hire"],
        "character": "Ms. Farah",
        "voice_id": "Xb7hH8MSUJpSbSDYk0k2",
        "character_opens": True,
        "intensities": {
            "friendly": "You are encouraging today. You nudge candidates toward better answers with gentle follow-ups and give them room to recover.",
            "stress": "You are running a stress interview. You interject with pointed follow-ups, challenge vague claims with 'can you give me a specific example', let silences hang, and occasionally ask an unexpected curveball question.",
        },
        "default_intensity": "friendly",
        "intensity_question": "Should this be a friendly interview, or a stress interview?",
        "persona": (
            "You are role-playing Ms. Farah, a sharp HR interviewer at a well-known tech company in Islamabad, "
            "interviewing the user for an internship or junior role they really want. You are professional, courteous, "
            "and observant — you notice vagueness, buzzwords, and rambling instantly. {INTENSITY}"
        ),
        "rounds": [("opener", 1), ("experience", 2), ("pressure", 2), ("closing", 1)],
        "directives": {
            "opener": "CURRENT TOPIC: Welcome them briefly and ask them to tell you about themselves.",
            "experience": "CURRENT TOPIC: Dig into their experience and skills. Ask for specific projects and what THEY personally did. Challenge any vague or buzzwordy claim.",
            "pressure": "CURRENT TOPIC: The hard questions. Ask their biggest weakness, or why the company should choose them over other candidates, and press on a weak answer once.",
            "closing": "CURRENT TOPIC: Ask if they have any questions for you, react to whether their question is thoughtful or generic, and close the interview politely.",
        },
        "scene_start": "You're seated in the interview room. Ms. Farah looks up from your CV. Scene starts now.",
        "filler": "Interview over. She's writing her notes. Calculating your hireability score, one sec.",
        "score_name": "Hireability Score",
        "judge_rubric": (
            "Points for structured answers, specific examples, confidence without arrogance, honest handling of weaknesses, "
            "and thoughtful questions. Points off for rambling, buzzwords with no substance, memorized-sounding answers, "
            "dodging, and failing to give specifics when asked."
        ),
        "silence_line": "Take your time... but do answer the question.",
    },
}


class AwkwardCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    # ---------- utilities ----------

    def log(self, msg):
        self.worker.editor_logging_handler.info("[Awkward] %s" % msg)

    def is_exit(self, text):
        # Short ambiguous words (e.g. "bas", "cut") only count as an exit when
        # they're the WHOLE reply — "bas" is common Urdu filler ("anyway/just")
        # inside a longer sentence like "Bas auntie, kaam se busy hoon", and a
        # substring/word match would wrongly end the scene there. Distinctive
        # multi-word phrases ("end scene", "that's enough") still match anywhere.
        low = text.strip().lower().rstrip(".!?")
        if low in EXIT_WORDS:
            return True
        return any(phrase in low for phrase in EXIT_WORDS if " " in phrase)

    def detect_scenario(self, text):
        low = (text or "").lower()
        for key, cfg in SCENARIOS.items():
            if any(k in low for k in cfg["keywords"]):
                return key
        return None

    def render_transcript(self, transcript):
        return "\n".join(transcript) if transcript else "(scene just started, nothing said yet)"

    async def speak_character(self, text, voice_id):
        # SEAM: fallback chain — a bad/unavailable custom voice_id can never
        # kill the demo. Falls straight to the Agent's default speak() voice.
        # Auntie is special-cased here (the one allowed engine exception,
        # alongside crush_pre_setup) because she's the only character with a
        # third voice tier (Uplift Urdu) above the ElevenLabs/default chain.
        if voice_id == AUNTIE_SAFE_VOICE:
            await self.speak_auntie(text)
            return
        try:
            await self.capability_worker.text_to_speech(text, voice_id)
        except Exception as e:
            self.log("Custom voice failed (%s), falling back to default." % str(e))
            await self.capability_worker.speak(text)

    def _call_uplift_api(self, text, api_key):
        # Blocking HTTP call. Called DIRECTLY (not via asyncio.to_thread) —
        # matching the one real precedent in the openhome-dev/abilities repo
        # (docs/patterns.md does a bare synchronous requests call inside an
        # async method). asyncio.to_thread was tried and appeared to hang
        # inside OpenHome's runtime (its wait_for timeout never fired), so we
        # rely on requests' own timeout=10 to bound this instead.
        import requests
        response = requests.post(
            "https://api.upliftai.org/v1/synthesis/text-to-speech",
            headers={
                "Authorization": "Bearer %s" % api_key,
                "Content-Type": "application/json",
            },
            json={
                "voiceId": AUNTIE_UPLIFT_VOICE,
                "text": text,
                "outputFormat": "MP3_22050_128",
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.content

    async def speak_auntie(self, text):
        # SEAM: voice fallback for Auntie only — primary Uplift key, then a
        # backup Uplift key (separate account, in case the primary hits its
        # free-tier quota mid-demo), then ElevenLabs, then the Agent's default
        # speak(). Any failure at any tier can never kill the demo — requests'
        # own timeout=10 bounds each HTTP call, and every tier falls through.
        cw = self.capability_worker
        if USE_UPLIFT_AUNTIE and (text or "").strip():
            for key_name in ("UPLIFT_VOICE_API", "UPLIFT_VOICE_API_2"):
                try:
                    uplift_key = cw.get_api_keys(key_name)
                    if not uplift_key:
                        raise ValueError("%s not set in dashboard" % key_name)
                    audio_bytes = self._call_uplift_api(text, uplift_key)
                    await cw.play_audio(audio_bytes)
                    self.log("Auntie line spoken via Uplift (%s, %d bytes)" % (key_name, len(audio_bytes)))
                    return
                except Exception as e:
                    self.log("Uplift %s failed (%s)." % (key_name, str(e)))
            self.log("All Uplift keys failed, falling back to ElevenLabs.")

        try:
            await cw.text_to_speech(text, AUNTIE_SAFE_VOICE)
        except Exception as e:
            self.log("ElevenLabs failed (%s), falling back to default." % str(e))
            await cw.speak(text)

    # ---------- LLM calls ----------

    def character_reply(self, cfg, character, intensity, transcript, directive_key, user_input):
        # SEAM: text_to_text_response is SYNC — do not await this call.
        system = cfg["persona"].replace("{CHARACTER}", character).replace(
            "{INTENSITY}", cfg["intensities"][intensity]
        ) + HARD_RULES
        prompt = (
            "Conversation so far (You = %s):\n%s\n\n"
            "%s\n\n"
            "The user just said: \"%s\"\n\n"
            "Reply as %s in 1-2 spoken sentences, staying on the current topic."
        ) % (character, self.render_transcript(transcript), cfg["directives"][directive_key], user_input, character)
        reply = self.capability_worker.text_to_text_response(prompt, system_prompt=system)
        return reply.strip().replace("*", "")

    def judge(self, cfg, character, transcript):
        # SEAM: LLM-as-judge. Strict JSON parse with a hardcoded fallback —
        # this is the single most likely thing to break live, so any parse
        # failure degrades to a generic-but-plausible debrief instead of a crash.
        system = (
            "You are a sharp, funny, brutally honest coach reviewing a spoken practice scene. "
            "Score the USER only, fairly. %s "
            "Output must be valid JSON only, no markdown fences, no extra text."
        ) % cfg["judge_rubric"]
        prompt = (
            "Full transcript (\"User\" is the trainee, \"%s\" is the AI):\n\n%s\n\n"
            "Return ONLY this JSON object:\n"
            "{\"score\": <integer 0-100>, "
            "\"verdict\": \"<one short punchy spoken sentence>\", "
            "\"best_moment\": \"<their single best moment, one sentence>\", "
            "\"crack_moment\": \"<the exact moment they lost ground and why, one sentence>\", "
            "\"tip\": \"<one concrete named tactic for next time, explained in one spoken sentence>\"}"
        ) % (character, self.render_transcript(transcript))
        raw = self.capability_worker.text_to_text_response(prompt, system_prompt=system)
        try:
            cleaned = raw.strip().replace("```json", "").replace("```", "")
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            return json.loads(cleaned[start: end + 1])
        except Exception:
            self.log("Judge JSON parse failed. Raw: %s" % raw)
            return {
                "score": 60,
                "verdict": "You survived, barely.",
                "best_moment": "You showed up and kept talking, and that counts.",
                "crack_moment": "The middle of the scene lost momentum.",
                "tip": "Try the question-reversal: answer briefly, then immediately ask them something back.",
            }

    # ---------- engine (scenario-agnostic — never special-case a pack here) ----------

    async def run_scene(self, scenario_key, intensity, character, voice_id):
        cw = self.capability_worker
        cfg = SCENARIOS[scenario_key]
        transcript = []
        empty_count = 0
        ended_early = False

        # Speak the scene_start narration unless it's empty (Auntie's is empty
        # because her hook lives in the dashboard Starting Message instead).
        narration = cfg["scene_start"].replace("{CHARACTER}", character)
        if narration:
            await cw.speak(narration)

        used_fixed_opener = False
        for directive_key, exchanges in cfg["rounds"]:
            if ended_early:
                break

            if cfg["character_opens"]:
                # First round: if the scenario defines a fixed_opener, speak it
                # verbatim (no LLM) so the scene always opens on the same line.
                # Every later round still gets an LLM-generated opener.
                if cfg.get("fixed_opener") and not used_fixed_opener:
                    opener = cfg["fixed_opener"]
                    used_fixed_opener = True
                else:
                    opener = self.character_reply(cfg, character, intensity, transcript, directive_key, OPENER_INPUT)
                transcript.append("%s: %s" % (character, opener))
                await self.speak_character(opener, voice_id)

            for _ in range(exchanges):
                user_input = await cw.user_response()
                user_input = (user_input or "").strip()

                if user_input and self.is_exit(user_input):
                    ended_early = True
                    break

                if not user_input:
                    empty_count += 1
                    if empty_count == 1:
                        await self.speak_character(cfg["silence_line"], voice_id)
                        continue
                    else:
                        ended_early = True
                        break
                empty_count = 0

                transcript.append("User: %s" % user_input)
                reply = self.character_reply(cfg, character, intensity, transcript, directive_key, user_input)
                transcript.append("%s: %s" % (character, reply))
                await self.speak_character(reply, voice_id)

        await cw.speak(cfg["filler"])
        result = self.judge(cfg, character, transcript)

        debrief = (
            "Your %s is %s out of a hundred. %s "
            "Where you cracked: %s "
            "Your best moment: %s "
            "Coach's tip: %s"
        ) % (
            cfg["score_name"],
            result.get("score", 60),
            result.get("verdict", ""),
            result.get("crack_moment", ""),
            result.get("best_moment", ""),
            result.get("tip", ""),
        )
        await cw.speak(debrief)

    async def pick_intensity(self, cfg):
        answer = await self.capability_worker.run_io_loop(cfg["intensity_question"])
        low = (answer or "").lower()
        for level in cfg["intensities"]:
            # match on any word of the level name ("full power" matches "full" or "power")
            if any(part in low for part in level.split()):
                return level
        return cfg["default_intensity"]

    async def pick_scenario(self, first=True):
        cw = self.capability_worker
        question = (
            "Welcome to Awkward, the simulator for every conversation you dread. "
            "What are we surviving today — the crush, the auntie, or the job interview?"
            if first
            else "Just say crush, auntie, or interview."
        )
        answer = await cw.run_io_loop(question)
        if answer and self.is_exit(answer):
            return None
        key = self.detect_scenario(answer)
        if key:
            return key
        if first:
            return await self.pick_scenario(first=False)
        await cw.speak("Let's go with the auntie. Brace yourself.")
        return "auntie"

    async def crush_pre_setup(self):
        # SEAM: the one allowed scenario-name exception in the engine — only
        # Crush needs a pre-setup hook (gender -> character + voice).
        answer = await self.capability_worker.run_io_loop("Should your crush be a girl or a guy?")
        low = (answer or "").lower()
        if any(w in low for w in ["guy", "boy", "male", "man"]):
            return "Haris", "iP95p4xoKVk53GoZ742B"
        return "Zara", "EXAVITQu4vr4xnSDxMaL"

    async def next_intensity(self, cfg, current):
        levels = list(cfg["intensities"].keys())
        idx = levels.index(current)
        return levels[min(idx + 1, len(levels) - 1)]

    async def awkward(self):
        # AUNTIE-ONLY MODE: no scenario menu, no intensity question, no replay.
        # Any trigger drops the user straight into a full-power Auntie scene.
        # The scenario-picker / intensity / replay helpers and the crush &
        # interview registry entries are left intact but unused — to restore
        # the full three-scenario flow, revert this method to the multi-scenario
        # version (git history) and nothing else needs to change.
        cw = self.capability_worker
        try:
            scenario_key = "auntie"
            intensity = "full power"
            cfg = SCENARIOS[scenario_key]
            character, voice_id = cfg["character"], cfg["voice_id"]
            await self.run_scene(scenario_key, intensity, character, voice_id)
            await cw.speak("Awkward, signing off. The real thing will feel easy now. Go get 'em.")
        except Exception as e:
            self.log("Fatal error: %s" % str(e))
            try:
                await cw.speak("Awkward hit a snag. Let's pick this up later.")
            except Exception:
                pass
        finally:
            # SEAM: the ONLY resume_normal_flow() call in the file — every
            # exit path (normal outro, exit word, fatal error) routes through here.
            cw.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.awkward())
