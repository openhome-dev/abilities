"""
Test Utilities for OpenHome Abilities

Provides mock helpers and utilities for testing abilities in isolation.
"""

from unittest.mock import MagicMock, AsyncMock, patch
import json
import os
from typing import Dict, List, Any, Optional


class MockCapabilityWorker:
    """
    Mock CapabilityWorker for testing ability interactions.
    
    Use this to simulate user responses, LLM outputs, and verify speak() calls.
    """
    
    def __init__(self):
        self.spoken_messages: List[str] = []
        self.user_responses: List[str] = []
        self.response_index = 0
        self.llm_responses: Dict[str, str] = {}
        
    async def speak(self, message: str):
        """Record messages spoken by the ability."""
        self.spoken_messages.append(message)
        
    async def user_response(self) -> Optional[str]:
        """Return pre-configured user responses in sequence."""
        if self.response_index < len(self.user_responses):
            response = self.user_responses[self.response_index]
            self.response_index += 1
            return response
        return None
        
    async def run_io_loop(self, prompt: str) -> Optional[str]:
        """Simulate IO loop with pre-configured response."""
        await self.speak(prompt)
        return await self.user_response()
        
    def text_to_text_response(self, prompt: str) -> str:
        """Return pre-configured LLM response for a given prompt."""
        return self.llm_responses.get(prompt, "Mock LLM response")
        
    def resume_normal_flow(self):
        """Mock resuming normal flow."""
        pass
        
    def set_user_responses(self, responses: List[str]):
        """Configure user responses for the test."""
        self.user_responses = responses
        self.response_index = 0
        
    def set_llm_response(self, prompt: str, response: str):
        """Configure LLM response for a specific prompt."""
        self.llm_responses[prompt] = response
        
    def get_spoken_messages(self) -> List[str]:
        """Get all messages spoken during the test."""
        return self.spoken_messages
        
    def clear(self):
        """Clear all recorded state."""
        self.spoken_messages = []
        self.user_responses = []
        self.response_index = 0
        self.llm_responses = {}


class MockAgentWorker:
    """
    Mock AgentWorker for testing ability lifecycle.
    """
    
    def __init__(self):
        self.session_tasks = MockSessionTasks()
        self.capabilities: List[Any] = []
        
    def register_capability(self, capability):
        """Register a capability for testing."""
        self.capabilities.append(capability)


class MockSessionTasks:
    """
    Mock SessionTasks to track async task creation.
    """
    
    def __init__(self):
        self.created_tasks: List[Any] = []
        
    def create(self, coro):
        """Record task creation without actually running it."""
        self.created_tasks.append(coro)
        return MagicMock()


def load_ability_config(ability_path: str) -> Dict[str, Any]:
    """
    Load config.json from an ability directory.
    
    Args:
        ability_path: Path to ability directory (e.g., "official/weather")
        
    Returns:
        Parsed config dictionary
    """
    config_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        ability_path,
        "config.json"
    )
    with open(config_path) as f:
        return json.load(f)


def create_mock_worker_with_capability(capability_class) -> tuple:
    """
    Create a mock worker and capability instance for testing.
    
    Args:
        capability_class: The capability class to instantiate
        
    Returns:
        Tuple of (mock_worker, mock_capability_worker, capability_instance)
    """
    mock_worker = MockAgentWorker()
    mock_capability_worker = MockCapabilityWorker()
    
    # Register the capability
    capability = capability_class.register_capability()
    capability.worker = mock_worker
    capability.capability_worker = mock_capability_worker
    
    return mock_worker, mock_capability_worker, capability


class MockHTTPResponse:
    """Mock HTTP response for testing external API calls."""
    
    def __init__(self, json_data: Dict, status_code: int = 200):
        self.json_data = json_data
        self.status_code = status_code
        self.ok = status_code < 400
        
    def json(self):
        return self.json_data
        
    def raise_for_status(self):
        if not self.ok:
            raise Exception(f"HTTP {self.status_code}")


def mock_requests_get(url: str, **kwargs) -> MockHTTPResponse:
    """
    Mock requests.get for testing API integrations.
    
    Override this function in your tests to return specific responses.
    """
    return MockHTTPResponse({"mock": "data"})


def assert_spoke(capability_worker: MockCapabilityWorker, *expected_phrases):
    """
    Assert that the capability spoke messages containing expected phrases.
    
    Args:
        capability_worker: The mock capability worker
        expected_phrases: Phrases that should appear in spoken messages
    """
    spoken = " ".join(capability_worker.get_spoken_messages()).lower()
    for phrase in expected_phrases:
        assert phrase.lower() in spoken, \
            f"Expected phrase '{phrase}' not found in spoken messages: {spoken}"


def assert_spoke_exact(capability_worker: MockCapabilityWorker, *expected_messages):
    """
    Assert that the capability spoke exact messages.
    
    Args:
        capability_worker: The mock capability worker
        expected_messages: Exact messages that should have been spoken
    """
    spoken = capability_worker.get_spoken_messages()
    for i, expected in enumerate(expected_messages):
        assert i < len(spoken), \
            f"Expected message #{i+1} but only {len(spoken)} messages were spoken"
        assert spoken[i] == expected, \
            f"Message #{i+1} mismatch. Expected: '{expected}', Got: '{spoken[i]}'"


# Pytest fixtures for common test setup
def pytest_configure():
    """Configure pytest with common fixtures."""
    pass
