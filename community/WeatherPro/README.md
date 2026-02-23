This is a basic capability template.
# 🌤️ Weather Master Ability

A professional, voice-first weather application for OpenHome that provides real-time weather data, forecasts, and intelligent recommendations.

## 📋 Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage Guide](#usage-guide)
- [Voice Commands](#voice-commands)
- [API Requirements](#api-requirements)
- [Technical Details](#technical-details)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## 🎯 Overview

Weather Master is a comprehensive weather ability designed specifically for voice interaction on OpenHome devices. Unlike simple weather queries that the base LLM can handle, this ability provides:

- **Real-time API data** from WeatherAPI.com
- **Persistent user preferences** across sessions
- **Multi-day and hourly forecasts**
- **Smart, context-aware recommendations**
- **Favorite locations management**
- **Customizable temperature units**

---

## ✨ Features

### Phase 1: Core Features
✅ **Smart Recommendations**
- Rain alerts with umbrella reminders
- Temperature-based clothing suggestions
- UV index warnings with sunscreen reminders
- Wind and visibility alerts
- Context-aware advice based on conditions

✅ **Sunrise/Sunset Times**
- Daily sun times for any location
- 12-hour format for natural voice playback
- Available for home and other cities

✅ **Temperature Unit Preference**
- Celsius or Fahrenheit
- Persistent across sessions
- Automatic conversion for all temperatures

### Phase 2: Advanced Features
✅ **3-Day Forecast**
- Today, tomorrow, and day after tomorrow
- High/low temperatures
- Weather conditions for each day
- Voice-optimized brief format

✅ **Favorite Locations**
- Save up to 5 favorite cities
- Quick weather check for all favorites
- Add/remove/list management
- Persistent storage

✅ **Hourly Forecast**
- Next 3-6 hours of weather
- Temperature and conditions per hour
- 12-hour time format
- Smart current-time detection

---

## 🚀 Installation

### Prerequisites
- OpenHome device or app
- Python 3.8+
- WeatherAPI.com account (free tier works)

### Steps

1. **Get Your API Key**
```
   Sign up at: https://www.weatherapi.com/signup.aspx
   Copy your free API key
```

2. **Install the Ability**
   - Upload `weather_master_ability.py` to your OpenHome abilities folder
   - Upload `config.json` to the same directory

3. **Configure API Key**
```python
   # In weather_master_ability.py, replace:
   WEATHER_API_KEY: ClassVar[str] = "REPLACE_WITH_YOUR_KEY"
   
   # With your actual key:
   WEATHER_API_KEY: ClassVar[str] = "your_actual_api_key_here"
```

4. **Deploy**
   - Restart your OpenHome device
   - The ability will be available via the trigger words in `config.json`

---

## ⚙️ Configuration

### config.json
```json
{
    "unique_name": "weather pro",
    "matching_hotwords": [
        "weather",
        "check weather",
        "weather forecast"
    ]
}
```

**Customization:**
- `unique_name`: Internal identifier for the ability
- `matching_hotwords`: Trigger phrases (add your preferred phrases)

### Preferences Storage

The ability automatically creates and manages `weather_preferences.json`:
```json
{
    "home_city": "Paris",
    "temp_unit": "celsius",
    "favorites": ["London", "Tokyo", "New York"]
}
```

This file persists across sessions and stores:
- Home location
- Temperature unit preference (celsius/fahrenheit)
- List of favorite cities (max 5)

---

## 📖 Usage Guide

### First Time Setup

**Step 1: Trigger the Ability**
```
User: "Weather"
App: "Ready."
App: "Welcome! Let's set up your weather preferences."
```

**Step 2: Choose Temperature Unit**
```
App: "Do you prefer Celsius or Fahrenheit?"
User: "Celsius"
App: "Celsius selected."
```

**Step 3: Set Home Location**
```
App: "Now let's set your home location."
App: "Which city should be your home?"
User: "Paris"
App: "Paris set as home."
```

### Daily Usage

**Check Home Weather**
```
User: "Weather"
App: "Ready."
App: "Your home is Paris."
App: "Paris. 7 degrees Celsius and partly cloudy. 89 percent chance of rain. Bring an umbrella and wear a jacket."
```

**Get 3-Day Forecast**
```
App: "Want the 3-day forecast?"
User: "Yes"
App: "Today: high 10, low 5, partly cloudy. Tomorrow: high 12, low 6, sunny. Day after tomorrow: high 9, low 4, rainy."
```

**Get Hourly Forecast**
```
App: "Want the hourly forecast?"
User: "Yes"
App: "At 2:00 PM: 8 and cloudy. At 3:00 PM: 9 and partly cloudy. At 4:00 PM: 7 and rainy."
```

**Check Other Cities**
```
App: "Do you want to check other areas?"
User: "Yes"
App: "Which area?"
User: "London"
App: "London. 8 degrees Celsius and rainy. High 10, low 5. Bring an umbrella."
```

### Managing Favorites

**Add to Favorites**
```
// After checking a city:
App: "Add London to favorites?"
User: "Yes"
App: "London added to favorites."
```

**Manage Favorites via Settings**
```
App: "Do you want to change settings or manage favorites?"
User: "Yes"
App: "Say home, unit, or favorites."
User: "Favorites"
App: "Say add, remove, list, or check all."
```

**Check All Favorites**
```
User: "Check all"
App: "Checking 3 favorite locations."
App: "London: 8, rainy. High 10, low 5."
App: "Tokyo: 15, sunny. High 18, low 12."
App: "New York: 5, cloudy. High 7, low 2."
```

---

## 🎤 Voice Commands

### Trigger Words
- "Weather"
- "Check weather"
- "Weather forecast"

### During Conversation

| Command | Action |
|---------|--------|
| "Yes" / "Yeah" / "Sure" | Confirm action |
| "No" / "Nope" / "Nah" | Decline action |
| "[City name]" | Check weather for that city |
| "Stop" / "Exit" / "Quit" / "Goodbye" | End session |
| "Home" | Change home location (in settings) |
| "Unit" | Change temperature unit (in settings) |
| "Favorites" | Manage favorites (in settings) |
| "Add" | Add city to favorites |
| "Remove" | Remove city from favorites |
| "List" | List all favorites |
| "Check all" | Check weather for all favorites |

---

## 🔑 API Requirements

### WeatherAPI.com

**Free Tier Includes:**
- 1,000,000 calls/month
- Current weather
- 3-day forecast
- Hourly forecast
- Astronomy (sunrise/sunset)
- Weather alerts

**API Endpoint Used:**
```
http://api.weatherapi.com/v1/forecast.json
```

**Parameters:**
- `key`: Your API key
- `q`: Location (city name)
- `days`: Forecast days (1-3)
- `aqi`: Air quality (set to no)
- `alerts`: Weather alerts (set to yes)

**Rate Limits:**
- Free tier: ~33,000 requests/day
- This ability uses ~1-5 requests per session
- Well within free limits for personal use

---

## 🛠️ Technical Details

### Architecture
```
weather_master_ability.py
├── Persistence Layer
│   ├── get_preferences()
│   └── save_preferences()
├── Weather Engine
│   ├── fetch_weather_data()
│   ├── get_smart_recommendations()
│   ├── create_current_weather_briefing()
│   ├── create_3day_forecast_briefing()
│   ├── create_hourly_forecast_briefing()
│   └── create_sun_times_briefing()
├── Favorites Management
│   ├── add_to_favorites()
│   ├── remove_from_favorites()
│   └── check_favorites_weather()
└── Main Flow
    └── run_main()
```

### Data Flow
```
User Trigger
    ↓
Load Preferences (persistent)
    ↓
Fetch Weather Data (API)
    ↓
Generate Smart Recommendations
    ↓
Create Voice Briefing
    ↓
Speak to User
    ↓
Offer Additional Options (3-day, hourly, sun times)
    ↓
Save Preferences (if changed)
```

### Key Technologies

- **Language**: Python 3.8+
- **Framework**: OpenHome Capability SDK
- **API**: WeatherAPI.com REST API
- **Storage**: JSON file-based persistence
- **Voice**: Text-to-Speech via OpenHome

---

## 👨‍💻 Development

### File Structure
```
weather_master_ability/
├── weather_master_ability.py    # Main ability code
├── config.json                   # Configuration file
├── weather_preferences.json      # Auto-generated user data
└── README.md                     # This file
```

### Adding New Features

**Example: Add Wind Speed Alert**

1. **Update `get_smart_recommendations()`:**
```python
# Add wind speed parameter
if wind_kph > 50:
    recommendations.append("very windy, avoid outdoor activities")
```

2. **Update weather data structure if needed:**
```python
# Ensure wind_kph is in the weather dict
'wind_kph': current['wind_kph']
```

3. **Test with voice:**
```
User: "Weather"
// Check if wind alert appears in recommendations
```

### Code Style

- **Voice-first**: Keep all spoken text under 2 sentences
- **Error handling**: Always wrap API calls in try/catch
- **Logging**: Use `self.worker.editor_logging_handler.info()` for debugging
- **Exit words**: Check exit words before processing any input

---

## 🐛 Troubleshooting

### Common Issues

**Issue: "Couldn't get weather for [city]"**
- **Cause**: Invalid API key or city name
- **Fix**: 
  1. Verify API key is correct
  2. Check city spelling
  3. Try with country name: "Paris France"

**Issue: "Something went wrong"**
- **Cause**: Network error or API timeout
- **Fix**:
  1. Check internet connection
  2. Verify WeatherAPI.com is accessible
  3. Check logs for detailed error

**Issue: Preferences not saving**
- **Cause**: File permission issues
- **Fix**:
  1. Check file permissions on `weather_preferences.json`
  2. Ensure ability has write access to directory

**Issue: Temperature unit not changing**
- **Cause**: Preferences file corrupted
- **Fix**:
  1. Delete `weather_preferences.json`
  2. Restart ability (will recreate file)

**Issue: Favorites not working**
- **Cause**: Maximum 5 favorites reached
- **Fix**: Remove one favorite before adding new ones

### Debug Mode

Enable detailed logging:
```python
# Add to run_main():
self.worker.editor_logging_handler.info(f"Preferences: {prefs}")
self.worker.editor_logging_handler.info(f"Weather data: {weather}")
```

View logs in OpenHome console or log file.

---

## 📝 Best Practices

### For Users

1. **Speak clearly** - Wait for app to finish before responding
2. **Use full city names** - "New York" instead of "NY"
3. **Be patient** - API calls take 1-2 seconds
4. **Say "stop" to exit** - Ends session immediately

### For Developers

1. **Keep responses short** - 1-2 sentences max
2. **Always confirm actions** - Use `run_confirmation_loop()` for changes
3. **Handle messy input** - Voice transcription isn't perfect
4. **Test with real voice** - Read responses aloud before deploying

---

## 🎯 Design Philosophy

### Voice-First Principles

**❌ Don't:**
- Dump walls of text
- Use technical jargon
- Require precise input
- Skip confirmations for actions

**✅ Do:**
- Keep responses brief (1-2 sentences)
- Use natural conversational language
- Accept varied input ("yeah", "yep", "sure")
- Always confirm before changing settings

### Why This Ability Exists

The base LLM can answer questions like "What's the weather in Paris?" using its training data, but it **cannot**:
- Fetch real-time current weather
- Access live forecasts
- Remember user preferences across sessions
- Provide location-specific alerts
- Store favorite locations

This ability **does what the LLM cannot** - it takes action, accesses live data, and persists state.

---

## 📊 Performance

### Typical Session Metrics

- **Startup time**: <1 second
- **API call latency**: 1-2 seconds
- **Total session time**: 30-60 seconds
- **API calls per session**: 1-5
- **Storage size**: <5KB

### Optimization Tips

1. **Batch favorites check** - Single loop through all favorites
2. **Cache weather data** - Reuse data within same session
3. **Limit forecast days** - Only fetch 3 days (API limit)
4. **Truncate hourly data** - Show only next 3 hours

---

## 🔮 Future Enhancements (Phase 3)

Potential features for future versions:

- **Compare Cities**: Side-by-side weather comparison
- **Travel Planning**: Multi-day weather for trip dates
- **Air Quality Index**: AQI data and health recommendations
- **Pollen Count**: Allergy alerts
- **Severe Weather Notifications**: Proactive alerts
- **Weather History**: Past week's weather trends
- **Custom Alerts**: User-defined temperature/rain thresholds
- **Multi-language Support**: Localized responses

---

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Test thoroughly with voice
4. Submit a pull request

---

## 📄 License

This project is licensed under the MIT License.

---

## 🙏 Acknowledgments

- **WeatherAPI.com** - Free weather data API
- **OpenHome** - Voice-first platform
- **Anthropic** - Claude AI assistance

---

## 📞 Support

For issues or questions:

1. Check [Troubleshooting](#troubleshooting) section
2. Review OpenHome documentation
3. Contact WeatherAPI.com support for API issues

---

## 📈 Version History

### v2.0.0 (Phase 2) - Current
- ✅ 3-day forecast
- ✅ Favorite locations management
- ✅ Hourly forecast

### v1.0.0 (Phase 1)
- ✅ Smart recommendations
- ✅ Sunrise/sunset times
- ✅ Temperature unit preference
- ✅ Persistent home location

---

## 🎉 Quick Start Example
```
User: "Weather"
App: "Ready. Your home is Paris. Paris. 7 degrees Celsius and partly cloudy. 
     89 percent chance of rain. Bring an umbrella and wear a jacket."
App: "Want the 3-day forecast?"
User: "Yes"
App: "Today: high 10, low 5, partly cloudy. Tomorrow: high 12, low 6, sunny. 
     Day after tomorrow: high 9, low 4, rainy."
App: "Want the hourly forecast?"
User: "No"
App: "Want sunrise and sunset times?"
User: "No"
App: "Do you want to change your Home"
User:"Yes"
App: "Which city for new home?"
User: "London"
App: "London is now your home"
User: "Paris. 6 degrees Celsius and patchy rain nearby."
App: "Do you want to change settings or manage favorites?"
User: "No"
App: "Do you want to check other areas?"
User: "No"
App: "Goodbye."
```

**That's it! You're now a Weather Master pro!** 🌤️

---

Made with ❤️ for OpenHome by the Weather Master Team
