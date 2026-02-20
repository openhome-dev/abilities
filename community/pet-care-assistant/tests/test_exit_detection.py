"""Tests for exit detection logic in Pet Care Assistant.

Tests the three-tier exit detection system:
1. Force-exit phrases (instant shutdown)
2. Exit commands (word-based matching)
3. Exit responses (exact or prefix matching)
4. LLM fallback for ambiguous inputs
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st


class TestCleanInput:
    """Test input cleaning logic."""

    def test_removes_punctuation(self):
        """Should remove all punctuation except apostrophes."""
        from llm_service import LLMService

        assert LLMService.clean_input("Stop!") == "stop"
        assert LLMService.clean_input("Done.") == "done"
        assert LLMService.clean_input("Quit???") == "quit"
        assert LLMService.clean_input("No, thanks!") == "no thanks"

    def test_preserves_apostrophes(self):
        """Should preserve apostrophes in contractions."""
        from llm_service import LLMService

        assert LLMService.clean_input("I'm done") == "i'm done"
        assert LLMService.clean_input("That's it") == "that's it"
        assert LLMService.clean_input("We're good") == "we're good"

    def test_lowercases(self):
        """Should convert all text to lowercase."""
        from llm_service import LLMService

        assert LLMService.clean_input("STOP") == "stop"
        assert LLMService.clean_input("Exit") == "exit"
        assert LLMService.clean_input("DONE") == "done"

    def test_empty_input(self):
        """Should handle empty strings."""
        from llm_service import LLMService

        assert LLMService.clean_input("") == ""

    def test_whitespace_only(self):
        """Should handle whitespace-only input."""
        from llm_service import LLMService

        assert LLMService.clean_input("   ") == ""
        assert LLMService.clean_input("\t\n") == ""

    def test_multiple_spaces(self):
        """Should normalize multiple spaces."""
        from llm_service import LLMService

        # Regex will remove extra spaces when punctuation is removed
        result = LLMService.clean_input("no   thanks")
        assert "no" in result and "thanks" in result

    def test_mixed_punctuation(self):
        """Should handle mixed punctuation."""
        from llm_service import LLMService

        assert LLMService.clean_input("Done, thanks!!!") == "done thanks"
        assert LLMService.clean_input("I'm done.") == "i'm done"


class TestIsExitTier1ForceExitPhrases:
    """Test Tier 1: Force-exit phrases (instant shutdown)."""

    def test_exit_petcare_exact(self, capability):
        """Should detect 'exit petcare' exactly."""
        assert capability.llm_service.is_exit("exit petcare") is True

    def test_close_petcare_exact(self, capability):
        """Should detect 'close petcare' exactly."""
        assert capability.llm_service.is_exit("close petcare") is True

    def test_shut_down_pets_exact(self, capability):
        """Should detect 'shut down pets' exactly."""
        assert capability.llm_service.is_exit("shut down pets") is True

    def test_petcare_out_exact(self, capability):
        """Should detect 'petcare out' exactly."""
        assert capability.llm_service.is_exit("petcare out") is True

    def test_force_exit_with_extra_words(self, capability):
        """Should detect force-exit phrases with extra words."""
        assert capability.llm_service.is_exit("please exit petcare now") is True
        assert capability.llm_service.is_exit("I want to close petcare") is True

    def test_force_exit_with_punctuation(self, capability):
        """Should detect force-exit phrases with punctuation."""
        assert capability.llm_service.is_exit("Exit petcare!") is True
        assert capability.llm_service.is_exit("Close petcare.") is True

    def test_force_exit_case_insensitive(self, capability):
        """Should detect force-exit phrases case-insensitively."""
        assert capability.llm_service.is_exit("EXIT PETCARE") is True
        assert capability.llm_service.is_exit("Close PetCare") is True


class TestIsExitTier2ExitCommands:
    """Test Tier 2: Exit commands (word-based matching)."""

    def test_stop_exact(self, capability):
        """Should detect 'stop' as exact word."""
        assert capability.llm_service.is_exit("stop") is True

    def test_exit_exact(self, capability):
        """Should detect 'exit' as exact word."""
        assert capability.llm_service.is_exit("exit") is True

    def test_quit_exact(self, capability):
        """Should detect 'quit' as exact word."""
        assert capability.llm_service.is_exit("quit") is True

    def test_cancel_exact(self, capability):
        """Should detect 'cancel' as exact word."""
        assert capability.llm_service.is_exit("cancel") is True

    def test_stop_in_sentence(self, capability):
        """Should detect 'stop' as word within sentence."""
        assert capability.llm_service.is_exit("I want to stop now") is True
        assert capability.llm_service.is_exit("please stop") is True

    def test_stop_not_as_substring(self, capability):
        """Should NOT detect 'stop' as substring in other words."""
        assert capability.llm_service.is_exit("stopping by later") is False
        assert capability.llm_service.is_exit("non-stop") is False

    def test_exit_commands_with_punctuation(self, capability):
        """Should detect exit commands with punctuation."""
        assert capability.llm_service.is_exit("Stop!") is True
        assert capability.llm_service.is_exit("Quit.") is True

    def test_exit_commands_case_insensitive(self, capability):
        """Should detect exit commands case-insensitively."""
        assert capability.llm_service.is_exit("STOP") is True
        assert capability.llm_service.is_exit("Exit") is True


class TestIsExitTier3ExitResponses:
    """Test Tier 3: Exit responses (exact or prefix matching)."""

    def test_no_exact(self, capability):
        """Should detect 'no' as exact match."""
        assert capability.llm_service.is_exit("no") is True

    def test_nope_exact(self, capability):
        """Should detect 'nope' as exact match."""
        assert capability.llm_service.is_exit("nope") is True

    def test_done_exact(self, capability):
        """Should detect 'done' as exact match."""
        assert capability.llm_service.is_exit("done") is True

    def test_bye_exact(self, capability):
        """Should detect 'bye' as exact match."""
        assert capability.llm_service.is_exit("bye") is True

    def test_thanks_exact(self, capability):
        """Should detect 'thanks' as exact match."""
        assert capability.llm_service.is_exit("thanks") is True

    def test_no_thanks_exact(self, capability):
        """Should detect 'no thanks' as exact match."""
        assert capability.llm_service.is_exit("no thanks") is True

    def test_nothing_else_exact(self, capability):
        """Should detect 'nothing else' as exact match."""
        assert capability.llm_service.is_exit("nothing else") is True

    def test_thats_all_exact(self, capability):
        """Should detect 'that's all' as exact match."""
        assert capability.llm_service.is_exit("that's all") is True

    def test_im_done_exact(self, capability):
        """Should detect 'i'm done' as exact match."""
        assert capability.llm_service.is_exit("i'm done") is True

    def test_no_prefix_match(self, capability):
        """Should detect 'no' as prefix match."""
        assert capability.llm_service.is_exit("no thanks") is True
        assert capability.llm_service.is_exit("No, I'm good") is True

    def test_done_prefix_match(self, capability):
        """Should detect 'done' as prefix match."""
        assert capability.llm_service.is_exit("done for now") is True

    def test_no_in_sentence_not_prefix(self, capability):
        """Should NOT detect 'no' in middle of sentence."""
        assert capability.llm_service.is_exit("I have no questions") is False
        assert capability.llm_service.is_exit("there are no issues") is False

    def test_exit_responses_with_punctuation(self, capability):
        """Should detect exit responses with punctuation."""
        assert capability.llm_service.is_exit("No!") is True
        assert capability.llm_service.is_exit("Done, thanks!") is True
        assert capability.llm_service.is_exit("Bye.") is True

    def test_exit_responses_case_insensitive(self, capability):
        """Should detect exit responses case-insensitively."""
        assert capability.llm_service.is_exit("NO") is True
        assert capability.llm_service.is_exit("Done") is True


class TestIsExitNonExitQueries:
    """Test that non-exit queries are NOT detected as exits."""

    def test_pet_care_queries(self, capability):
        """Should NOT detect normal pet care queries as exits."""
        assert capability.llm_service.is_exit("What's Luna's weight?") is False
        assert capability.llm_service.is_exit("How many walks today?") is False
        assert capability.llm_service.is_exit("When did I last feed Max?") is False

    def test_questions_with_no(self, capability):
        """Should NOT detect questions containing 'no' as exits."""
        assert capability.llm_service.is_exit("Does Luna have no allergies?") is False
        assert capability.llm_service.is_exit("Are there no vets nearby?") is False

    def test_statements_with_exit_words_as_substrings(self, capability):
        """Should NOT detect exit words as substrings."""
        assert capability.llm_service.is_exit("stopping by the vet") is False
        assert capability.llm_service.is_exit("Luna is non-stop energy") is False

    def test_ok_and_okay(self, capability):
        """Should NOT detect 'ok' or 'okay' as exits."""
        assert capability.llm_service.is_exit("ok") is False
        assert capability.llm_service.is_exit("okay") is False
        assert capability.llm_service.is_exit("OK, what's next?") is False


class TestIsExitEmptyAndWhitespace:
    """Test edge cases: empty and whitespace-only input."""

    def test_empty_string(self, capability):
        """Should return False for empty string."""
        assert capability.llm_service.is_exit("") is False

    def test_whitespace_only(self, capability):
        """Should return False for whitespace-only input."""
        assert capability.llm_service.is_exit("   ") is False
        assert capability.llm_service.is_exit("\t\n") is False

    def test_none_input(self, capability):
        """Should handle None gracefully."""
        # _is_exit checks for not text, which catches None
        assert capability.llm_service.is_exit(None) is False


class TestIsExitLLMFallback:
    """Test Tier 4: LLM fallback for ambiguous inputs."""

    def test_llm_says_yes(self, capability):
        """Should return True when LLM says user wants to exit."""
        capability.capability_worker.text_to_text_response.return_value = "yes"
        assert capability.llm_service.is_exit_llm("maybe") is True
        capability.capability_worker.text_to_text_response.assert_called_once()

    def test_llm_says_no(self, capability):
        """Should return False when LLM says user doesn't want to exit."""
        capability.capability_worker.text_to_text_response.return_value = "no"
        assert capability.llm_service.is_exit_llm("hmm") is False
        capability.capability_worker.text_to_text_response.assert_called_once()

    def test_llm_says_yes_with_extra_text(self, capability):
        """Should handle LLM response with extra text."""
        capability.capability_worker.text_to_text_response.return_value = (
            "yes, they want to exit"
        )
        assert capability.llm_service.is_exit_llm("I guess") is True

    def test_llm_failure_returns_false(self, capability):
        """Should return False (fail safe) when LLM call fails."""
        capability.capability_worker.text_to_text_response.side_effect = Exception(
            "LLM error"
        )
        assert capability.llm_service.is_exit_llm("maybe") is False

    def test_llm_prompt_structure(self, capability):
        """Should call LLM with correct prompt structure."""
        capability.capability_worker.text_to_text_response.return_value = "no"
        capability.llm_service.is_exit_llm("hmm")

        call_args = capability.capability_worker.text_to_text_response.call_args[0][0]
        assert "END the conversation" in call_args
        assert "hmm" in call_args


class TestIsExitPropertyBased:
    """Property-based tests using Hypothesis."""

    @given(st.text())
    def test_never_crashes(self, text):
        """Should never crash regardless of input."""
        from unittest.mock import MagicMock

        from llm_service import LLMService
        from main import PetCareAssistantCapability

        # Create capability with mocked dependencies inside test
        cap = PetCareAssistantCapability(unique_name="test", matching_hotwords=[])
        cap.worker = MagicMock()
        cap.worker.editor_logging_handler = MagicMock()
        cap.capability_worker = MagicMock()
        cap._geocode_cache = {}
        cap.pet_data = {}
        cap.llm_service = LLMService(cap.capability_worker, cap.worker, cap.pet_data)

        try:
            result = cap.llm_service.is_exit(text)
            assert isinstance(result, bool)
        except Exception:
            pytest.fail("_is_exit should not raise exceptions")

    @given(st.text(min_size=1, max_size=100))
    def test_clean_input_returns_string(self, text):
        """_clean_input should always return a string."""
        from llm_service import LLMService

        result = LLMService.clean_input(text)
        assert isinstance(result, str)

    @given(st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=1))
    def test_exit_detection_deterministic(self, text):
        """Exit detection should be deterministic (same input = same output)."""
        from unittest.mock import MagicMock

        from llm_service import LLMService
        from main import PetCareAssistantCapability

        # Create capability with mocked dependencies inside test
        cap = PetCareAssistantCapability(unique_name="test", matching_hotwords=[])
        cap.worker = MagicMock()
        cap.worker.editor_logging_handler = MagicMock()
        cap.capability_worker = MagicMock()
        cap._geocode_cache = {}
        cap.pet_data = {}
        cap.llm_service = LLMService(cap.capability_worker, cap.worker, cap.pet_data)

        result1 = cap.llm_service.is_exit(text)
        result2 = cap.llm_service.is_exit(text)
        assert result1 == result2


class TestIsExitIntegration:
    """Integration tests for exit detection in realistic scenarios."""

    def test_quick_mode_exit_flow(self, capability):
        """Should detect exits in quick mode follow-up."""
        # User completes main task, says "no thanks" to follow-up
        assert capability.llm_service.is_exit("no thanks") is True

    def test_full_mode_idle_exit(self, capability):
        """Should detect exits after idle timeout."""
        # User says "done" after idle warning
        assert capability.llm_service.is_exit("done") is True

    def test_onboarding_exit(self, capability):
        """Should detect exits during onboarding."""
        # User says "cancel" during onboarding
        assert capability.llm_service.is_exit("cancel") is True

    def test_multi_turn_conversation_exit(self, capability):
        """Should detect exits after multiple turns."""
        # User says "that's all" after several interactions
        assert capability.llm_service.is_exit("that's all") is True

    def test_false_positive_prevention(self, capability):
        """Should NOT false-positive on common pet care queries."""
        queries = [
            "Luna has no allergies",
            "How many walks this week?",
            "Is Max okay?",
            "What's the vet's number?",
            "Can I walk Luna today?",
        ]
        for query in queries:
            assert (
                capability.llm_service.is_exit(query) is False
            ), f"False positive on: {query}"
