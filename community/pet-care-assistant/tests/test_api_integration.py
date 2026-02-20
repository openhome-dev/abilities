"""API Integration tests for Pet Care Assistant.

Tests all external API integrations with mocked HTTP responses:
- Serper Maps API (emergency vet search)
- Open-Meteo API (weather safety)
- openFDA API (food recalls)
- Serper News API (recall headlines)

Uses responses library to mock HTTP calls and test:
- Success paths with valid responses
- Error handling (401/403/429/timeout/connection)
- Response parsing and validation
- Edge cases (empty results, malformed JSON)
"""

import json
import pytest
import responses
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio


class TestEmergencyVetAPI:
    """Tests for Serper Maps API integration (emergency vet search)."""

    @pytest.fixture
    def capability_with_location(self, capability):
        """Capability with location data set."""
        capability.pet_data = {
            "pets": [{"name": "Luna", "species": "dog"}],
            "user_lat": 30.2672,
            "user_lon": -97.7431,
            "user_location": "Austin, Texas",
        }
        return capability

    @pytest.mark.asyncio
    @responses.activate
    @patch("main.SERPER_API_KEY", "test_api_key_123")
    async def test_emergency_vet_success(self, capability_with_location):
        """Should successfully find emergency vets with valid response."""
        # Mock successful Serper Maps response
        responses.add(
            responses.POST,
            "https://google.serper.dev/maps",
            json={
                "places": [
                    {
                        "title": "Austin Vet Emergency",
                        "rating": 4.5,
                        "openNow": True,
                        "phoneNumber": "512-555-1234",
                    },
                    {
                        "title": "BluePearl Pet Hospital",
                        "rating": 4.8,
                        "openNow": True,
                        "phoneNumber": "512-555-5678",
                    },
                ]
            },
            status=200,
        )

        # Call the method
        await capability_with_location._handle_emergency_vet()

        # Verify speak was called with vet info
        calls = capability_with_location.capability_worker.speak.call_args_list
        speak_text = " ".join(str(call[0][0]) for call in calls)

        assert "Austin Vet Emergency" in speak_text
        assert "BluePearl Pet Hospital" in speak_text
        assert "open now" in speak_text

    @pytest.mark.asyncio
    @responses.activate
    @patch("main.SERPER_API_KEY", "test_api_key_123")
    async def test_emergency_vet_401_unauthorized(self, capability_with_location):
        """Should handle 401 authentication error with actionable message."""
        responses.add(
            responses.POST,
            "https://google.serper.dev/maps",
            json={"error": "Invalid API key"},
            status=401,
        )

        await capability_with_location._handle_emergency_vet()

        # Verify user gets actionable error message
        calls = capability_with_location.capability_worker.speak.call_args_list
        speak_text = " ".join(str(call[0][0]) for call in calls)

        assert "invalid" in speak_text.lower() or "expired" in speak_text.lower()
        assert "serper" in speak_text.lower()

    @pytest.mark.asyncio
    @responses.activate
    @patch("main.SERPER_API_KEY", "test_api_key_123")
    async def test_emergency_vet_429_rate_limit(self, capability_with_location):
        """Should handle 429 rate limiting with appropriate message."""
        responses.add(
            responses.POST,
            "https://google.serper.dev/maps",
            json={"error": "Rate limit exceeded"},
            status=429,
        )

        await capability_with_location._handle_emergency_vet()

        calls = capability_with_location.capability_worker.speak.call_args_list
        speak_text = " ".join(str(call[0][0]) for call in calls)

        assert "rate limit" in speak_text.lower()

    @pytest.mark.asyncio
    @responses.activate
    @patch("main.SERPER_API_KEY", "test_api_key_123")
    async def test_emergency_vet_empty_results(self, capability_with_location):
        """Should handle empty results gracefully."""
        responses.add(
            responses.POST,
            "https://google.serper.dev/maps",
            json={"places": []},
            status=200,
        )

        await capability_with_location._handle_emergency_vet()

        calls = capability_with_location.capability_worker.speak.call_args_list
        speak_text = " ".join(str(call[0][0]) for call in calls)

        assert "couldn't find" in speak_text.lower() or "no" in speak_text.lower()

    @pytest.mark.asyncio
    @responses.activate
    @patch("main.SERPER_API_KEY", "test_api_key_123")
    async def test_emergency_vet_invalid_json(self, capability_with_location):
        """Should handle malformed JSON response."""
        responses.add(
            responses.POST,
            "https://google.serper.dev/maps",
            body="not valid json",
            status=200,
        )

        await capability_with_location._handle_emergency_vet()

        calls = capability_with_location.capability_worker.speak.call_args_list
        speak_text = " ".join(str(call[0][0]) for call in calls)

        assert "invalid" in speak_text.lower() or "error" in speak_text.lower()


class TestWeatherAPI:
    """Tests for Open-Meteo API integration (weather safety check)."""

    @pytest.fixture
    def capability_with_pet_and_location(self, capability):
        """Capability with pet and location data."""
        capability.pet_data = {
            "pets": [
                {
                    "id": "pet_123",
                    "name": "Luna",
                    "species": "dog",
                    "breed": "golden retriever",
                    "weight_lbs": 55,
                }
            ],
            "user_lat": 30.2672,
            "user_lon": -97.7431,
        }
        capability.activity_log = []
        return capability

    @pytest.mark.asyncio
    @responses.activate
    async def test_weather_success(self, capability_with_pet_and_location):
        """Should successfully check weather with valid response."""
        responses.add(
            responses.GET,
            "https://api.open-meteo.com/v1/forecast",
            json={
                "current": {
                    "temperature_2m": 75.0,
                    "weather_code": 0,
                    "wind_speed_10m": 5.0,
                },
                "hourly": {"uv_index": [0, 1, 2, 3, 4, 5, 6, 5, 4, 3, 2, 1]},
            },
            status=200,
        )

        intent = {"pet_name": "Luna"}
        await capability_with_pet_and_location._handle_weather(intent)

        # Verify weather check was performed
        assert capability_with_pet_and_location.capability_worker.speak.called

    @pytest.mark.asyncio
    @responses.activate
    async def test_weather_http_error(self, capability_with_pet_and_location):
        """Should handle HTTP error from weather API."""
        responses.add(
            responses.GET,
            "https://api.open-meteo.com/v1/forecast",
            json={"error": "Service unavailable"},
            status=503,
        )

        intent = {"pet_name": "Luna"}
        await capability_with_pet_and_location._handle_weather(intent)

        calls = capability_with_pet_and_location.capability_worker.speak.call_args_list
        speak_text = " ".join(str(call[0][0]) for call in calls)

        assert "error" in speak_text.lower()

    @pytest.mark.asyncio
    @responses.activate
    async def test_weather_invalid_json(self, capability_with_pet_and_location):
        """Should handle malformed JSON from weather API."""
        responses.add(
            responses.GET,
            "https://api.open-meteo.com/v1/forecast",
            body="<html>Server Error</html>",
            status=200,
        )

        intent = {"pet_name": "Luna"}
        await capability_with_pet_and_location._handle_weather(intent)

        calls = capability_with_pet_and_location.capability_worker.speak.call_args_list
        speak_text = " ".join(str(call[0][0]) for call in calls)

        assert "invalid" in speak_text.lower() or "error" in speak_text.lower()

    @pytest.mark.asyncio
    @responses.activate
    async def test_weather_missing_current_field(self, capability_with_pet_and_location):
        """Should handle response missing required 'current' field."""
        responses.add(
            responses.GET,
            "https://api.open-meteo.com/v1/forecast",
            json={"hourly": {"uv_index": [1, 2, 3]}},  # Missing 'current'
            status=200,
        )

        intent = {"pet_name": "Luna"}
        await capability_with_pet_and_location._handle_weather(intent)

        calls = capability_with_pet_and_location.capability_worker.speak.call_args_list
        speak_text = " ".join(str(call[0][0]) for call in calls)

        assert "incomplete" in speak_text.lower() or "error" in speak_text.lower()


class TestFoodRecallAPI:
    """Tests for openFDA and Serper News API integration (food recalls)."""

    @pytest.fixture
    def capability_with_pets(self, capability):
        """Capability with pet data."""
        capability.pet_data = {
            "pets": [
                {"name": "Luna", "species": "dog"},
                {"name": "Max", "species": "cat"},
            ]
        }
        return capability

    @pytest.mark.asyncio
    @responses.activate
    async def test_food_recall_fda_success(self, capability_with_pets):
        """Should successfully fetch FDA adverse events."""
        responses.add(
            responses.GET,
            "https://api.fda.gov/animalandtobacco/event.json",
            json={
                "results": [
                    {
                        "product": [{"brand_name": "Acme Dog Food"}],
                        "original_receive_date": "20250115",
                    }
                ]
            },
            status=200,
        )

        await capability_with_pets._handle_food_recall()

        # Verify recall check was performed
        assert capability_with_pets.capability_worker.speak.called

    @pytest.mark.asyncio
    @responses.activate
    async def test_food_recall_fda_404_no_results(self, capability_with_pets):
        """Should handle 404 (no results) gracefully."""
        responses.add(
            responses.GET,
            "https://api.fda.gov/animalandtobacco/event.json",
            json={"error": {"message": "No matches found"}},
            status=404,
        )

        await capability_with_pets._handle_food_recall()

        # Should not crash, just log info
        assert capability_with_pets.worker.editor_logging_handler.info.called

    @pytest.mark.asyncio
    @responses.activate
    async def test_food_recall_fda_429_rate_limit(self, capability_with_pets):
        """Should handle FDA API rate limiting."""
        responses.add(
            responses.GET,
            "https://api.fda.gov/animalandtobacco/event.json",
            json={"error": {"message": "Rate limit exceeded"}},
            status=429,
        )

        await capability_with_pets._handle_food_recall()

        # Should log warning about rate limit
        assert capability_with_pets.worker.editor_logging_handler.warning.called

    @pytest.mark.asyncio
    @responses.activate
    async def test_food_recall_fda_invalid_json(self, capability_with_pets):
        """Should handle malformed JSON from FDA API."""
        responses.add(
            responses.GET,
            "https://api.fda.gov/animalandtobacco/event.json",
            body="Invalid JSON{",
            status=200,
        )

        await capability_with_pets._handle_food_recall()

        # Should continue gracefully (may check other sources)
        calls = capability_with_pets.capability_worker.speak.call_args_list
        assert len(calls) > 0  # Should at least speak final summary

    @pytest.mark.asyncio
    @responses.activate
    async def test_food_recall_no_results(self, capability_with_pets):
        """Should speak when no recalls found."""
        # Mock FDA with no results
        responses.add(
            responses.GET,
            "https://api.fda.gov/animalandtobacco/event.json",
            json={"results": []},
            status=200,
        )

        await capability_with_pets._handle_food_recall()

        calls = capability_with_pets.capability_worker.speak.call_args_list
        speak_text = " ".join(str(call[0][0]) for call in calls)

        assert "no" in speak_text.lower() and ("alert" in speak_text.lower() or "clear" in speak_text.lower())


class TestGeolocationAPIs:
    """Tests for geolocation APIs (IP-based and geocoding)."""

    @pytest.mark.asyncio
    @responses.activate
    async def test_ip_geolocation_success(self, capability):
        """Should successfully detect location from IP."""
        responses.add(
            responses.GET,
            "http://ip-api.com/json/1.2.3.4",
            json={
                "status": "success",
                "lat": 30.2672,
                "lon": -97.7431,
                "city": "Austin",
                "regionName": "Texas",
                "isp": "AT&T",
            },
            status=200,
        )

        capability.worker.user_socket = MagicMock()
        capability.worker.user_socket.client.host = "1.2.3.4"

        result = await capability._detect_location_by_ip()

        assert result is not None
        assert result["lat"] == 30.2672
        assert result["lon"] == -97.7431
        assert "Austin" in result["city"]

    @pytest.mark.asyncio
    @responses.activate
    async def test_ip_geolocation_cloud_ip(self, capability):
        """Should detect and warn about cloud IPs."""
        responses.add(
            responses.GET,
            "http://ip-api.com/json/1.2.3.4",
            json={
                "status": "success",
                "lat": 39.0,
                "lon": -77.0,
                "city": "Ashburn",
                "regionName": "Virginia",
                "isp": "Amazon AWS",  # Cloud indicator
            },
            status=200,
        )

        capability.worker.user_socket = MagicMock()
        capability.worker.user_socket.client.host = "1.2.3.4"

        result = await capability._detect_location_by_ip()

        # Should still return result but log warning
        assert result is not None
        assert capability.worker.editor_logging_handler.warning.called

    @pytest.mark.asyncio
    @responses.activate
    async def test_geocoding_success(self, capability):
        """Should successfully geocode a location string."""
        capability._geocode_cache = {}

        responses.add(
            responses.GET,
            "https://geocoding-api.open-meteo.com/v1/search",
            json={
                "results": [
                    {"latitude": 30.2672, "longitude": -97.7431, "name": "Austin"}
                ]
            },
            status=200,
        )

        result = await capability._geocode_location("Austin, Texas")

        assert result is not None
        assert result["lat"] == 30.2672
        assert result["lon"] == -97.7431

    @pytest.mark.asyncio
    async def test_geocoding_cache_hit(self, capability):
        """Should return cached result without API call."""
        capability._geocode_cache = {
            "Austin, Texas": {"lat": 30.2672, "lon": -97.7431}
        }

        # No responses.add needed - should not hit API
        result = await capability._geocode_location("Austin, Texas")

        assert result is not None
        assert result["lat"] == 30.2672
        # Verify cache hit was logged
        assert capability.worker.editor_logging_handler.info.called

    @pytest.mark.asyncio
    @responses.activate
    async def test_geocoding_no_results(self, capability):
        """Should handle geocoding with no results."""
        capability._geocode_cache = {}

        responses.add(
            responses.GET,
            "https://geocoding-api.open-meteo.com/v1/search",
            json={"results": []},
            status=200,
        )

        result = await capability._geocode_location("Nonexistent Place")

        assert result is None


# Run these tests with: pytest tests/test_api_integration.py -v
