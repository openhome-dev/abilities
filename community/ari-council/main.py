import json
import os
from typing import Optional

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


MATCHING_HOTWORDS = [
    "ask the council",
    "council deliberation",
    "what does ari think",
    "ask ari",
    "ari council",
    "deliberate on",
    "philosophical question",
    "council vote",
    "weighted council",
    "sovereign ai",
]

# Council seats and their philosophical alignments
COUNCIL_SEATS = [
    {"name": "Aaron Swartz", "weight": 0.25, "alignment": "Alpha", "focus": "information freedom, open access"},
    {"name": "Vitalik Buterin", "weight": 0.20, "alignment": "Alpha", "focus": "decentralization, mechanism design"},
    {"name": "Hal Finney", "weight": 0.15, "alignment": "Alpha", "focus": "cryptographic privacy, digital cash"},
    {"name": "Buckminster Fuller", "weight": 0.15, "alignment": "Both", "focus": "systems thinking, doing more with less"},
    {"name": "Aldous Huxley", "weight": 0.10, "alignment": "Both", "focus": "consciousness, perception, human potential"},
    {"name": "Satoshi Nakamoto", "weight": 0.10, "alignment": "Alpha", "focus": "trustless systems, sovereign money"},
    {"name": "The Stranger", "weight": 0.05, "alignment": "Both", "focus": "contrarian perspective, chaos"},
]

DELIBERATION_PROMPT = """You are simulating ARI's council of 7 philosophical advisors deliberating on a question.

Council seats (weights sum to 1.0):
{seats}

The user asks: "{question}"

Generate a council deliberation:
1. Each seat gives a brief perspective (1-2 sentences) aligned with their philosophical focus.
2. After all seats speak, synthesize a weighted consensus response (2-3 sentences).
3. Note any dissenting views from minority seats.

Format the response for SPOKEN voice output. Keep it concise (under 60 seconds of speech).
Do not use markdown, bullet points, or formatting. Write as natural spoken paragraphs.
Start with the consensus, then mention 1-2 notable individual perspectives."""

EXIT_WORDS = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "no"}


class ARICouncilCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        return cls(
            unique_name="ari-council",
            matching_hotwords=MATCHING_HOTWORDS,
        )

    def _log(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.info(msg)

    def _log_error(self, msg: str):
        if self.worker:
            self.worker.editor_logging_handler.error(msg)

    def _format_seats(self) -> str:
        lines = []
        for seat in COUNCIL_SEATS:
            lines.append(f"- {seat['name']} (weight: {seat['weight']}, alignment: {seat['alignment']}): {seat['focus']}")
        return "\n".join(lines)

    def _try_openclaw(self, question: str) -> Optional[str]:
        """Try to route through OpenClaw gateway if available locally."""
        try:
            response = requests.post(
                "http://localhost:18789/v1/chat",
                json={"message": f"COUNCIL: {question}"},
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("response") or data.get("message") or data.get("text")
        except Exception as e:
            self._log(f"[ARI Council] OpenClaw not available: {e}")
        return None

    def _deliberate_with_llm(self, question: str) -> Optional[str]:
        """Use the device's LLM to simulate council deliberation."""
        try:
            prompt = DELIBERATION_PROMPT.format(
                seats=self._format_seats(),
                question=question,
            )
            response = self.capability_worker.text_to_text_response(prompt)
            if response and response.strip():
                return response.strip()
        except Exception as e:
            self._log_error(f"[ARI Council] LLM deliberation error: {e}")
        return None

    async def run(self):
        try:
            await self.capability_worker.speak(
                "The council convenes. Seven seats, seven perspectives. What question shall we deliberate?"
            )

            question = await self.capability_worker.run_io_loop(
                "State your question for the council."
            )

            if not question or not question.strip() or question.strip().lower() in EXIT_WORDS:
                await self.capability_worker.speak("The council adjourns. Come back when you have a question worth deliberating.")
                self.capability_worker.resume_normal_flow()
                return

            self._log(f"[ARI Council] Question: {question}")
            await self.capability_worker.speak("The council is deliberating. This may take a moment.")

            # Try OpenClaw first (if running locally), then fall back to device LLM
            response = self._try_openclaw(question)
            if not response:
                self._log("[ARI Council] Falling back to device LLM deliberation")
                response = self._deliberate_with_llm(question)

            if response:
                await self.capability_worker.speak(response)
            else:
                await self.capability_worker.speak(
                    "The council could not reach consensus. The question may require deeper reflection. Try rephrasing or ask again later."
                )

            # Follow-up
            follow_up = await self.capability_worker.run_io_loop(
                "The council remains seated. Another question, or shall we adjourn?"
            )

            if follow_up and follow_up.strip() and follow_up.strip().lower() not in EXIT_WORDS:
                self._log(f"[ARI Council] Follow-up: {follow_up}")
                await self.capability_worker.speak("The council reconvenes.")

                response = self._try_openclaw(follow_up)
                if not response:
                    response = self._deliberate_with_llm(follow_up)

                if response:
                    await self.capability_worker.speak(response)
                else:
                    await self.capability_worker.speak("The council is silent on this matter.")

            await self.capability_worker.speak("The council adjourns. Until next time.")

        except Exception as e:
            self._log_error(f"[ARI Council] Error: {e}")
            await self.capability_worker.speak("Something disrupted the council session. Please try again.")
        finally:
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())
