"""
Sample ability configurations for testing.

These can be used as fixtures in your tests.
"""

# Weather ability config
WEATHER_CONFIG = {
    "unique_name": "weather",
    "matching_hotwords": [
        "weather",
        "forecast",
        "temperature",
        "climate",
        "how's the weather",
        "what's the weather"
    ],
    "description": "Get current weather for any city"
}

# Basic advisor config
BASIC_ADVISOR_CONFIG = {
    "unique_name": "basic-advisor",
    "matching_hotwords": [
        "advice",
        "advisor",
        "help me decide",
        "suggestion",
        "what should I do"
    ],
    "description": "Daily life advice and suggestions"
}

# Coin flipper config
COIN_FLIPPER_CONFIG = {
    "unique_name": "coin-flipper",
    "matching_hotwords": [
        "flip a coin",
        "coin toss",
        "heads or tails",
        "decide for me",
        "help me choose"
    ],
    "description": "Flip a coin or help decide between options"
}

# Generic ability config template
GENERIC_ABILITY_CONFIG = {
    "unique_name": "test-ability",
    "matching_hotwords": ["test", "example"],
    "description": "A test ability for unit testing",
    "enabled": True,
    "priority": 1
}
