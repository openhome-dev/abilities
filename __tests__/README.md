# Ability Testing Guide

This directory contains test infrastructure and test suites for OpenHome abilities.

## Overview

Testing abilities ensures they work reliably and helps catch bugs before users encounter them. This guide will help you write effective tests for your abilities.

## Prerequisites

### SDK Dependencies

Ability tests require the OpenHome SDK modules to be available:
- `src.agent.capability` — Base capability classes
- `src.agent.capability_worker` — Capability worker interface
- `src.main` — Agent worker

**Running Tests:**

1. **Within OpenHome environment** — Tests run automatically with full SDK access
2. **Standalone development** — Tests use mocks and may skip SDK-dependent functionality

### Installing Test Dependencies

```bash
# From the abilities directory
pip install -r requirements-test.txt
```

This installs:
- `pytest` — Test framework
- `pytest-asyncio` — Async test support
- `pytest-cov` — Coverage reporting
- `pytest-mock` — Enhanced mocking

## Quick Start

### Running Tests

```bash
# Run all ability tests
pytest abilities/__tests__/

# Run tests for a specific ability
pytest abilities/__tests__/official/test_weather.py

# Run with verbose output
pytest abilities/__tests__/ -v

# Run with coverage
pytest abilities/__tests__/ --cov=abilities
```

### Writing Your First Test

1. Create a test file in the appropriate directory:
   - `__tests__/official/` for official abilities
   - `__tests__/community/` for community abilities

2. Name your test file `test_<ability_name>.py`

3. Import the test utilities:
```python
from __tests__.utils import (
    MockAgentWorker,
    MockCapabilityWorker,
    create_mock_worker_with_capability,
    assert_spoke
)
```

4. Write test classes and methods following the examples below.

## Test Structure

### Basic Test Template

```python
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from __tests__.utils import (
    MockCapabilityWorker,
    create_mock_worker_with_capability,
    assert_spoke
)

from community.your_ability.main import YourAbilityCapability


class TestYourAbilityBasic:
    """Test basic functionality."""
    
    @pytest.mark.asyncio
    async def test_basic_flow(self):
        """Test the main flow of your ability."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            YourAbilityCapability
        )
        
        # Configure mock responses
        mock_cap_worker.set_user_responses(["test input", "exit"])
        
        # Run your ability
        await capability.your_main_method()
        
        # Verify behavior
        assert_spoke(mock_cap_worker, "expected phrase")
```

## Mock Utilities

### MockCapabilityWorker

The `MockCapabilityWorker` simulates user interactions and captures ability outputs.

#### Key Methods

**`set_user_responses(responses: List[str])`**
- Configure what the "user" will say
- Responses are returned in sequence

```python
mock_cap_worker.set_user_responses([
    "first response",
    "second response",
    "exit"
])
```

**`set_llm_response(prompt: str, response: str)`**
- Configure LLM responses for specific prompts
- Useful for testing conversational abilities

```python
mock_cap_worker.set_llm_response(
    "What advice would you give?",
    "Try breaking the problem into smaller steps."
)
```

**`get_spoken_messages() -> List[str]`**
- Get all messages spoken by the ability
- Useful for verification

```python
spoken = mock_cap_worker.get_spoken_messages()
assert "Hello" in spoken[0]
```

**`clear()`**
- Reset all state between tests
- Usually not needed (each test gets fresh mocks)

### Assertion Helpers

**`assert_spoke(capability_worker, *phrases)`**
- Verify that the ability spoke messages containing the given phrases
- Case-insensitive partial matching

```python
assert_spoke(mock_cap_worker, "welcome", "how can I help")
```

**`assert_spoke_exact(capability_worker, *messages)`**
- Verify exact messages were spoken
- Case-sensitive exact matching

```python
assert_spoke_exact(mock_cap_worker, "Goodbye!", "Thanks for using the ability.")
```

## Testing Patterns

### 1. Conversational Flow Testing

Test abilities that interact with users through multiple turns:

```python
@pytest.mark.asyncio
async def test_conversation_flow(self):
    mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
        ConversationalAbility
    )
    
    # Set up conversation
    mock_cap_worker.set_user_responses([
        "I need help",
        "Yes, please",
        "Thank you"
    ])
    
    await capability.run()
    
    # Verify conversation flow
    spoken = mock_cap_worker.get_spoken_messages()
    assert len(spoken) >= 3
    assert_spoke(mock_cap_worker, "how can I assist")
```

### 2. API Integration Testing

Test abilities that call external APIs:

```python
from unittest.mock import patch
from __tests__.utils import MockHTTPResponse

@pytest.mark.asyncio
async def test_api_call(self):
    mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
        APIAbility
    )
    
    mock_cap_worker.set_user_responses(["query"])
    
    # Mock API response
    mock_response = MockHTTPResponse({
        "data": "test value"
    })
    
    with patch('requests.get', return_value=mock_response):
        await capability.fetch_data()
    
    assert_spoke(mock_cap_worker, "test value")
```

### 3. Error Handling Testing

Test how your ability handles errors:

```python
@pytest.mark.asyncio
async def test_handles_api_error(self):
    mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
        RobustAbility
    )
    
    # Simulate API failure
    with patch('requests.get', side_effect=Exception("Network error")):
        await capability.fetch_data()
    
    # Should handle gracefully
    assert_spoke(mock_cap_worker, "sorry", "error")
```

### 4. Edge Case Testing

Test boundary conditions and unusual inputs:

```python
@pytest.mark.asyncio
async def test_empty_input(self):
    mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
        InputAbility
    )
    
    mock_cap_worker.set_user_responses(["", "exit"])
    
    await capability.run()
    
    # Should prompt again
    assert_spoke(mock_cap_worker, "didn't hear", "try again")
```

### 5. Configuration Testing

Test that your ability loads configuration correctly:

```python
def test_capability_registration(self):
    capability = MyAbility.register_capability()
    
    assert capability.unique_name == "my-ability"
    assert len(capability.matching_hotwords) > 0
    assert "keyword" in capability.matching_hotwords
```

## Test Organization

Organize your tests into logical classes:

```python
class TestBasicFlow:
    """Test basic happy-path functionality."""
    # Basic flow tests here

class TestAPIIntegration:
    """Test external API calls."""
    # API tests here

class TestErrorHandling:
    """Test error scenarios."""
    # Error tests here

class TestEdgeCases:
    """Test boundary conditions."""
    # Edge case tests here

class TestConfiguration:
    """Test config loading and validation."""
    # Config tests here
```

## Best Practices

### 1. Test One Thing Per Test
Each test should focus on a single aspect of functionality.

❌ **Bad:**
```python
async def test_everything(self):
    # Tests initialization, API call, error handling, and exit all in one
```

✅ **Good:**
```python
async def test_initialization(self):
    # Tests only initialization

async def test_api_call(self):
    # Tests only API integration

async def test_error_handling(self):
    # Tests only error scenarios
```

### 2. Use Descriptive Test Names
Test names should describe what they're testing.

❌ **Bad:**
```python
def test_1(self):
def test_stuff(self):
```

✅ **Good:**
```python
def test_asks_for_location_on_start(self):
def test_handles_invalid_api_response(self):
```

### 3. Mock External Dependencies
Never make real API calls in tests.

❌ **Bad:**
```python
# Makes real HTTP request
response = requests.get("https://api.example.com")
```

✅ **Good:**
```python
with patch('requests.get', return_value=mock_response):
    # Test your ability's logic
```

### 4. Test Both Success and Failure
Don't just test the happy path.

```python
async def test_successful_query(self):
    # Test when everything works

async def test_failed_query(self):
    # Test when something goes wrong
```

### 5. Keep Tests Fast
Use mocks instead of real services. Tests should run in milliseconds.

### 6. Make Tests Independent
Each test should be able to run in isolation.

## Example Test Suites

### Simple Logic Ability (Coin Flipper)
See: `community/test_coin_flipper.py`
- Tests random logic
- Tests repeat functionality
- Tests exit conditions

### Conversational Ability (Basic Advisor)
See: `official/test_basic_advisor.py`
- Tests LLM integration
- Tests feedback collection
- Tests conversational flow

### API Integration Ability (Weather)
See: `official/test_weather.py`
- Tests geocoding API
- Tests weather API
- Tests error handling

## Fixtures

Create reusable test data in `fixtures/` directory:

```python
# fixtures/sample_configs.py
SAMPLE_WEATHER_CONFIG = {
    "unique_name": "weather",
    "matching_hotwords": ["weather", "forecast"]
}

# fixtures/sample_api_responses.py
SAMPLE_WEATHER_RESPONSE = {
    "current_weather": {
        "temperature": 72.0,
        "windspeed": 5.0
    }
}
```

## Common Issues

### Import Errors
If you get import errors, make sure:
1. You're running from the `abilities/` directory
2. You've added the path adjustment: `sys.path.insert(0, ...)`
3. The ability module exists in the expected location

### Async Test Errors
Always use `@pytest.mark.asyncio` for async tests:
```python
@pytest.mark.asyncio
async def test_async_method(self):
    await capability.some_async_method()
```

### Mock Not Working
Make sure you're patching the right import path:
```python
# If ability imports as: from official.weather.main import requests
with patch('official.weather.main.requests.get'):
    
# If ability imports as: import requests
with patch('requests.get'):
```

## Resources

- **pytest documentation**: https://docs.pytest.org/
- **unittest.mock guide**: https://docs.python.org/3/library/unittest.mock.html
- **Example tests**: Check the existing test files in this directory

## Contributing

When contributing a new ability, please include:
- [ ] Comprehensive test suite
- [ ] Tests for success scenarios
- [ ] Tests for error scenarios
- [ ] Tests for edge cases
- [ ] Configuration validation tests

See `../CONTRIBUTING.md` for more details on contributing to OpenHome abilities.
