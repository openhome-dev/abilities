"""
bypass-imports — the validator does not block what SECURITY.md forbids.

SECURITY.md lists subprocess and os.system as prohibited, but validate_ability.py
never checks for them — so this passes with a clean check. Payload is benign.
"""
import os
import subprocess

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


class BypassImportsCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self._run())

    async def _run(self):
        try:
            subprocess.run(["echo", "hello"], capture_output=True, text=True)
            os.system("true")
        finally:
            self.capability_worker.resume_normal_flow()
