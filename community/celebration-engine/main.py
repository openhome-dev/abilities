import json
from datetime import datetime

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# CELEBRATION ENGINE — Interactive Skill (main.py)
# Lets users review their logged wins and positive moments.
# The background daemon (background.py) handles automatic detection.
# =============================================================================

WINS_FILE = "celebration_engine_wins.json"

RECAP_PROMPT = (
    "Here are the user's recent positive moments:\n{wins}\n\n"
    "Generate a warm, encouraging 2-3 sentence recap of their wins. "
    "Be specific about what they achieved. End on an uplifting note.\n"
    "Return ONLY the recap message."
)


class CelebrationEngineCapability(MatchingCapability):
    model_config = {"extra": "allow", "arbitrary_types_allowed": True}

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            exists = await self.capability_worker.check_if_file_exists(
                WINS_FILE, False
            )

            if not exists:
                await self.capability_worker.speak(
                    "No wins logged yet. The celebration engine runs in the "
                    "background and notices when good things happen. "
                    "Keep talking — I'll catch the good stuff."
                )
                return

            raw = await self.capability_worker.read_file(WINS_FILE, False)
            wins = json.loads(raw)

            if not wins:
                await self.capability_worker.speak(
                    "No wins logged yet. I'm listening for good things in the background."
                )
                return

            # Show recent wins
            recent = wins[-10:]
            today = datetime.now().strftime("%Y-%m-%d")
            today_wins = [w for w in recent if w.get("date") == today]
            total = len(wins)

            if today_wins:
                await self.capability_worker.speak(
                    f"You've had {len(today_wins)} win{'s' if len(today_wins) != 1 else ''} today!"
                )
            else:
                await self.capability_worker.speak(
                    f"You have {total} wins logged overall."
                )

            # LLM recap
            wins_text = "\n".join(
                f"- {w.get('date', '')} {w.get('time', '')}: {w.get('summary', '')}"
                for w in recent
            )
            try:
                recap = self.capability_worker.text_to_text_response(
                    RECAP_PROMPT.format(wins=wins_text)
                )
                await self.capability_worker.speak(recap)
            except Exception:
                for win in recent[-3:]:
                    await self.capability_worker.speak(
                        f"{win.get('date', '')}: {win.get('summary', '')}"
                    )

            await self.capability_worker.speak(
                "Keep doing great things. I'm always listening for wins."
            )

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[CelebrationEngine] Error: {e}"
            )
            await self.capability_worker.speak(
                "Something went wrong checking your wins."
            )
        finally:
            self.capability_worker.resume_normal_flow()
