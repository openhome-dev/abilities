import json
import logging
from typing import Optional, Any, List

import trackingmore
import re

try:
    from openhome import MatchingCapability
    from openhome import editor_logging_handler
    from src.agent.capability_worker import CapabilityWorker
    from src.main import AgentWorker
except Exception:
    class MatchingCapability:
        def __init__(self, *args, **kwargs):
            pass

    def editor_logging_handler():
        return logging.StreamHandler()
    class AgentWorker:
        pass
    class CapabilityWorker:
        pass

logger = logging.getLogger('package_tracker')
logger.setLevel(logging.DEBUG)
try:
    handler = editor_logging_handler()
except Exception:
    handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
if not logger.handlers:
    logger.addHandler(handler)


class PackageTracker(MatchingCapability):
    # {{register capability}}
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        config_path = "config.json"
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {}
        unique_name = data.get("unique_name", "package_tracker")
        hotwords = data.get("matching_hotwords",
                            ["track my package", "where's my package", "package status", "tracking"])
        return cls(unique_name=unique_name, matching_hotwords=hotwords)

    def __init__(self, unique_name: Optional[str] = None, matching_hotwords: Optional[List[str]] = None):
        try:
            super().__init__(unique_name=unique_name, matching_hotwords=matching_hotwords)
        except Exception:
            try:
                super().__init__()
            except Exception:
                pass
        self.config_path = 'config.json'
        self.packages_path = 'packages.json'
        self.config = {}
        self.packages = []

    async def _load_packages(self):
        if self.capability_worker and hasattr(self.capability_worker, 'read_file'):
            try:
                content = await self.capability_worker.read_file(self.packages_path, False)
                self.packages = json.loads(content).get('packages', [])
            except Exception:
                self.packages = []
        else:
            self.packages = []

    async def _load_json_async(self, path: str, default: Any):
        if self.capability_worker and hasattr(self.capability_worker, 'read_file'):
            try:
                content = await self.capability_worker.read_file(path, False)
                return json.loads(content)
            except Exception:
                return default
        return default

    async def _save_packages_async(self):
        if self.capability_worker and hasattr(self.capability_worker, 'write_file'):
            try:
                await self.capability_worker.write_file(self.packages_path, json.dumps({'packages': self.packages}, indent=2), False)
            except Exception:
                logger.error('Failed to save packages.json')

    def call(self, worker):
        self.worker = worker
        if hasattr(worker, 'capability_worker'):
            self.capability_worker = worker.capability_worker
        else:
            self.capability_worker = type('CapabilityWorker', (), {})()
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            await self._load_packages()
            await self.worker.session_tasks.sleep(0.1)
            await self.capability_worker.speak("Package tracker ready. You can ask about your packages.")
            user_input = await self.capability_worker.user_response()
            self._handle_input(user_input)
        except Exception as e:
            logger.exception('Error in run: %s', e)
            await self.capability_worker.speak("Sorry, something went wrong.")
        finally:
            self.capability_worker.resume_normal_flow()

    def _handle_input(self, user_input: str):
        text = (user_input or '').lower()
        extracted_number = None
        if user_input:
            m = re.search(r"\b(\d{8,})\b", user_input)
            if m:
                extracted_number = m.group(1)

        if any(x in text for x in ('add', 'track', 'save', 'remember')):
            intent = 'add'
        elif any(x in text for x in ('where', 'status', 'check', 'how is')):
            intent = 'check'
        elif any(x in text for x in ('list', 'show', 'my packages')):
            intent = 'list'
        elif any(x in text for x in ('remove', 'delete', 'forget')):
            intent = 'remove'
        else:
            intent = 'unknown'

        if intent == 'add':
            self._respond(self.capability_worker, f"Add package called with number {extracted_number}. (Real implementation would create tracking.)")
        elif intent == 'check':
            self._respond(self.capability_worker, f"Checking status for {extracted_number}... (real implementation would call TrackingMore)")
        elif intent == 'list':
            if not self.packages:
                self._respond(self.capability_worker, "You have no tracked packages.")
            else:
                lines = [f'{p["friendly_name"]}: {p["tracking_number"]}' for p in self.packages]
                self._respond(self.capability_worker, "Your packages: " + ", ".join(lines))
        elif intent == 'remove':
            self._respond(self.capability_worker, f"Removing {extracted_number}...")
        else:
            self._respond(self.capability_worker, "I can help you track packages. Try 'track my package'.")

    def _respond(self, capability_worker, text: str):
        try:
            if hasattr(capability_worker, 'speak'):
                capability_worker.speak(text)
            elif hasattr(capability_worker, 'respond'):
                capability_worker.respond(text)
            else:
                logger.info(text)
        except Exception as e:
            logger.error(f"Failed to respond: {e}")
