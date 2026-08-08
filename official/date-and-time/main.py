from datetime import datetime
from zoneinfo import ZoneInfo

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


class DateAndTimeCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            msg = (await self.capability_worker.wait_for_complete_transcription() or "").lower()
            tz = self.capability_worker.get_timezone()
            now = datetime.now(ZoneInfo(tz)) if tz else datetime.now()

            if "date" in msg and "time" not in msg:
                reply = f"Today is {now.strftime('%A, %B %-d, %Y')}."
            elif "time" in msg and "date" not in msg:
                reply = f"It's {now.strftime('%-I:%M %p')}."
            else:
                reply = f"It's {now.strftime('%-I:%M %p')} on {now.strftime('%A, %B %-d')}."

            await self.capability_worker.speak(reply)
        finally:
            self.capability_worker.resume_normal_flow()
