"""Orynq — stub main.py.

All audit capture + anchoring logic lives in ``background.py``, which
runs as a Background Daemon on session start. This file exists only to
satisfy the OpenHome CLI validator's REQUIRED_FILES + REQUIRED_PATTERNS
checks (main.py + class extending MatchingCapability + call() method +
``resume_normal_flow()`` + ``{{register_capability}}`` tag). The
ability is deployed with ``--category background_daemon`` and has no
hotwords, so this code path is never invoked at runtime.
"""
from __future__ import annotations

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


class OrynqAuditabilityMain(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register_capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.capability_worker.resume_normal_flow()
