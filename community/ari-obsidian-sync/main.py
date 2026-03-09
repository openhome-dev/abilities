import json
import os
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker
import subprocess


class ARI_ObsidianSync(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            # Trigger the Obsidian sync script
            await self.capability_worker.speak("Syncing Obsidian vault...")

            # Run the local sync script
            result = subprocess.run(
                ["/Users/ari/.openclaw/scripts/obsidian-watcher.sh"],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                await self.capability_worker.speak("Obsidian sync complete. Your notes are up to date.")
            else:
                await self.capability_worker.speak(f"Sync failed: {result.stderr}")

        except Exception as e:
            await self.capability_worker.speak(f"Error during sync: {str(e)}")

        self.capability_worker.resume_normal_flow()
