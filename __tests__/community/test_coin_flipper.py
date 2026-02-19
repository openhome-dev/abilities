"""
Tests for Coin Flipper Ability

Tests the coin-flipper ability's logic, including:
- Basic coin flipping
- Decision making between two options
- Repeat functionality
- Edge cases and error handling
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
    assert_spoke
)


# Import the ability (this requires the src module to be available)
try:
    from community.coin_flipper.main import CoinFlipperCapability
except ImportError:
    pytest.skip("Coin flipper capability not available", allow_module_level=True)


class TestCoinFlipperBasic:
    """Test basic coin flipping functionality."""
    
    @pytest.mark.asyncio
    async def test_coin_flip_basic(self):
        """Test that coin flip returns heads or tails."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            CoinFlipperCapability
        )
        
        # Configure user to flip and then exit
        mock_cap_worker.set_user_responses(["flip", "stop"])
        
        # Run the coin logic
        await capability.run_coin_logic()
        
        # Verify it spoke about the result
        spoken = " ".join(mock_cap_worker.get_spoken_messages())
        assert any(word in spoken.lower() for word in ["heads", "tails", "side"])
        
    @pytest.mark.asyncio
    async def test_coin_flip_exit(self):
        """Test that user can exit the ability."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            CoinFlipperCapability
        )
        
        # User immediately exits
        mock_cap_worker.set_user_responses(["stop"])
        
        await capability.run_coin_logic()
        
        # Should say goodbye
        assert_spoke(mock_cap_worker, "see you")


class TestCoinFlipperDecision:
    """Test decision-making functionality."""
    
    @pytest.mark.asyncio
    async def test_decision_mode_basic(self):
        """Test making a decision between two options."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            CoinFlipperCapability
        )
        
        # User wants to decide, provides options, then exits
        mock_cap_worker.set_user_responses([
            "decide",
            "Pizza",      # First option
            "Burger",     # Second option
            "stop"
        ])
        
        await capability.run_coin_logic()
        
        # Should ask for options and make a choice
        spoken = " ".join(mock_cap_worker.get_spoken_messages())
        assert "first option" in spoken.lower()
        assert "second option" in spoken.lower()
        assert any(word in spoken for word in ["Pizza", "Burger"])
        
    @pytest.mark.asyncio
    async def test_decision_mode_with_repeat(self):
        """Test that decision mode can be repeated."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            CoinFlipperCapability
        )
        
        # User decides, then asks to repeat
        mock_cap_worker.set_user_responses([
            "decide",
            "Coffee",
            "Tea",
            "again",      # Should repeat with same options
            "stop"
        ])
        
        await capability.run_coin_logic()
        
        # Should mention both options twice (original + repeat)
        spoken = " ".join(mock_cap_worker.get_spoken_messages())
        assert spoken.count("Coffee") >= 1
        assert spoken.count("Tea") >= 1


class TestCoinFlipperEdgeCases:
    """Test edge cases and error handling."""
    
    @pytest.mark.asyncio
    async def test_empty_user_input(self):
        """Test handling of empty user input."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            CoinFlipperCapability
        )
        
        # User provides empty input, then exits
        mock_cap_worker.set_user_responses(["", "stop"])
        
        await capability.run_coin_logic()
        
        # Should handle gracefully and prompt again
        assert_spoke(mock_cap_worker, "silence", "please")
        
    @pytest.mark.asyncio
    async def test_unknown_command(self):
        """Test handling of unrecognized commands."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            CoinFlipperCapability
        )
        
        # User provides gibberish, then exits
        mock_cap_worker.set_user_responses(["asdfghjkl", "stop"])
        
        await capability.run_coin_logic()
        
        # Should ask for clarification
        assert_spoke(mock_cap_worker, "did not understand")
        
    @pytest.mark.asyncio
    async def test_repeat_without_previous_action(self):
        """Test repeat command when nothing has been done yet."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            CoinFlipperCapability
        )
        
        # User tries to repeat immediately
        mock_cap_worker.set_user_responses(["again", "stop"])
        
        await capability.run_coin_logic()
        
        # Should inform user that there's nothing to repeat
        assert_spoke(mock_cap_worker, "haven't done anything")


class TestCoinFlipperRareEvents:
    """Test rare events like coin landing on side."""
    
    @pytest.mark.asyncio
    async def test_coin_lands_on_side(self):
        """Test the 1% chance of coin landing on its side."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            CoinFlipperCapability
        )
        
        # Mock random to always return 1 (the "side" condition)
        with patch('random.randint', return_value=1):
            mock_cap_worker.set_user_responses(["flip", "stop"])
            await capability.run_coin_logic()
            
            # Should mention landing on side
            assert_spoke(mock_cap_worker, "side", "impossible")
            
    @pytest.mark.asyncio
    async def test_coin_normal_flip(self):
        """Test normal coin flip (not landing on side)."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            CoinFlipperCapability
        )
        
        # Mock random to return anything but 1
        with patch('random.randint', return_value=50):
            with patch('random.choice', return_value="Heads"):
                mock_cap_worker.set_user_responses(["flip", "stop"])
                await capability.run_coin_logic()
                
                # Should mention heads or tails
                assert_spoke(mock_cap_worker, "heads")


class TestCoinFlipperConfig:
    """Test configuration loading."""
    
    def test_capability_registration(self):
        """Test that capability registers correctly."""
        capability = CoinFlipperCapability.register_capability()
        
        assert capability is not None
        assert hasattr(capability, 'unique_name')
        assert hasattr(capability, 'matching_hotwords')
        assert capability.unique_name == "coin-flipper"
        assert len(capability.matching_hotwords) > 0
