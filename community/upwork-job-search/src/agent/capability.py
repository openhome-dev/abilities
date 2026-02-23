# Mock SDK - Capability module
from typing import Optional

class MatchingCapability:
    """Mock base class for MatchingCapability"""
    worker: 'AgentWorker' = None
    capability_worker: 'CapabilityWorker' = None
    unique_name: str = ""
    matching_hotwords: list = []

    def __init__(self, unique_name: str = "", matching_hotwords: list = None):
        self.unique_name = unique_name
        self.matching_hotwords = matching_hotwords or []
        self.worker = None
        self.capability_worker = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        """Register this capability - must be implemented by subclass"""
        raise NotImplementedError("Subclasses must implement register_capability")

    def call(self, worker: 'AgentWorker'):
        """Called when the capability is triggered"""
        raise NotImplementedError("Subclasses must implement call")

    async def run(self):
        """Main execution logic - must be implemented by subclass"""
        raise NotImplementedError("Subclasses must implement run")
