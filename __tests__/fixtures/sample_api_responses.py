"""
Sample API responses for testing external integrations.

These mock responses can be used when testing abilities that call external APIs.
"""

# Weather API responses
WEATHER_SUNNY = {
    "current_weather": {
        "temperature": 75.0,
        "windspeed": 5.0,
        "winddirection": 180,
        "weathercode": 0,  # Clear sky
        "time": "2024-02-15T12:00"
    },
    "current_weather_units": {
        "temperature": "°F",
        "windspeed": "mph"
    }
}

WEATHER_RAINY = {
    "current_weather": {
        "temperature": 55.0,
        "windspeed": 15.0,
        "winddirection": 90,
        "weathercode": 61,  # Rain
        "time": "2024-02-15T12:00"
    }
}

WEATHER_SNOWY = {
    "current_weather": {
        "temperature": 28.0,
        "windspeed": 20.0,
        "winddirection": 0,
        "weathercode": 71,  # Snowfall
        "time": "2024-02-15T12:00"
    }
}

# Geocoding API responses
GEOCODE_DENVER = [{
    "lat": "39.7392358",
    "lon": "-104.990251",
    "display_name": "Denver, Denver County, Colorado, United States",
    "address": {
        "city": "Denver",
        "county": "Denver County",
        "state": "Colorado",
        "country": "United States"
    }
}]

GEOCODE_NEW_YORK = [{
    "lat": "40.7127753",
    "lon": "-74.0059728",
    "display_name": "New York, New York, United States",
    "address": {
        "city": "New York",
        "state": "New York",
        "country": "United States"
    }
}]

GEOCODE_LONDON = [{
    "lat": "51.5074456",
    "lon": "-0.1277653",
    "display_name": "London, Greater London, England, United Kingdom",
    "address": {
        "city": "London",
        "state": "Greater London",
        "country": "United Kingdom"
    }
}]

GEOCODE_NOT_FOUND = []  # Empty array means location not found

# Generic success/error responses
API_SUCCESS = {
    "status": "success",
    "data": {
        "result": "test data"
    }
}

API_ERROR = {
    "status": "error",
    "error": {
        "code": 500,
        "message": "Internal server error"
    }
}

API_TIMEOUT = {
    "error": "Request timeout"
}

API_RATE_LIMIT = {
    "error": "Rate limit exceeded",
    "retry_after": 60
}

# LLM-like text responses
LLM_RESPONSES = {
    "advice_simple": "Try breaking the problem down into smaller, manageable steps.",
    "advice_detailed": "Here's what I suggest: First, list out all your options. Then, evaluate the pros and cons of each. Finally, trust your gut feeling about which choice aligns best with your values.",
    "clarification": "Could you provide more details about what you're trying to accomplish?",
    "acknowledgment": "I understand. Let me think about that for a moment."
}

# Chat/conversation responses
CONVERSATION_SAMPLES = {
    "greeting": "Hello! How can I help you today?",
    "farewell": "Goodbye! Have a great day!",
    "confirmation": "Got it. I'll help you with that.",
    "error": "I'm sorry, I didn't quite understand that. Could you try again?"
}
