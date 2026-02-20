"""Tests for LLM-based extraction methods in Pet Care Assistant.

Tests the 10 typed extraction methods that parse user voice input:
- _extract_pet_name_async
- _extract_species_async
- _extract_breed_async
- _extract_birthday_async
- _extract_weight_async
- _extract_allergies_async
- _extract_medications_async
- _extract_vet_name_async
- _extract_phone_number_async
- _extract_location_async

Uses mocked LLM responses to test extraction logic and edge cases.
"""

import pytest
from datetime import datetime


class TestExtractPetName:
    """Tests for _extract_pet_name_async."""

    @pytest.mark.asyncio
    async def test_simple_name(self, capability):
        """Should extract simple pet names."""
        capability.capability_worker.text_to_text_response.return_value = "Max"

        result = await capability.llm_service.extract_pet_name_async("His name is Max")

        assert result == "Max"

    @pytest.mark.asyncio
    async def test_name_with_title(self, capability):
        """Should extract names with titles."""
        capability.capability_worker.text_to_text_response.return_value = "Princess Luna"

        result = await capability.llm_service.extract_pet_name_async("She's called Princess Luna")

        assert result == "Princess Luna"

    @pytest.mark.asyncio
    async def test_name_with_extra_words(self, capability):
        """Should extract name from verbose input."""
        capability.capability_worker.text_to_text_response.return_value = "Buddy"

        result = await capability.llm_service.extract_pet_name_async(
            "Well, we named him Buddy after my grandfather"
        )

        assert result == "Buddy"

    @pytest.mark.asyncio
    async def test_empty_input(self, capability):
        """Should handle empty input gracefully."""
        capability.capability_worker.text_to_text_response.side_effect = Exception("LLM error")

        result = await capability.llm_service.extract_pet_name_async("")

        assert result == ""

    @pytest.mark.asyncio
    async def test_llm_failure_returns_raw_input(self, capability):
        """Should return raw input if LLM fails."""
        capability.capability_worker.text_to_text_response.side_effect = Exception("LLM error")

        result = await capability.llm_service.extract_pet_name_async("Max")

        assert result == "Max"


class TestExtractSpecies:
    """Tests for _extract_species_async."""

    @pytest.mark.asyncio
    async def test_dog(self, capability):
        """Should extract 'dog' species."""
        capability.capability_worker.text_to_text_response.return_value = "dog"

        result = await capability.llm_service.extract_species_async("He's a golden retriever")

        assert result == "dog"

    @pytest.mark.asyncio
    async def test_cat(self, capability):
        """Should extract 'cat' species."""
        capability.capability_worker.text_to_text_response.return_value = "cat"

        result = await capability.llm_service.extract_species_async("She's a Maine Coon cat")

        assert result == "cat"

    @pytest.mark.asyncio
    async def test_exotic_species(self, capability):
        """Should extract exotic species."""
        capability.capability_worker.text_to_text_response.return_value = "rabbit"

        result = await capability.llm_service.extract_species_async("A Holland Lop rabbit")

        assert result == "rabbit"

    @pytest.mark.asyncio
    async def test_species_with_breed(self, capability):
        """Should extract species when breed is mentioned."""
        capability.capability_worker.text_to_text_response.return_value = "dog"

        result = await capability.llm_service.extract_species_async("German Shepherd dog")

        assert result == "dog"

    @pytest.mark.asyncio
    async def test_unclear_species(self, capability):
        """Should handle unclear species input."""
        capability.capability_worker.text_to_text_response.return_value = "dog"

        result = await capability.llm_service.extract_species_async("Just a regular pet")

        assert result == "dog"


class TestExtractBreed:
    """Tests for _extract_breed_async."""

    @pytest.mark.asyncio
    async def test_pure_breed(self, capability):
        """Should extract pure breed names."""
        capability.capability_worker.text_to_text_response.return_value = "golden retriever"

        result = await capability.llm_service.extract_breed_async("Golden Retriever")

        assert result == "golden retriever"

    @pytest.mark.asyncio
    async def test_mixed_breed(self, capability):
        """Should return 'mixed' for mixed breeds."""
        capability.capability_worker.text_to_text_response.return_value = "mixed"

        result = await capability.llm_service.extract_breed_async("He's a mutt")

        assert result == "mixed"

    @pytest.mark.asyncio
    async def test_unknown_breed(self, capability):
        """Should return 'mixed' when breed unknown."""
        capability.capability_worker.text_to_text_response.return_value = "mixed"

        result = await capability.llm_service.extract_breed_async("I don't know the breed")

        assert result == "mixed"

    @pytest.mark.asyncio
    async def test_hyphenated_breed(self, capability):
        """Should handle hyphenated breed names."""
        capability.capability_worker.text_to_text_response.return_value = "French Bulldog"

        result = await capability.llm_service.extract_breed_async("French-Bulldog")

        assert result == "French Bulldog"


class TestExtractBirthday:
    """Tests for _extract_birthday_async."""

    @pytest.mark.asyncio
    async def test_exact_date(self, capability):
        """Should extract exact birth dates."""
        capability.capability_worker.text_to_text_response.return_value = "2020-06-15"

        result = await capability.llm_service.extract_birthday_async("Born on June 15, 2020")

        assert result == "2020-06-15"

    @pytest.mark.asyncio
    async def test_age_calculation(self, capability):
        """Should calculate birthday from age."""
        # Mock to return a calculated date
        current_year = datetime.now().year
        expected_year = current_year - 3
        capability.capability_worker.text_to_text_response.return_value = f"{expected_year}-01-01"

        result = await capability.llm_service.extract_birthday_async("3 years old")

        assert result.startswith(str(expected_year))

    @pytest.mark.asyncio
    async def test_approximate_year(self, capability):
        """Should handle approximate year."""
        capability.capability_worker.text_to_text_response.return_value = "2019-01-01"

        result = await capability.llm_service.extract_birthday_async("Born in 2019")

        assert result.startswith("2019")

    @pytest.mark.asyncio
    async def test_recent_birth(self, capability):
        """Should handle recent births."""
        capability.capability_worker.text_to_text_response.return_value = "2025-12-01"

        result = await capability.llm_service.extract_birthday_async("Just got him last month")

        assert "2025" in result


class TestExtractWeight:
    """Tests for _extract_weight_async."""

    @pytest.mark.asyncio
    async def test_weight_in_pounds(self, capability):
        """Should extract weight in pounds."""
        capability.capability_worker.text_to_text_response.return_value = "55"

        result = await capability.llm_service.extract_weight_async("55 pounds")

        assert result == "55"

    @pytest.mark.asyncio
    async def test_weight_in_kilos(self, capability):
        """Should convert kilos to pounds."""
        capability.capability_worker.text_to_text_response.return_value = "55"  # 25 kg ≈ 55 lbs

        result = await capability.llm_service.extract_weight_async("25 kilograms")

        assert result == "55"

    @pytest.mark.asyncio
    async def test_weight_with_lbs_abbreviation(self, capability):
        """Should handle 'lbs' abbreviation."""
        capability.capability_worker.text_to_text_response.return_value = "70"

        result = await capability.llm_service.extract_weight_async("70 lbs")

        assert result == "70"

    @pytest.mark.asyncio
    async def test_decimal_weight(self, capability):
        """Should handle decimal weights."""
        capability.capability_worker.text_to_text_response.return_value = "12.5"

        result = await capability.llm_service.extract_weight_async("12.5 pounds")

        assert result == "12.5"

    @pytest.mark.asyncio
    async def test_approximate_weight(self, capability):
        """Should handle approximate weights."""
        capability.capability_worker.text_to_text_response.return_value = "60"

        result = await capability.llm_service.extract_weight_async("around 60 pounds")

        assert result == "60"


class TestExtractAllergies:
    """Tests for _extract_allergies_async."""

    @pytest.mark.asyncio
    async def test_single_allergy(self, capability):
        """Should extract single allergy as JSON array."""
        capability.capability_worker.text_to_text_response.return_value = '["chicken"]'

        result = await capability.llm_service.extract_allergies_async("Allergic to chicken")

        assert result == '["chicken"]'

    @pytest.mark.asyncio
    async def test_multiple_allergies(self, capability):
        """Should extract multiple allergies."""
        capability.capability_worker.text_to_text_response.return_value = '["chicken", "grain"]'

        result = await capability.llm_service.extract_allergies_async("Allergic to chicken and grain")

        assert result == '["chicken", "grain"]'

    @pytest.mark.asyncio
    async def test_no_allergies(self, capability):
        """Should return empty array for no allergies."""
        capability.capability_worker.text_to_text_response.return_value = '[]'

        result = await capability.llm_service.extract_allergies_async("No allergies")

        assert result == '[]'

    @pytest.mark.asyncio
    async def test_allergy_with_description(self, capability):
        """Should extract allergy from detailed description."""
        capability.capability_worker.text_to_text_response.return_value = '["beef"]'

        result = await capability.llm_service.extract_allergies_async(
            "Gets really itchy when eating beef"
        )

        assert result == '["beef"]'


class TestExtractMedications:
    """Tests for _extract_medications_async."""

    @pytest.mark.asyncio
    async def test_single_medication(self, capability):
        """Should extract single medication with frequency."""
        capability.capability_worker.text_to_text_response.return_value = (
            '[{"name": "Heartgard", "frequency": "monthly"}]'
        )

        result = await capability.llm_service.extract_medications_async("Takes Heartgard monthly")

        assert result == '[{"name": "Heartgard", "frequency": "monthly"}]'

    @pytest.mark.asyncio
    async def test_multiple_medications(self, capability):
        """Should extract multiple medications."""
        capability.capability_worker.text_to_text_response.return_value = (
            '[{"name": "Heartgard", "frequency": "monthly"}, '
            '{"name": "Apoquel", "frequency": "daily"}]'
        )

        result = await capability.llm_service.extract_medications_async(
            "Takes Heartgard monthly and Apoquel daily"
        )

        assert "Heartgard" in result
        assert "Apoquel" in result

    @pytest.mark.asyncio
    async def test_no_medications(self, capability):
        """Should return empty array for no medications."""
        capability.capability_worker.text_to_text_response.return_value = '[]'

        result = await capability.llm_service.extract_medications_async("Not on any medications")

        assert result == '[]'

    @pytest.mark.asyncio
    async def test_medication_without_frequency(self, capability):
        """Should handle medication without explicit frequency."""
        capability.capability_worker.text_to_text_response.return_value = (
            '[{"name": "Prednisone", "frequency": "as needed"}]'
        )

        result = await capability.llm_service.extract_medications_async("Takes Prednisone sometimes")

        assert "Prednisone" in result


class TestExtractVetName:
    """Tests for _extract_vet_name_async."""

    @pytest.mark.asyncio
    async def test_vet_with_title(self, capability):
        """Should extract vet name with title."""
        capability.capability_worker.text_to_text_response.return_value = "Dr. Smith"

        result = await capability.llm_service.extract_vet_name_async("Dr. Smith at Austin Vet")

        assert result == "Dr. Smith"

    @pytest.mark.asyncio
    async def test_vet_without_title(self, capability):
        """Should extract vet name without title."""
        capability.capability_worker.text_to_text_response.return_value = "John Smith"

        result = await capability.llm_service.extract_vet_name_async("John Smith")

        assert result == "John Smith"

    @pytest.mark.asyncio
    async def test_clinic_name(self, capability):
        """Should extract clinic name when that's what user provides."""
        capability.capability_worker.text_to_text_response.return_value = "Austin Veterinary Clinic"

        result = await capability.llm_service.extract_vet_name_async("Austin Veterinary Clinic")

        assert result == "Austin Veterinary Clinic"

    @pytest.mark.asyncio
    async def test_vet_with_clinic(self, capability):
        """Should extract vet name from verbose input."""
        capability.capability_worker.text_to_text_response.return_value = "Dr. Johnson"

        result = await capability.llm_service.extract_vet_name_async(
            "We go to Dr. Johnson at the North Austin Animal Hospital"
        )

        assert result == "Dr. Johnson"


class TestExtractPhoneNumber:
    """Tests for _extract_phone_number_async."""

    @pytest.mark.asyncio
    async def test_formatted_phone(self, capability):
        """Should extract digits from formatted phone."""
        capability.capability_worker.text_to_text_response.return_value = "5125551234"

        result = await capability.llm_service.extract_phone_number_async("(512) 555-1234")

        assert result == "5125551234"

    @pytest.mark.asyncio
    async def test_phone_with_spaces(self, capability):
        """Should extract digits from phone with spaces."""
        capability.capability_worker.text_to_text_response.return_value = "5125551234"

        result = await capability.llm_service.extract_phone_number_async("512 555 1234")

        assert result == "5125551234"

    @pytest.mark.asyncio
    async def test_phone_with_dots(self, capability):
        """Should extract digits from phone with dots."""
        capability.capability_worker.text_to_text_response.return_value = "5125551234"

        result = await capability.llm_service.extract_phone_number_async("512.555.1234")

        assert result == "5125551234"

    @pytest.mark.asyncio
    async def test_phone_with_country_code(self, capability):
        """Should extract phone with country code."""
        capability.capability_worker.text_to_text_response.return_value = "15125551234"

        result = await capability.llm_service.extract_phone_number_async("+1 512-555-1234")

        assert result == "15125551234"


class TestExtractLocation:
    """Tests for _extract_location_async."""

    @pytest.mark.asyncio
    async def test_city_state(self, capability):
        """Should extract city and state."""
        capability.capability_worker.text_to_text_response.return_value = "Austin, Texas"

        result = await capability.llm_service.extract_location_async("I live in Austin, Texas")

        assert result == "Austin, Texas"

    @pytest.mark.asyncio
    async def test_city_only(self, capability):
        """Should handle city only input."""
        capability.capability_worker.text_to_text_response.return_value = "Austin, TX"

        result = await capability.llm_service.extract_location_async("Austin")

        assert "Austin" in result

    @pytest.mark.asyncio
    async def test_city_country(self, capability):
        """Should extract city and country."""
        capability.capability_worker.text_to_text_response.return_value = "London, UK"

        result = await capability.llm_service.extract_location_async("London, United Kingdom")

        assert result == "London, UK"

    @pytest.mark.asyncio
    async def test_verbose_location(self, capability):
        """Should extract location from verbose input."""
        capability.capability_worker.text_to_text_response.return_value = "Seattle, Washington"

        result = await capability.llm_service.extract_location_async(
            "We're based out of Seattle in Washington state"
        )

        assert result == "Seattle, Washington"


class TestExtractionEdgeCases:
    """Tests for edge cases across all extraction methods."""

    @pytest.mark.asyncio
    async def test_none_input_pet_name(self, capability):
        """Should handle None input gracefully."""
        capability.capability_worker.text_to_text_response.side_effect = Exception("LLM error")

        result = await capability.llm_service.extract_pet_name_async(None)

        assert result == ""

    @pytest.mark.asyncio
    async def test_very_long_input(self, capability):
        """Should handle very long inputs."""
        capability.capability_worker.text_to_text_response.return_value = "Buddy"

        long_input = "Well, " * 100 + "his name is Buddy"
        result = await capability.llm_service.extract_pet_name_async(long_input)

        assert result == "Buddy"

    @pytest.mark.asyncio
    async def test_special_characters_in_input(self, capability):
        """Should handle special characters."""
        capability.capability_worker.text_to_text_response.return_value = "Mr. Whiskers"

        result = await capability.llm_service.extract_pet_name_async("His name is Mr. Whiskers!!!")

        assert result == "Mr. Whiskers"

    @pytest.mark.asyncio
    async def test_unicode_in_input(self, capability):
        """Should handle unicode characters."""
        capability.capability_worker.text_to_text_response.return_value = "Amélie"

        result = await capability.llm_service.extract_pet_name_async("Her name is Amélie 🐱")

        assert result == "Amélie"


# Run these tests with: pytest tests/test_llm_extraction.py -v
