"""
Pytest configuration and fixtures for ability tests.

This file is automatically discovered by pytest and sets up the test environment.
"""

import sys
import os
from pathlib import Path

# Add the abilities directory to the Python path
# This allows tests to import abilities like: from official.weather.main import WeatherCapability
abilities_root = Path(__file__).parent.parent
sys.path.insert(0, str(abilities_root))

# Note: Tests require the OpenHome SDK to be available in the Python path.
# The SDK provides the following modules:
#   - src.agent.capability (MatchingCapability base class)
#   - src.agent.capability_worker (CapabilityWorker)
#   - src.main (AgentWorker)
#
# When running in the OpenHome environment, these modules are automatically available.
# For standalone testing, you may need to mock these dependencies or run tests
# within the OpenHome system itself.

import pytest


@pytest.fixture
def mock_config_path(tmp_path):
    """
    Fixture providing a temporary config.json path for testing.
    
    Usage:
        def test_with_config(mock_config_path):
            config_file = mock_config_path / "config.json"
            config_file.write_text('{"unique_name": "test"}')
    """
    return tmp_path


@pytest.fixture
def sample_ability_config():
    """
    Fixture providing a sample ability configuration.
    
    Usage:
        def test_config(sample_ability_config):
            assert sample_ability_config["unique_name"] == "test-ability"
    """
    return {
        "unique_name": "test-ability",
        "matching_hotwords": ["test", "example"],
        "description": "A test ability",
        "enabled": True
    }


# Configure pytest-asyncio
pytest_plugins = ['pytest_asyncio']


def pytest_configure(config):
    """
    Pytest hook called after command line options have been parsed.
    
    Registers custom markers and performs initialization.
    """
    config.addinivalue_line(
        "markers", "unit: mark test as a unit test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow-running"
    )
    config.addinivalue_line(
        "markers", "api: mark test as requiring API mocking"
    )


def pytest_collection_modifyitems(config, items):
    """
    Pytest hook called after test collection.
    
    Automatically skips tests if required dependencies are not available.
    """
    skip_no_sdk = pytest.mark.skip(reason="OpenHome SDK not available")
    
    for item in items:
        # Check if test file imports abilities (which require SDK)
        test_file = item.fspath
        
        # If SDK modules aren't available, we should skip SDK-dependent tests
        # This is detected during test execution via ImportError handling
        pass  # Actual skipping happens in test files with pytest.skip()
