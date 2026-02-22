"""Tests for _answer_inline_query — mid-onboarding pet inventory detection.

When users ask "Do you have any animals?" embedded in an onboarding answer
(e.g. mixed into their allergy response), the system should:
1. Detect the inline question.
2. Answer with the current registered pets.
3. Return True so the caller re-asks its prompt.
"""

from unittest.mock import AsyncMock

import pytest


class TestAnswerInlineQuery:
    """Tests for PetCareAssistantCapability._answer_inline_query."""

    # ── Returns False (normal answers, no inventory question) ─────────────

    @pytest.mark.asyncio
    async def test_normal_no_answer_returns_false(self, capability):
        """'No' to allergies should not trigger inline query."""
        result = await capability._answer_inline_query("No")
        assert result is False
        capability.capability_worker.speak.assert_not_called()

    @pytest.mark.asyncio
    async def test_normal_health_answer_returns_false(self, capability):
        """A real health answer should not trigger inline query."""
        result = await capability._answer_inline_query("She's allergic to chicken")
        assert result is False
        capability.capability_worker.speak.assert_not_called()

    @pytest.mark.asyncio
    async def test_weight_answer_returns_false(self, capability):
        """'48 pounds' should not trigger inline query."""
        result = await capability._answer_inline_query("48 pounds")
        assert result is False
        capability.capability_worker.speak.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_string_returns_false(self, capability):
        """Empty string should return False without speaking."""
        result = await capability._answer_inline_query("")
        assert result is False
        capability.capability_worker.speak.assert_not_called()

    @pytest.mark.asyncio
    async def test_none_returns_false(self, capability):
        """None should return False without speaking."""
        result = await capability._answer_inline_query(None)
        assert result is False
        capability.capability_worker.speak.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_returns_false(self, capability):
        """'Skip' should not trigger inline query."""
        result = await capability._answer_inline_query("skip")
        assert result is False

    # ── Returns True (inventory question detected) ─────────────────────────

    @pytest.mark.asyncio
    async def test_do_you_have_any_animal_triggers(self, capability):
        """Classic STT output: 'Do you have any animal?' triggers inline response."""
        capability.pet_data = {}
        result = await capability._answer_inline_query("Do you have any animal?")
        assert result is True
        capability.capability_worker.speak.assert_called_once()

    @pytest.mark.asyncio
    async def test_any_pets_triggers(self, capability):
        """'Any pets?' triggers inline response."""
        capability.pet_data = {}
        result = await capability._answer_inline_query("any pets registered?")
        assert result is True

    @pytest.mark.asyncio
    async def test_any_animals_triggers(self, capability):
        """'Any animals?' triggers inline response."""
        capability.pet_data = {}
        result = await capability._answer_inline_query("do you have any animals?")
        assert result is True

    @pytest.mark.asyncio
    async def test_what_pets_triggers(self, capability):
        """'What pets do I have?' triggers inline response."""
        capability.pet_data = {}
        result = await capability._answer_inline_query("what pets do I have")
        assert result is True

    @pytest.mark.asyncio
    async def test_how_many_pets_triggers(self, capability):
        """'How many pets?' triggers inline response."""
        capability.pet_data = {}
        result = await capability._answer_inline_query("how many pets are there")
        assert result is True

    @pytest.mark.asyncio
    async def test_garbled_stt_mixed_answer_triggers(self, capability):
        """Garbled STT: 'No, no. Dog dog. Do you have any animal?' triggers."""
        capability.pet_data = {}
        result = await capability._answer_inline_query(
            "Dos. No, no. Dog dog. Do you have any animal?"
        )
        assert result is True

    # ── Correct spoken response per pet count ─────────────────────────────

    @pytest.mark.asyncio
    async def test_speaks_no_pets_yet_when_empty(self, capability):
        """When no pets are set up, says we're setting one up now."""
        capability.pet_data = {}
        await capability._answer_inline_query("do you have any animal")
        spoken = capability.capability_worker.speak.call_args[0][0]
        assert "setting one up right now" in spoken.lower()

    @pytest.mark.asyncio
    async def test_speaks_one_pet_name_and_species(self, capability):
        """When one pet exists, speaks their name and species."""
        capability.pet_data = {
            "pets": [{"name": "Luna", "species": "dog", "breed": "golden retriever"}]
        }
        await capability._answer_inline_query("do you have any pets")
        spoken = capability.capability_worker.speak.call_args[0][0]
        assert "Luna" in spoken
        assert "dog" in spoken

    @pytest.mark.asyncio
    async def test_speaks_multiple_pet_names(self, capability):
        """When multiple pets exist, lists all names."""
        capability.pet_data = {
            "pets": [
                {"name": "Luna", "species": "dog"},
                {"name": "Max", "species": "cat"},
            ]
        }
        await capability._answer_inline_query("how many pets do I have")
        spoken = capability.capability_worker.speak.call_args[0][0]
        assert "Luna" in spoken
        assert "Max" in spoken
        assert "2" in spoken

    @pytest.mark.asyncio
    async def test_case_insensitive_detection(self, capability):
        """Detection should be case-insensitive."""
        capability.pet_data = {}
        result = await capability._answer_inline_query("DO YOU HAVE ANY ANIMAL?")
        assert result is True

    @pytest.mark.asyncio
    async def test_does_not_speak_twice_for_single_call(self, capability):
        """Should speak exactly once per call, even with multiple patterns in input."""
        capability.pet_data = {}
        await capability._answer_inline_query(
            "any animals any pets how many pets do you have any"
        )
        assert capability.capability_worker.speak.call_count == 1

    @pytest.mark.asyncio
    async def test_do_i_have_any_triggers(self, capability):
        """'Do I have any other I have any animal' (garbled STT) triggers."""
        capability.pet_data = {}
        result = await capability._answer_inline_query(
            "Do I have any other I have any animal I have any animal?"
        )
        assert result is True

    # ── Tier 2: LLM-based general question detection ─────────────────────

    @pytest.mark.asyncio
    async def test_short_question_words_do_not_trigger_llm(self, capability):
        """Short inputs with question words shouldn't trigger the LLM (too expensive)."""
        result = await capability._answer_inline_query("What? No.")
        assert result is False

    @pytest.mark.asyncio
    async def test_lookup_intent_triggers_handler(self, capability):
        """A question about stored pet info should be answered via _handle_lookup."""
        capability.pet_data = {
            "pets": [
                {
                    "id": "pet_abc",
                    "name": "Luna",
                    "species": "dog",
                    "breed": "golden retriever",
                    "weight_lbs": 48,
                    "birthday": "",
                    "allergies": [],
                    "medications": [],
                }
            ]
        }
        capability.activity_log = []
        # Mock the LLM classifier to return lookup intent
        capability.llm_service.classify_intent_async = AsyncMock(
            return_value={"mode": "lookup", "pet_name": "Luna", "query": "profile info"}
        )
        result = await capability._answer_inline_query(
            "Tell me about Luna's registered info"
        )
        assert result is True
        # Should have spoken Luna's profile
        capability.capability_worker.speak.assert_called()

    @pytest.mark.asyncio
    async def test_log_intent_defers_to_after_onboarding(self, capability):
        """Log intents (question-like) should be acknowledged and deferred."""
        capability.llm_service.classify_intent_async = AsyncMock(
            return_value={"mode": "log", "pet_name": "Luna", "activity_type": "feeding"}
        )
        result = await capability._answer_inline_query(
            "Can you log that I just fed Luna some food"
        )
        assert result is True
        spoken = capability.capability_worker.speak.call_args[0][0]
        assert "finish" in spoken.lower() or "continue" in spoken.lower()

    @pytest.mark.asyncio
    async def test_unknown_pet_related_defers(self, capability):
        """Unknown intent that IS pet-related should defer, returning True."""
        capability.llm_service.classify_intent_async = AsyncMock(
            return_value={"mode": "unknown"}
        )
        capability._is_pet_care_related = AsyncMock(return_value=True)
        result = await capability._answer_inline_query(
            "What food is best for puppies in winter"
        )
        assert result is True
        capability.capability_worker.speak.assert_called()

    @pytest.mark.asyncio
    async def test_unknown_unrelated_returns_false(self, capability):
        """Unknown intent that is NOT pet-related should return False."""
        capability.llm_service.classify_intent_async = AsyncMock(
            return_value={"mode": "unknown"}
        )
        capability._is_pet_care_related = AsyncMock(return_value=False)
        result = await capability._answer_inline_query(
            "What is the meaning of life and everything"
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_weather_intent_handled_inline(self, capability):
        """Weather intent should be handled inline during onboarding."""
        capability.llm_service.classify_intent_async = AsyncMock(
            return_value={"mode": "weather", "pet_name": "Luna"}
        )
        capability._handle_weather = AsyncMock()
        result = await capability._answer_inline_query(
            "Can you tell me if it is safe for Luna outside"
        )
        assert result is True
        capability._handle_weather.assert_called_once()

    @pytest.mark.asyncio
    async def test_reminder_intent_handled_inline(self, capability):
        """Reminder intent should be handled inline during onboarding."""
        capability.llm_service.classify_intent_async = AsyncMock(
            return_value={
                "mode": "reminder",
                "action": "set",
                "pet_name": "Luna",
                "activity": "feeding",
                "time_description": "in 2 hours",
            }
        )
        capability._handle_reminder = AsyncMock()
        result = await capability._answer_inline_query(
            "Can you remind me to feed Luna in two hours"
        )
        assert result is True
        capability._handle_reminder.assert_called_once()


class TestAskOnboardingStep:
    """Tests for PetCareAssistantCapability._ask_onboarding_step."""

    @pytest.mark.asyncio
    async def test_returns_normal_response(self, capability):
        """Normal answers pass through unchanged."""
        capability.capability_worker.run_io_loop = AsyncMock(return_value="48 pounds")
        result = await capability._ask_onboarding_step("How much does Luna weigh?")
        assert result == "48 pounds"

    @pytest.mark.asyncio
    async def test_returns_none_on_hard_exit(self, capability):
        """Hard exit (stop/quit) returns None."""
        capability.capability_worker.run_io_loop = AsyncMock(return_value="stop")
        result = await capability._ask_onboarding_step("How much does Luna weigh?")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_empty_string_on_empty_input(self, capability):
        """Empty user input returns empty string (not None)."""
        capability.capability_worker.run_io_loop = AsyncMock(return_value="")
        result = await capability._ask_onboarding_step("How much does Luna weigh?")
        assert result == ""

    @pytest.mark.asyncio
    async def test_reasks_after_inline_query(self, capability):
        """If user asks about pets, answer then re-ask the prompt."""
        capability.pet_data = {}
        # First call returns the inline query, second returns the real answer
        capability.capability_worker.run_io_loop = AsyncMock(
            side_effect=["do you have any animal?", "48 pounds"]
        )
        result = await capability._ask_onboarding_step("How much does Luna weigh?")
        assert result == "48 pounds"
        # Should have spoken the inline answer AND called run_io_loop twice
        capability.capability_worker.speak.assert_called_once()
        assert capability.capability_worker.run_io_loop.call_count == 2

    @pytest.mark.asyncio
    async def test_hard_exit_after_inline_query_reask(self, capability):
        """If user exits on the re-ask after inline query, returns None."""
        capability.pet_data = {}
        capability.capability_worker.run_io_loop = AsyncMock(
            side_effect=["do you have any animal?", "quit"]
        )
        result = await capability._ask_onboarding_step("How much does Luna weigh?")
        assert result is None
