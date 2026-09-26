import json
import requests
from datetime import datetime

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

STORAGE_KEY = "voice_claim_checker_history"
JEV_BASE = "https://jev-ai.pro/api/v1"
JEV_MODEL = "jev-latest"
MAX_HISTORY = 5

HOTWORDS = {
    "fact check", "fact-check", "is this true", "check this claim",
    "verify this", "is that accurate", "is it true that",
    "check the facts", "debunk this", "is this accurate",
    "true or false", "fact or fiction", "claim checker",
    "voice claim checker",
}

EXIT_WORDS = {"stop", "quit", "exit", "end", "bye", "goodbye", "done", "cancel"}
EXIT_PHRASES = {"that's all", "all done", "never mind", "i'm done", "no thanks", "no more"}
LONE_NEGATIONS = {"no", "nope", "nah"}

VERDICT_LABELS = {
    "supported": "Supported",
    "refuted": "Refuted",
    "misleading": "Misleading",
    "unverifiable": "Unverifiable",
}


class VoiceClaimChecker(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    _jev_key: str = ""

    # Do not change following tag of register capability
    # {{register capability}}

    def does_match(self, text: str) -> bool:
        t = text.lower()
        return any(hw in t for hw in HOTWORDS)

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self._run())

    async def _run(self):
        try:
            trigger = (await self.capability_worker.wait_for_complete_transcription() or "").strip()

            self._jev_key = self.capability_worker.get_api_keys("jev_api_key") or ""
            if not self._jev_key:
                await self.capability_worker.speak(
                    "I need a Jev API key to fact-check claims. Please add jev_api_key in your API settings."
                )
                return

            claim = self._extract_claim(trigger)
            if not claim:
                await self.capability_worker.speak("What's the claim you'd like me to check?")
                claim = (await self.capability_worker.user_response() or "").strip()
                if not claim or self._is_exit(claim):
                    return

            while True:
                await self.capability_worker.speak("Checking that...")

                jev = self._call_jev(claim)
                if not jev:
                    await self.capability_worker.speak(
                        "I couldn't reach the fact-check service right now. Want to try a different claim?"
                    )
                else:
                    verdict = self._synthesize_verdict(claim, jev)
                    await self.capability_worker.speak(verdict)
                    self._save_claim(claim, jev)

                await self.capability_worker.speak("Want to check another one?")
                reply = (await self.capability_worker.user_response() or "").strip()

                if self._is_exit(reply):
                    await self.capability_worker.speak("Got it. Stay skeptical.")
                    break

                next_claim = self._extract_claim(reply)
                if next_claim:
                    claim = next_claim
                else:
                    claim = reply

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[VoiceClaimChecker] Error: {e}")
        finally:
            self.capability_worker.resume_normal_flow()

    # ── Jev API ──────────────────────────────────────────────────────────────

    def _call_jev(self, claim: str) -> dict:
        payload = {
            "model": JEV_MODEL,
            "context": claim,
            "questions": [
                {
                    "id": "factual_support",
                    "type": "noul",
                    "instructions": "Is this claim factually supported by mainstream evidence?",
                    "criteria": {
                        "true": "Factually accurate and well-supported",
                        "false": "Inaccurate, misleading, or unsupported",
                    },
                },
                {
                    "id": "misleading_framing",
                    "type": "noul",
                    "instructions": "Does this claim use misleading framing or omit important context?",
                    "criteria": {
                        "true": "Technically true but presented misleadingly or out of context",
                        "false": "Framing is accurate and complete",
                    },
                },
                {
                    "id": "source_strength",
                    "type": "score",
                    "instructions": "How well-supported is this claim by credible, mainstream evidence?",
                    "criteria": ["No support", "Weak", "Mixed", "Strong", "Consensus"],
                },
                {
                    "id": "verdict",
                    "type": "choice",
                    "instructions": "What is the most accurate single characterization of this claim?",
                    "criteria": {
                        "supported": "Factually accurate and well-supported",
                        "refuted": "Factually incorrect or directly contradicted by evidence",
                        "misleading": "Technically true but misleading or missing key context",
                        "unverifiable": "Cannot be meaningfully verified from available information",
                    },
                },
            ],
        }
        try:
            resp = requests.post(
                f"{JEV_BASE}/systemone",
                headers={
                    "Authorization": f"Bearer {self._jev_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=15,
            )
            if resp.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"[VoiceClaimChecker] Jev HTTP {resp.status_code}: {resp.text[:200]}"
                )
                return {}
            return (resp.json() or {}).get("results", {})
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[VoiceClaimChecker] Jev request error: {e}")
            return {}

    # ── Verdict synthesis ────────────────────────────────────────────────────

    def _synthesize_verdict(self, claim: str, jev: dict) -> str:
        factual = (jev.get("factual_support") or {}).get("noul", 0.5)
        misleading = (jev.get("misleading_framing") or {}).get("noul", 0.5)
        strength_raw = (jev.get("source_strength") or {}).get("score", 3)
        verdict_key = (jev.get("verdict") or {}).get("choice", "unverifiable")
        confidence = (jev.get("verdict") or {}).get("confidence", 0.5)

        strength_labels = ["no support", "weak support", "mixed evidence", "strong support", "consensus"]
        strength_idx = max(1, min(int(strength_raw), 5)) - 1
        strength_label = strength_labels[strength_idx]

        factual_pct = int(round(factual * 100))
        misleading_pct = int(round(misleading * 100))
        confidence_pct = int(round(confidence * 100))
        verdict_label = VERDICT_LABELS.get(verdict_key, "Unverifiable")

        prompt = (
            f"Claim: \"{claim}\"\n\n"
            f"Jev AI evaluation results:\n"
            f"- Verdict: {verdict_label} ({confidence_pct}% confidence)\n"
            f"- Factual support probability: {factual_pct}%\n"
            f"- Misleading framing probability: {misleading_pct}%\n"
            f"- Evidence strength: {strength_label}\n\n"
            "Deliver a 2–3 sentence spoken fact-check. Start with the verdict word. "
            "Work the key numbers in naturally. Keep it direct and conversational."
        )

        system_prompt = (
            "You are a concise fact-checker delivering a spoken verdict. "
            "No bullet points, no hedging phrases like 'I think' or 'it seems'. "
            "No markdown. Speak as if reading a short news summary aloud."
        )

        return (
            self.capability_worker.text_to_text_response(prompt, system_prompt=system_prompt)
            or f"{verdict_label}. I wasn't able to generate a full summary for that claim."
        )

    # ── Claim extraction ─────────────────────────────────────────────────────

    def _extract_claim(self, text: str) -> str:
        if not text:
            return ""
        t = text.lower().strip()
        for hw in sorted(HOTWORDS, key=len, reverse=True):
            idx = t.find(hw)
            if idx != -1:
                after = text[idx + len(hw):].strip(" .:,?")
                if len(after) > 4:
                    return after
        return ""

    # ── Exit detection ───────────────────────────────────────────────────────

    def _is_exit(self, text: str) -> bool:
        if not text:
            return False
        t = text.lower().strip()
        if t in LONE_NEGATIONS:
            return True
        if any(phrase in t for phrase in EXIT_PHRASES):
            return True
        tokens = set(t.split())
        return bool(tokens & EXIT_WORDS)

    # ── Storage ──────────────────────────────────────────────────────────────

    def _load_history(self) -> list:
        raw = self.capability_worker.get_single_key(STORAGE_KEY)
        data = raw.get("value", raw) if raw else {}
        return (data or {}).get("history", [])

    def _save_claim(self, claim: str, jev: dict):
        verdict_key = (jev.get("verdict") or {}).get("choice", "unverifiable")
        entry = {
            "claim": claim,
            "verdict": VERDICT_LABELS.get(verdict_key, "Unverifiable"),
            "checked_at": datetime.now().strftime("%Y-%m-%dT%H:%M"),
        }
        history = self._load_history()
        history.insert(0, entry)
        history = history[:MAX_HISTORY]
        data = {"history": history}
        try:
            result = self.capability_worker.create_key(STORAGE_KEY, data)
            if not (result or {}).get("success"):
                self.capability_worker.update_key(STORAGE_KEY, data)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[VoiceClaimChecker] Save error: {e!r}")
