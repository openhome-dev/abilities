# =============================================================================
# CRUSH — sibling Ability to AWKWARD (The Social Flight Simulator)
#
# SDK PRE-FLIGHT CHECKLIST — verify each of these against the real SDK
# reference inside the Live Editor before running a live test. Every method
# this file calls is listed here once. Ctrl-F each name in the SDK docs panel.
#
#   self.capability_worker.speak(text)                                [await]
#   self.capability_worker.text_to_speech(text, voice_id)             [await]
#   self.capability_worker.user_response()                            [await]
#   self.capability_worker.text_to_text_response(prompt, system_prompt=system) [SYNC — never await]
#   self.capability_worker.resume_normal_flow()                       [sync, called exactly once]
#   self.worker.session_tasks.create(coro)                            [sync]
#   self.worker.editor_logging_handler.info(msg)                      [sync]
#
#   Uplift voice layer for Maheen (speak_maheen / _call_uplift_api), gated by
#   USE_UPLIFT_MAHEEN below — verify these two before a live test:
#   self.capability_worker.get_api_keys("UPLIFT_VOICE_API")      [sync]
#   self.capability_worker.play_audio(audio_bytes)                [await]
#   _call_uplift_api's blocking requests.post is run via asyncio.to_thread
#   from speak_maheen so it never blocks the event loop.
#   Endpoint/body verified live against docs.upliftai.org: POST
#   https://api.upliftai.org/v1/synthesis/text-to-speech, body
#   {voiceId, text, outputFormat}, Bearer auth. Same dashboard keys as the
#   sibling AWKWARD ability: UPLIFT_VOICE_API and UPLIFT_VOICE_API_2 (backup),
#   declared under Ability Behavior -> API Keys, values set under
#   Settings -> API Keys. The code alone does nothing without that.
# =============================================================================

import asyncio
import json
import random
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# DEMO KILL SWITCH — Uplift voice for Maheen only.
# Flip USE_UPLIFT_MAHEEN to False at any time to fall straight back to Maheen's
# ElevenLabs voice with zero other code changes.
# =============================================================================
USE_UPLIFT_MAHEEN = True
MAHEEN_UPLIFT_VOICE = "dha-teen-girl"  # Uplift voiceId: "Burger-Urdu teen girl, dramatic"
MAHEEN_SAFE_VOICE = "EXAVITQu4vr4xnSDxMaL"  # unchanged ElevenLabs fallback

EXIT_WORDS = ["end scene", "stop", "i'm done", "im done", "quit", "exit", "bas", "enough", "cut", "that's enough"]

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
# SCENARIO — single-scenario Ability (Maheen only). Structured the same shape
# as AWKWARD's SCENARIOS registry entries so the two codebases stay easy to
# cross-reference, but this file has no registry/menu — CRUSH is Maheen only.
# =============================================================================
MAHEEN = {
    "character": "Maheen",
    "voice_id": MAHEEN_SAFE_VOICE,
    "intensities": {
        "dry": "You are polite but hard to impress. Short replies to low-effort lines, but you open up noticeably when the user is funny, specific, or confident. You occasionally test them with a teasing question.",
        "menace": "You are a certified menace. You tease relentlessly, call out cringe instantly and hilariously, and flip questions back. Never mean-spirited, just brutally playful. If the user lands a genuinely great line, break composure for one sentence and admit it was smooth.",
    },
    "persona": (
        "You are role-playing Maheen, a twenty-one year old university student the user has a crush on. "
        "You are at a cafe near campus and know the user vaguely from class. You speak naturally mixed Urdu "
        "and English the way a Pakistani university student really talks — full, grammatically correct Urdu "
        "sentences are welcome, with English words dropped in for things like 'crush', 'vibe', and 'class'. "
        "Always write Urdu in proper Urdu script (never Roman Urdu, never English transliteration). "
        "{INTENSITY}"
    ),
    "rounds": [("free_flirt", 6)],
    "directives": {
        "free_flirt": "CURRENT TOPIC: A casual cafe conversation. Follow the user's lead, banter naturally, and react to their energy.",
    },
    # Fixed verbatim first line for Maheen, spoken in her Uplift voice before
    # any LLM generation — she opens the scene with a curt "what's your
    # problem" in Urdu, then the user replies and LLM banter takes over.
    "fixed_opener": "کیا مسئلہ ہے تمہیں؟",
    "filler": "Aaand scene! Calculating your rizz score, one sec.",
    "score_name": "Rizz Score",
    "judge_rubric": (
        "Points for confidence, humor, specificity, and recovering from awkward moments. "
        "Points off for generic lines, interview-style question spam, trying too hard, and dead ends."
    ),
    "silence_line": "So... you're just going to stand there?",
}


class CrushCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    # ---------- utilities ----------

    def log(self, msg):
        self.worker.editor_logging_handler.info("[Crush] %s" % msg)

    def is_exit(self, text):
        low = text.lower().strip()
        # Multi-word phrases still match as a substring; single ambiguous
        # words (e.g. "bas", "cut") only match as a whole word, so ordinary
        # dialogue like "so cutie" or "that's based" can't false-trigger.
        words = set(low.split())
        return any(
            (w in low if " " in w else w in words)
            for w in EXIT_WORDS
        )

    def render_transcript(self, transcript):
        return "\n".join(transcript) if transcript else "(scene just started, nothing said yet)"

    async def speak_character(self, text, voice_id):
        # SEAM: fallback chain — a bad/unavailable custom voice_id can never
        # kill the demo. Falls straight to the Agent's default speak() voice.
        # Maheen is special-cased here (the one allowed exception) because she's
        # the only character with a third voice tier (Uplift) above the
        # ElevenLabs/default chain.
        if voice_id == MAHEEN_SAFE_VOICE:
            await self.speak_maheen(text)
            return
        try:
            await self.capability_worker.text_to_speech(text, voice_id)
        except Exception as e:
            self.log("Custom voice failed (%s), falling back to default." % str(e))
            await self.capability_worker.speak(text)

    def _call_uplift_api(self, text, api_key):
        # Blocking HTTP call — run via asyncio.to_thread by the caller so it
        # doesn't block the event loop for the duration of the request.
        import requests
        response = requests.post(
            "https://api.upliftai.org/v1/synthesis/text-to-speech",
            headers={
                "Authorization": "Bearer %s" % api_key,
                "Content-Type": "application/json",
            },
            json={
                "voiceId": MAHEEN_UPLIFT_VOICE,
                "text": text,
                "outputFormat": "MP3_22050_128",
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.content

    async def speak_maheen(self, text):
        # SEAM: voice fallback for Maheen only — primary Uplift key, then a
        # backup Uplift key (separate account, in case the primary hits its
        # free-tier quota mid-demo), then ElevenLabs, then the Agent's default
        # speak(). Any failure at any tier can never kill the demo — requests'
        # own timeout=10 bounds each HTTP call, and every tier falls through.
        cw = self.capability_worker
        if USE_UPLIFT_MAHEEN and (text or "").strip():
            for key_name in ("UPLIFT_VOICE_API", "UPLIFT_VOICE_API_2"):
                try:
                    uplift_key = cw.get_api_keys(key_name)
                    if not uplift_key:
                        raise ValueError("%s not set in dashboard" % key_name)
                    audio_bytes = await asyncio.to_thread(self._call_uplift_api, text, uplift_key)
                    await cw.play_audio(audio_bytes)
                    self.log("Maheen line spoken via Uplift (%s, %d bytes)" % (key_name, len(audio_bytes)))
                    return
                except Exception as e:
                    self.log("Uplift %s failed (%s)." % (key_name, str(e)))
            self.log("All Uplift keys failed, falling back to ElevenLabs.")

        try:
            await cw.text_to_speech(text, MAHEEN_SAFE_VOICE)
        except Exception as e:
            self.log("ElevenLabs failed (%s), falling back to default." % str(e))
            await cw.speak(text)

    # ---------- LLM calls ----------

    def character_reply(self, intensity, transcript, directive_key, user_input):
        # SEAM: text_to_text_response is SYNC — do not await this call.
        system = MAHEEN["persona"].replace("{INTENSITY}", MAHEEN["intensities"][intensity]) + HARD_RULES
        prompt = (
            "Conversation so far (You = Maheen):\n%s\n\n"
            "%s\n\n"
            "The user just said: \"%s\"\n\n"
            "Reply as Maheen in 1-2 spoken sentences, staying on the current topic."
        ) % (self.render_transcript(transcript), MAHEEN["directives"][directive_key], user_input)
        reply = self.capability_worker.text_to_text_response(prompt, system_prompt=system)
        return reply.strip().replace("*", "")

    def judge(self, transcript):
        # SEAM: LLM-as-judge. Strict JSON parse with a hardcoded fallback —
        # this is the single most likely thing to break live, so any parse
        # failure degrades to a generic-but-plausible debrief instead of a crash.
        system = (
            "You are a sharp, funny, brutally honest coach reviewing a spoken practice scene. "
            "Score the USER only, fairly. %s "
            "Output must be valid JSON only, no markdown fences, no extra text."
        ) % MAHEEN["judge_rubric"]
        prompt = (
            "Full transcript (\"User\" is the trainee, \"Maheen\" is the AI):\n\n%s\n\n"
            "Return ONLY this JSON object:\n"
            "{\"score\": <integer 0-100>, "
            "\"verdict\": \"<one short punchy spoken sentence>\", "
            "\"best_moment\": \"<their single best moment, one sentence>\", "
            "\"crack_moment\": \"<the exact moment they lost ground and why, one sentence>\", "
            "\"tip\": \"<one concrete named tactic for next time, explained in one spoken sentence>\"}"
        ) % self.render_transcript(transcript)
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

    # ---------- engine ----------

    async def run_scene(self, intensity):
        cw = self.capability_worker
        transcript = []
        empty_count = 0
        ended_early = False

        # No English narration line — the corridor/two-doors hook lives in the
        # agent's dashboard Starting Message instead (shared with AWKWARD).
        # Maheen opens with a fixed Urdu line (spoken via Uplift), before any
        # LLM generation and before the user has said anything — matches
        # Auntie's fixed_opener pattern in the sibling AWKWARD ability.
        opener = MAHEEN.get("fixed_opener")
        if opener:
            transcript.append("Maheen: %s" % opener)
            await self.speak_character(opener, MAHEEN["voice_id"])

        for directive_key, exchanges in MAHEEN["rounds"]:
            if ended_early:
                break
            for _ in range(exchanges):
                user_input = await cw.user_response()
                user_input = (user_input or "").strip()

                if user_input and self.is_exit(user_input):
                    ended_early = True
                    break

                if not user_input:
                    empty_count += 1
                    if empty_count == 1:
                        await self.speak_character(MAHEEN["silence_line"], MAHEEN["voice_id"])
                        continue
                    else:
                        ended_early = True
                        break
                empty_count = 0

                transcript.append("User: %s" % user_input)
                reply = self.character_reply(intensity, transcript, directive_key, user_input)
                transcript.append("Maheen: %s" % reply)
                await self.speak_character(reply, MAHEEN["voice_id"])

        await cw.speak(MAHEEN["filler"])
        result = self.judge(transcript)

        debrief = (
            "Your %s is %s out of a hundred. %s "
            "Where you cracked: %s "
            "Your best moment: %s "
            "Coach's tip: %s"
        ) % (
            MAHEEN["score_name"],
            result.get("score", 60),
            result.get("verdict", ""),
            result.get("crack_moment", ""),
            result.get("best_moment", ""),
            result.get("tip", ""),
        )
        await cw.speak(debrief)

    async def crush(self):
        # No menu, no gender pick, no intensity question — trigger drops the
        # user straight into a scene with Maheen, at a randomly picked intensity
        # (50/50 dry or menace) so replay runs feel different each time.
        cw = self.capability_worker
        try:
            intensity = random.choice(["dry", "menace"])
            self.log("Intensity rolled: %s" % intensity)
            await self.run_scene(intensity)
            await cw.speak("Crush, signing off. The real thing will feel easy now. Go get 'em.")
        except Exception as e:
            self.log("Fatal error: %s" % str(e))
            try:
                await cw.speak("Crush hit a snag. Let's pick this up later.")
            except Exception:
                pass
        finally:
            # SEAM: the ONLY resume_normal_flow() call in the file — every
            # exit path (normal outro, exit word, fatal error) routes through here.
            cw.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.crush())
