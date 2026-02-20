"""Shared test fixtures for Pet Care Assistant tests."""

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest


# Mock the OpenHome src modules before importing main
@pytest.fixture(scope="session", autouse=True)
def mock_src_modules():
    """Mock the src.agent modules that aren't available in test environment."""
    # Create mock modules
    mock_capability = MagicMock()
    mock_capability.MatchingCapability = type(
        "MatchingCapability",
        (),
        {"__init__": lambda self, unique_name="", matching_hotwords=None: None},
    )

    mock_capability_worker = MagicMock()
    mock_capability_worker.CapabilityWorker = MagicMock

    mock_main = MagicMock()
    mock_main.AgentWorker = MagicMock

    # Install mocks in sys.modules
    sys.modules["src"] = MagicMock()
    sys.modules["src.agent"] = MagicMock()
    sys.modules["src.agent.capability"] = mock_capability
    sys.modules["src.agent.capability_worker"] = mock_capability_worker
    sys.modules["src.main"] = mock_main

    # Add parent directory to path
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    yield

    # Cleanup not strictly necessary for session-scope fixture


@pytest.fixture
def mock_worker():
    """Mock AgentWorker."""
    worker = MagicMock()
    worker.editor_logging_handler = MagicMock()
    worker.editor_logging_handler.info = MagicMock()
    worker.editor_logging_handler.error = MagicMock()
    worker.editor_logging_handler.warning = MagicMock()
    return worker


@pytest.fixture
def mock_capability_worker():
    """Mock CapabilityWorker."""
    cw = MagicMock()
    cw.speak = AsyncMock()
    cw.user_response = AsyncMock()
    cw.run_io_loop = AsyncMock()
    cw.text_to_text_response = MagicMock()
    cw.run_confirmation_loop = AsyncMock()
    cw.check_if_file_exists = AsyncMock()
    cw.read_file = AsyncMock()
    cw.write_file = AsyncMock()
    cw.delete_file = AsyncMock()
    cw.resume_normal_flow = MagicMock()
    return cw


@pytest.fixture
def capability(mock_worker, mock_capability_worker):
    """Create a PetCareAssistantCapability instance with mocked dependencies."""
    from activity_log_service import ActivityLogService
    from external_api_service import ExternalAPIService
    from llm_service import LLMService
    from main import PetCareAssistantCapability
    from pet_data_service import PetDataService

    cap = PetCareAssistantCapability(
        unique_name="test_pet_care", matching_hotwords=["pet care", "my pets"]
    )
    cap.worker = mock_worker
    cap.capability_worker = mock_capability_worker
    cap.pet_data = {}
    cap.activity_log = []
    cap._geocode_cache = {}

    # Initialize all services
    cap.pet_data_service = PetDataService(mock_capability_worker, mock_worker)
    cap.activity_log_service = ActivityLogService(mock_worker, max_log_entries=500)
    cap.external_api_service = ExternalAPIService(
        mock_worker, serper_api_key="test_key"
    )
    cap.llm_service = LLMService(mock_capability_worker, mock_worker, cap.pet_data)

    return cap
