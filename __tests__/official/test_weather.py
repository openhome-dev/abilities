"""
Tests for Weather Ability

Tests the weather ability, including:
- API integration (geocoding and weather)
- Location parsing and handling
- Error handling for invalid locations
- Response formatting
"""

import pytest
import sys
import os
from unittest.mock import patch, MagicMock, AsyncMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from __tests__.utils import (
    MockAgentWorker,
    MockCapabilityWorker,
    create_mock_worker_with_capability,
    assert_spoke,
    MockHTTPResponse
)


# Import the ability
try:
    from official.weather.main import WeatherCapability
except ImportError:
    pytest.skip("Weather capability not available", allow_module_level=True)


class TestWeatherBasicFlow:
    """Test basic weather query flow."""
    
    @pytest.mark.asyncio
    async def test_successful_weather_query(self):
        """Test successful weather query for a valid city."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            WeatherCapability
        )
        
        # User asks for weather in Denver
        mock_cap_worker.set_user_responses(["Denver"])
        
        # Mock geocoding API response
        mock_geocode_response = MockHTTPResponse([{
            "lat": "39.7392",
            "lon": "-104.9903",
            "display_name": "Denver, Colorado, USA"
        }])
        
        # Mock weather API response
        mock_weather_response = MockHTTPResponse({
            "current_weather": {
                "temperature": 72.0,
                "windspeed": 5.0,
                "weathercode": 0
            }
        })
        
        with patch('requests.get') as mock_get:
            # Configure mock to return different responses based on URL
            def mock_get_side_effect(url, **kwargs):
                if "nominatim" in url:
                    return mock_geocode_response
                elif "open-meteo" in url:
                    return mock_weather_response
                return MockHTTPResponse({})
            
            mock_get.side_effect = mock_get_side_effect
            
            await capability.get_weather()
            
        # Should ask for location
        assert_spoke(mock_cap_worker, "city", "weather")
        
        # Should confirm the location
        assert_spoke(mock_cap_worker, "checking", "denver")
        
        # Should report weather details (temperature, conditions, etc.)
        spoken = " ".join(mock_cap_worker.get_spoken_messages()).lower()
        assert "72" in spoken or "temperature" in spoken
        
    @pytest.mark.asyncio
    async def test_asks_for_location(self):
        """Test that ability asks for location when called."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            WeatherCapability
        )
        
        mock_cap_worker.set_user_responses(["Seattle"])
        
        with patch('requests.get', return_value=MockHTTPResponse([])):
            await capability.get_weather()
        
        # First message should ask for city
        first_message = mock_cap_worker.get_spoken_messages()[0]
        assert "city" in first_message.lower() or "location" in first_message.lower()


class TestWeatherAPIIntegration:
    """Test external API integrations."""
    
    @pytest.mark.asyncio
    async def test_geocoding_api_called_correctly(self):
        """Test that geocoding API is called with correct parameters."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            WeatherCapability
        )
        
        location = "San Francisco"
        mock_cap_worker.set_user_responses([location])
        
        mock_geocode_response = MockHTTPResponse([{
            "lat": "37.7749",
            "lon": "-122.4194",
            "display_name": "San Francisco, CA"
        }])
        
        mock_weather_response = MockHTTPResponse({
            "current_weather": {
                "temperature": 65.0,
                "windspeed": 10.0,
                "weathercode": 1
            }
        })
        
        with patch('requests.get') as mock_get:
            def mock_get_side_effect(url, **kwargs):
                if "nominatim" in url:
                    # Verify location is in the request
                    assert location.lower() in url.lower() or \
                           (kwargs.get('params') and location.lower() in str(kwargs['params']).lower())
                    return mock_geocode_response
                elif "open-meteo" in url:
                    return mock_weather_response
                return MockHTTPResponse({})
            
            mock_get.side_effect = mock_get_side_effect
            await capability.get_weather()
            
        # Should have made API calls
        assert mock_get.call_count >= 1
        
    @pytest.mark.asyncio
    async def test_weather_api_called_with_coordinates(self):
        """Test that weather API is called with geocoded coordinates."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            WeatherCapability
        )
        
        mock_cap_worker.set_user_responses(["Boston"])
        
        lat, lon = "42.3601", "-71.0589"
        mock_geocode_response = MockHTTPResponse([{
            "lat": lat,
            "lon": lon,
            "display_name": "Boston, MA"
        }])
        
        mock_weather_response = MockHTTPResponse({
            "current_weather": {
                "temperature": 55.0,
                "windspeed": 8.0,
                "weathercode": 2
            }
        })
        
        with patch('requests.get') as mock_get:
            def mock_get_side_effect(url, **kwargs):
                if "nominatim" in url:
                    return mock_geocode_response
                elif "open-meteo" in url:
                    # Verify coordinates are in the request
                    url_str = str(url) + str(kwargs.get('params', ''))
                    assert lat in url_str and lon in url_str
                    return mock_weather_response
                return MockHTTPResponse({})
            
            mock_get.side_effect = mock_get_side_effect
            await capability.get_weather()


class TestWeatherErrorHandling:
    """Test error handling for various failure scenarios."""
    
    @pytest.mark.asyncio
    async def test_invalid_location(self):
        """Test handling of invalid/unknown location."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            WeatherCapability
        )
        
        mock_cap_worker.set_user_responses(["Xyzabc123NonexistentCity"])
        
        # Geocoding returns empty array for unknown location
        with patch('requests.get', return_value=MockHTTPResponse([])):
            await capability.get_weather()
        
        # Should handle gracefully
        spoken = " ".join(mock_cap_worker.get_spoken_messages()).lower()
        assert any(word in spoken for word in ["sorry", "couldn't", "find", "error"])
        
    @pytest.mark.asyncio
    async def test_no_location_provided(self):
        """Test handling when user provides no location."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            WeatherCapability
        )
        
        # User provides empty response
        mock_cap_worker.set_user_responses([None])
        
        await capability.get_weather()
        
        # Should handle gracefully
        assert_spoke(mock_cap_worker, "didn't catch", "try again")
        
    @pytest.mark.asyncio
    async def test_api_timeout(self):
        """Test handling of API timeout."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            WeatherCapability
        )
        
        mock_cap_worker.set_user_responses(["Chicago"])
        
        # Mock API timeout
        with patch('requests.get', side_effect=Exception("Connection timeout")):
            await capability.get_weather()
        
        # Should report error gracefully
        spoken = " ".join(mock_cap_worker.get_spoken_messages()).lower()
        assert "sorry" in spoken or "error" in spoken or "problem" in spoken
        
    @pytest.mark.asyncio
    async def test_malformed_api_response(self):
        """Test handling of malformed API response."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            WeatherCapability
        )
        
        mock_cap_worker.set_user_responses(["Miami"])
        
        # Return malformed response (missing required fields)
        mock_response = MockHTTPResponse({"unexpected": "format"})
        
        with patch('requests.get', return_value=mock_response):
            await capability.get_weather()
        
        # Should handle gracefully
        spoken = " ".join(mock_cap_worker.get_spoken_messages()).lower()
        # Either reports error or handles missing data
        assert len(spoken) > 0


class TestWeatherResponseFormatting:
    """Test weather response formatting."""
    
    @pytest.mark.asyncio
    async def test_temperature_included_in_response(self):
        """Test that temperature is mentioned in the response."""
        mock_worker, mock_cap_worker, capability = create_mock_worker_with_capability(
            WeatherCapability
        )
        
        mock_cap_worker.set_user_responses(["Portland"])
        
        mock_geocode = MockHTTPResponse([{
            "lat": "45.5152",
            "lon": "-122.6784",
            "display_name": "Portland, OR"
        }])
        
        temp = 68.5
        mock_weather = MockHTTPResponse({
            "current_weather": {
                "temperature": temp,
                "windspeed": 7.0,
                "weathercode": 0
            }
        })
        
        with patch('requests.get') as mock_get:
            def side_effect(url, **kwargs):
                if "nominatim" in url:
                    return mock_geocode
                return mock_weather
            mock_get.side_effect = side_effect
            
            await capability.get_weather()
        
        # Should mention the temperature
        spoken = " ".join(mock_cap_worker.get_spoken_messages())
        assert str(int(temp)) in spoken or "temperature" in spoken.lower()


class TestWeatherConfig:
    """Test configuration and registration."""
    
    def test_capability_registration(self):
        """Test that capability registers correctly."""
        capability = WeatherCapability.register_capability()
        
        assert capability is not None
        assert hasattr(capability, 'unique_name')
        assert hasattr(capability, 'matching_hotwords')
        assert capability.unique_name == "weather"
        
    def test_matching_hotwords_include_weather(self):
        """Test that matching hotwords include weather-related terms."""
        capability = WeatherCapability.register_capability()
        
        hotwords_lower = [hw.lower() for hw in capability.matching_hotwords]
        assert any("weather" in hw or "forecast" in hw or "temperature" in hw
                   for hw in hotwords_lower)
