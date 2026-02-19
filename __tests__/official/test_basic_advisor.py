"""
Tests for Basic Advisor Ability

Tests the basic-advisor ability, including:
- Problem collection and advice generation
- LLM integration
- User feedback collection
- Conversational flow
"""

import pytest
import sys
import os
from unittest.mock import patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from __tests__.utils import (
    MockAgentWorker,
    MockCapabilityWorker,
    create_mock_worker_with_capability,
    assert_spoke,
    assert_spoke_exact
)


# Import the ability
try:
    from official.basic_advisor.main import BasicAdvisorCapability
except ImportError:
    pytest.skip("Basic advisor capability not available", allow_module_level=True)


class TestBasicAdvisorFlow:
    """Test the full conversational flow."""
    
    @pytest.mark.asyncio
    async def test_complete_advice_flow(self):
        """Test complete flow: intro -> problem -> advice -> feedback -> exit."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            BasicAdvisorCapability
        )
        
        # Configure user responses
        problem = "I can't decide what to eat for dinner"
        mock_cap_worker.set_user_responses([
            problem,           # User's problem
            "yes, thank you"  # Feedback
        ])
        
        # Configure LLM response
        advice = "Try making a list of what you have in the fridge and pick the easiest option."
        mock_cap_worker.set_llm_response(
            f"The user has the following problem: {problem}. Provide a helpful solution in just 1 or 2 sentences.",
            advice
        )
        
        # Run the advice flow
        await capability.give_advice()
        
        # Verify the flow
        spoken_messages = mock_cap_worker.get_spoken_messages()
        
        # Should start with intro
        assert any("advisor" in msg.lower() for msg in spoken_messages[:2])
        
        # Should provide the advice
        assert any(advice in msg for msg in spoken_messages)
        
        # Should ask for feedback
        assert any("satisfied" in msg.lower() for msg in spoken_messages)
        
        # Should thank and exit
        assert any("thank you" in msg.lower() for msg in spoken_messages)
        assert any("goodbye" in msg.lower() for msg in spoken_messages)
        
    @pytest.mark.asyncio
    async def test_intro_prompt(self):
        """Test that the intro prompt is spoken correctly."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            BasicAdvisorCapability
        )
        
        mock_cap_worker.set_user_responses(["test problem", "yes"])
        mock_cap_worker.set_llm_response(
            "The user has the following problem: test problem. Provide a helpful solution in just 1 or 2 sentences.",
            "Test advice"
        )
        
        await capability.give_advice()
        
        # First message should be the intro
        first_message = mock_cap_worker.get_spoken_messages()[0]
        assert "advisor" in first_message.lower()
        assert "problem" in first_message.lower()


class TestBasicAdvisorLLM:
    """Test LLM integration."""
    
    @pytest.mark.asyncio
    async def test_llm_receives_correct_prompt(self):
        """Test that LLM receives the correctly formatted prompt."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            BasicAdvisorCapability
        )
        
        problem = "I'm having trouble sleeping at night"
        expected_prompt = f"The user has the following problem: {problem}. Provide a helpful solution in just 1 or 2 sentences."
        advice = "Try establishing a consistent bedtime routine."
        
        mock_cap_worker.set_user_responses([problem, "yes"])
        mock_cap_worker.set_llm_response(expected_prompt, advice)
        
        await capability.give_advice()
        
        # Verify the advice was spoken
        spoken = " ".join(mock_cap_worker.get_spoken_messages())
        assert advice in spoken
        
    @pytest.mark.asyncio
    async def test_llm_response_is_spoken(self):
        """Test that LLM's advice is spoken to the user."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            BasicAdvisorCapability
        )
        
        problem = "I need help organizing my schedule"
        advice = "Use a calendar app and block time for important tasks first."
        
        mock_cap_worker.set_user_responses([problem, "yes"])
        mock_cap_worker.set_llm_response(
            f"The user has the following problem: {problem}. Provide a helpful solution in just 1 or 2 sentences.",
            advice
        )
        
        await capability.give_advice()
        
        # The advice should be in the spoken messages
        assert_spoke(mock_cap_worker, advice)


class TestBasicAdvisorFeedback:
    """Test feedback collection."""
    
    @pytest.mark.asyncio
    async def test_feedback_prompt_includes_satisfaction(self):
        """Test that feedback prompt asks about satisfaction."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            BasicAdvisorCapability
        )
        
        mock_cap_worker.set_user_responses(["test problem", "yes"])
        mock_cap_worker.set_llm_response(
            "The user has the following problem: test problem. Provide a helpful solution in just 1 or 2 sentences.",
            "test advice"
        )
        
        await capability.give_advice()
        
        # Should ask about satisfaction
        assert_spoke(mock_cap_worker, "satisfied")
        
    @pytest.mark.asyncio
    async def test_positive_feedback(self):
        """Test handling of positive feedback."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            BasicAdvisorCapability
        )
        
        mock_cap_worker.set_user_responses(["problem", "yes, very helpful!"])
        mock_cap_worker.set_llm_response(
            "The user has the following problem: problem. Provide a helpful solution in just 1 or 2 sentences.",
            "advice"
        )
        
        await capability.give_advice()
        
        # Should thank the user and exit gracefully
        assert_spoke(mock_cap_worker, "thank you", "goodbye")
        
    @pytest.mark.asyncio
    async def test_negative_feedback(self):
        """Test handling of negative feedback."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            BasicAdvisorCapability
        )
        
        mock_cap_worker.set_user_responses(["problem", "no, not really"])
        mock_cap_worker.set_llm_response(
            "The user has the following problem: problem. Provide a helpful solution in just 1 or 2 sentences.",
            "advice"
        )
        
        await capability.give_advice()
        
        # Should still thank and exit gracefully
        assert_spoke(mock_cap_worker, "thank you", "goodbye")


class TestBasicAdvisorEdgeCases:
    """Test edge cases and error handling."""
    
    @pytest.mark.asyncio
    async def test_empty_problem(self):
        """Test handling when user provides empty problem."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            BasicAdvisorCapability
        )
        
        # User provides empty input
        mock_cap_worker.set_user_responses(["", "yes"])
        
        # LLM should still be called with empty problem
        mock_cap_worker.set_llm_response(
            "The user has the following problem: . Provide a helpful solution in just 1 or 2 sentences.",
            "Could you please describe your problem?"
        )
        
        await capability.give_advice()
        
        # Should complete the flow
        spoken = " ".join(mock_cap_worker.get_spoken_messages())
        assert "goodbye" in spoken.lower()
        
    @pytest.mark.asyncio
    async def test_very_long_problem(self):
        """Test handling of very long problem descriptions."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            BasicAdvisorCapability
        )
        
        # Very long problem
        long_problem = "I have been struggling with " + "many issues " * 50
        mock_cap_worker.set_user_responses([long_problem, "yes"])
        mock_cap_worker.set_llm_response(
            f"The user has the following problem: {long_problem}. Provide a helpful solution in just 1 or 2 sentences.",
            "That's complex. Let's break it down into smaller steps."
        )
        
        await capability.give_advice()
        
        # Should handle gracefully
        assert_spoke(mock_cap_worker, "thank you")


class TestBasicAdvisorConfig:
    """Test configuration and registration."""
    
    def test_capability_registration(self):
        """Test that capability registers correctly."""
        capability = BasicAdvisorCapability.register_capability()
        
        assert capability is not None
        assert hasattr(capability, 'unique_name')
        assert hasattr(capability, 'matching_hotwords')
        assert capability.unique_name == "basic-advisor"
        
    def test_matching_hotwords_exist(self):
        """Test that matching hotwords are configured."""
        capability = BasicAdvisorCapability.register_capability()
        
        assert len(capability.matching_hotwords) > 0
        # Should include advice-related keywords
        hotwords_lower = [hw.lower() for hw in capability.matching_hotwords]
        assert any("advice" in hw or "advisor" in hw or "help" in hw 
                   for hw in hotwords_lower)
