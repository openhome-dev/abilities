import json
import os
from datetime import datetime
from typing import ClassVar, Optional

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker


class WeatherProCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    FILENAME: ClassVar[str] = "weather_preferences.json"
    PERSIST: ClassVar[bool] = False

    # Get your free API key at https://www.weatherapi.com/signup.aspx
    # WEATHER_API_KEY: ClassVar[str] = "your_key_here"
    WEATHER_API_KEY: ClassVar[str] = "7dd861d3c29946f6af0192344261402"

    EXIT_WORDS: ClassVar[set] = {
        "stop", "exit", "quit", "done", "cancel",
        "bye", "goodbye", "leave", "no more",
        "that's all", "finish", "end"
    }

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"]
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run_main())

    # --- PERSISTENCE HELPERS ---
    async def get_preferences(self) -> dict:
        if await self.capability_worker.check_if_file_exists(self.FILENAME, self.PERSIST):
            raw = await self.capability_worker.read_file(self.FILENAME, self.PERSIST)
            try:
                return json.loads(raw)
            except Exception:
                return {"home_city": None, "temp_unit": "celsius", "favorites": []}
        return {"home_city": None, "temp_unit": "celsius", "favorites": []}

    async def save_preferences(self, prefs: dict):
        if await self.capability_worker.check_if_file_exists(self.FILENAME, self.PERSIST):
            await self.capability_worker.delete_file(self.FILENAME, self.PERSIST)
        await self.capability_worker.write_file(
            self.FILENAME, json.dumps(prefs), self.PERSIST
        )

    # --- TEMPERATURE HELPERS ---
    def format_temperature(self, temp_c: float, unit: str) -> str:
        if unit == "fahrenheit":
            temp_f = round((temp_c * 9 / 5) + 32)
            return f"{temp_f} degrees Fahrenheit"
        return f"{round(temp_c)} degrees Celsius"

    def convert_time_to_12hr(self, time_str: str) -> str:
        try:
            time_str = time_str.strip()
            if "AM" in time_str.upper() or "PM" in time_str.upper():
                return time_str
            hour, minute = time_str.split(":")
            hour = int(hour)
            period = "AM" if hour < 12 else "PM"
            if hour == 0:
                hour = 12
            elif hour > 12:
                hour -= 12
            return f"{hour}:{minute} {period}"
        except Exception:
            return time_str

    def is_fahrenheit_response(self, text: str) -> bool:
        text_lower = text.lower().strip()
        fahrenheit_variants = {
            "fahrenheit", "farenheit", "farhenheit", "farenheight", "f"
        }
        return any(variant in text_lower for variant in fahrenheit_variants)

    # --- WEATHER ENGINE ---
    def fetch_weather_data(self, location: str, days: int = 3) -> Optional[dict]:
        try:
            url = (
                f"http://api.weatherapi.com/v1/forecast.json"
                f"?key={self.WEATHER_API_KEY}&q={location}"
                f"&days={days}&aqi=no&alerts=yes"
            )
            r = requests.get(url, timeout=10)
            data = r.json()

            if "error" in data:
                self.worker.editor_logging_handler.error(
                    f"Weather API error: {data['error']}"
                )
                return None

            current = data["current"]
            location_info = data["location"]
            alerts = data.get("alerts", {}).get("alert", [])

            forecast_days = []
            for day_data in data["forecast"]["forecastday"]:
                forecast_days.append({
                    "date": day_data["date"],
                    "high": day_data["day"]["maxtemp_c"],
                    "low": day_data["day"]["mintemp_c"],
                    "condition": day_data["day"]["condition"]["text"],
                    "rain_chance": day_data["day"]["daily_chance_of_rain"],
                    "sunrise": day_data["astro"]["sunrise"],
                    "sunset": day_data["astro"]["sunset"],
                    "hourly": day_data["hour"]
                })

            return {
                "location": location_info["name"],
                "country": location_info["country"],
                "temp": current["temp_c"],
                "feels_like": current["feelslike_c"],
                "condition": current["condition"]["text"],
                "humidity": current["humidity"],
                "wind_kph": current["wind_kph"],
                "uv_index": current["uv"],
                "visibility_km": current["vis_km"],
                "alerts": [a["headline"] for a in alerts] if alerts else [],
                "forecast_days": forecast_days
            }
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Weather fetch error: {e}")
            return None

    def get_smart_recommendations(
        self,
        temp: float,
        rain_chance: int,
        uv_index: float,
        wind_kph: float,
        visibility_km: float
    ) -> list:
        recommendations = []

        if rain_chance > 60:
            recommendations.append("bring an umbrella")
        elif rain_chance > 30:
            recommendations.append("keep an umbrella handy")

        if temp < 5:
            recommendations.append("wear a heavy coat")
        elif temp < 15:
            recommendations.append("wear a jacket")
        elif temp > 30:
            recommendations.append("stay hydrated")

        if uv_index >= 6:
            recommendations.append("wear sunscreen")
        elif uv_index >= 3:
            recommendations.append("consider sunscreen if outdoors for long")

        if wind_kph > 40:
            recommendations.append("it's windy, secure loose items")

        if visibility_km < 2:
            recommendations.append("low visibility, drive carefully")

        return recommendations

    def create_current_weather_briefing(
        self,
        weather: dict,
        temp_unit: str,
        include_recommendations: bool = True
    ) -> str:
        temp_str = self.format_temperature(weather["temp"], temp_unit)
        today = weather["forecast_days"][0]
        high_str = self.format_temperature(today["high"], temp_unit)
        low_str = self.format_temperature(today["low"], temp_unit)

        main = f"{weather['location']}. {temp_str} and {weather['condition'].lower()}."

        if weather["alerts"]:
            detail = "Weather alert active."
        elif today["rain_chance"] > 60:
            detail = f"{today['rain_chance']} percent chance of rain."
        else:
            detail = f"High {high_str.split()[0]}, low {low_str.split()[0]}."

        briefing = f"{main} {detail}"

        if include_recommendations:
            recs = self.get_smart_recommendations(
                weather["temp"],
                today["rain_chance"],
                weather["uv_index"],
                weather["wind_kph"],
                weather["visibility_km"]
            )
            if recs:
                rec_text = " and ".join(recs[:2]).capitalize() + "."
                briefing += f" {rec_text}"

        return briefing

    def create_3day_forecast_briefing(self, weather: dict, temp_unit: str) -> str:
        days = ["Today", "Tomorrow", "Day after tomorrow"]
        parts = []

        for i, day_data in enumerate(weather["forecast_days"][:3]):
            day_name = days[i] if i < len(days) else f"Day {i + 1}"
            high = self.format_temperature(day_data["high"], temp_unit).split()[0]
            low = self.format_temperature(day_data["low"], temp_unit).split()[0]
            condition = day_data["condition"].lower()
            parts.append(f"{day_name}: high {high}, low {low}, {condition}")

        return ". ".join(parts) + "."

    def create_hourly_forecast_briefing(
        self,
        weather: dict,
        temp_unit: str,
        hours_ahead: int = 6
    ) -> str:
        today = weather["forecast_days"][0]
        hourly_data = today["hourly"]
        current_hour = datetime.now().hour

        parts = []
        hours_shown = 0

        for hour_data in hourly_data:
            hour_time = hour_data["time"].split()[1]
            hour_num = int(hour_time.split(":")[0])

            if hour_num >= current_hour and hours_shown < hours_ahead:
                temp = self.format_temperature(
                    hour_data["temp_c"], temp_unit
                ).split()[0]
                condition = hour_data["condition"]["text"].lower()
                time_12hr = self.convert_time_to_12hr(hour_time)
                parts.append(f"At {time_12hr}: {temp} and {condition}")
                hours_shown += 1

        if parts:
            return ". ".join(parts[:3]) + "."
        return "Hourly forecast not available for the rest of today."

    def create_sun_times_briefing(self, weather: dict) -> str:
        today = weather["forecast_days"][0]
        sunrise = self.convert_time_to_12hr(today["sunrise"])
        sunset = self.convert_time_to_12hr(today["sunset"])
        return f"Sunrise at {sunrise}, sunset at {sunset}."

    def extract_city_from_text(self, text: str) -> Optional[str]:
        prompt = (
            f"Extract ONLY the city name from this text: '{text}'. "
            "Return just the city name, nothing else. "
            "If no city is mentioned, return exactly: NONE"
        )
        result = (
            self.capability_worker.text_to_text_response(prompt)
            .strip()
            .replace('"', "")
            .replace("'", "")
            .replace(",", "")
            .replace(".", "")
        )
        return None if result.upper() == "NONE" else result

    def is_yes_response(self, text: str) -> bool:
        text_lower = text.lower().strip()
        yes_words = {
            "yes", "yeah", "yep", "sure", "okay",
            "ok", "yup", "correct", "right", "absolutely"
        }
        return any(word in text_lower for word in yes_words)

    def is_no_response(self, text: str) -> bool:
        text_lower = text.lower().strip()
        no_words = {"no", "nope", "nah", "not", "don't", "never"}
        return any(word in text_lower for word in no_words)

    def is_exit(self, text: str) -> bool:
        return any(word in text.lower() for word in self.EXIT_WORDS)

    # --- FAVORITES MANAGEMENT ---
    async def add_to_favorites(self, city: str, prefs: dict) -> bool:
        favorites = prefs.get("favorites", [])
        if city not in favorites:
            if len(favorites) >= 5:
                await self.capability_worker.speak(
                    "You already have 5 favorites. Remove one first."
                )
                return False
            favorites.append(city)
            prefs["favorites"] = favorites
            await self.save_preferences(prefs)
            return True
        await self.capability_worker.speak(f"{city} is already in favorites.")
        return False

    async def remove_from_favorites(self, city: str, prefs: dict) -> bool:
        favorites = prefs.get("favorites", [])
        if city in favorites:
            favorites.remove(city)
            prefs["favorites"] = favorites
            await self.save_preferences(prefs)
            return True
        await self.capability_worker.speak(f"{city} is not in favorites.")
        return False

    async def check_favorites_weather(self, prefs: dict, temp_unit: str):
        favorites = prefs.get("favorites", [])
        if not favorites:
            await self.capability_worker.speak("You have no favorite locations saved.")
            return

        await self.capability_worker.speak(
            f"Checking {len(favorites)} favorite locations."
        )

        for city in favorites:
            weather = self.fetch_weather_data(city, days=1)
            if weather:
                today = weather["forecast_days"][0]
                temp = self.format_temperature(weather["temp"], temp_unit).split()[0]
                high = self.format_temperature(today["high"], temp_unit).split()[0]
                low = self.format_temperature(today["low"], temp_unit).split()[0]
                condition = weather["condition"].lower()
                briefing = f"{city}: {temp}, {condition}. High {high}, low {low}."
                await self.capability_worker.speak(briefing)
                await self.worker.session_tasks.sleep(0.1)

    # --- MAIN WEATHER APP FLOW ---
    async def run_main(self):
        try:
            await self.capability_worker.speak("Ready.")
            await self.worker.session_tasks.sleep(0.1)

            prefs = await self.get_preferences()
            home_city = prefs.get("home_city")
            temp_unit = prefs.get("temp_unit", "celsius")

            # FIRST TIME SETUP
            if not home_city:
                await self.capability_worker.speak(
                    "Welcome! Let's set up your weather preferences."
                )

                await self.worker.session_tasks.sleep(0.1)
                unit_response = await self.capability_worker.run_io_loop(
                    "Do you prefer Celsius or Fahrenheit?"
                )

                if unit_response and self.is_fahrenheit_response(unit_response):
                    temp_unit = "fahrenheit"
                    prefs["temp_unit"] = "fahrenheit"
                    await self.capability_worker.speak("Fahrenheit selected.")
                else:
                    temp_unit = "celsius"
                    prefs["temp_unit"] = "celsius"
                    await self.capability_worker.speak("Celsius selected.")

                await self.capability_worker.speak("Now let's set your home location.")

                while True:
                    await self.worker.session_tasks.sleep(0.1)
                    city_input = await self.capability_worker.run_io_loop(
                        "Which city should be your home?"
                    )

                    if not city_input:
                        await self.capability_worker.speak("Didn't catch that. Which city?")
                        continue

                    if self.is_exit(city_input):
                        await self.capability_worker.speak("Goodbye.")
                        return

                    home_city = self.extract_city_from_text(city_input)
                    if home_city:
                        test_weather = self.fetch_weather_data(home_city, days=3)
                        if test_weather:
                            prefs["home_city"] = test_weather["location"]
                            await self.save_preferences(prefs)
                            await self.capability_worker.speak(
                                f"{test_weather['location']} set as home."
                            )
                            home_city = test_weather["location"]
                            break
                        else:
                            await self.capability_worker.speak(
                                f"Couldn't find {home_city}. Try another city?"
                            )
                    else:
                        await self.capability_worker.speak("Couldn't understand. Which city?")

            # SHOW HOME WEATHER
            await self.capability_worker.speak(f"Your home is {home_city}.")

            home_weather = self.fetch_weather_data(home_city, days=3)
            if not home_weather:
                await self.capability_worker.speak(
                    f"Couldn't get weather for {home_city}."
                )
                return

            briefing = self.create_current_weather_briefing(
                home_weather, temp_unit, include_recommendations=True
            )
            await self.capability_worker.speak(briefing)

            # 3-DAY FORECAST
            await self.worker.session_tasks.sleep(0.2)
            forecast_response = await self.capability_worker.run_io_loop(
                "Want the 3-day forecast?"
            )
            if forecast_response and self.is_yes_response(forecast_response):
                await self.capability_worker.speak(
                    self.create_3day_forecast_briefing(home_weather, temp_unit)
                )

            # HOURLY FORECAST
            await self.worker.session_tasks.sleep(0.2)
            hourly_response = await self.capability_worker.run_io_loop(
                "Want the hourly forecast?"
            )
            if hourly_response and self.is_yes_response(hourly_response):
                await self.capability_worker.speak(
                    self.create_hourly_forecast_briefing(home_weather, temp_unit)
                )

            # SUNRISE / SUNSET
            await self.worker.session_tasks.sleep(0.2)
            sun_response = await self.capability_worker.run_io_loop(
                "Want sunrise and sunset times?"
            )
            if sun_response and self.is_yes_response(sun_response):
                await self.capability_worker.speak(
                    self.create_sun_times_briefing(home_weather)
                )

            # CHANGE HOME LOCATION
            await self.worker.session_tasks.sleep(0.2)
            change_home_response = await self.capability_worker.run_io_loop(
                "Do you want to change your home location?"
            )

            if change_home_response and self.is_yes_response(change_home_response):
                while True:
                    await self.worker.session_tasks.sleep(0.1)
                    new_city_input = await self.capability_worker.run_io_loop(
                        "Which city for new home?"
                    )

                    if not new_city_input:
                        await self.capability_worker.speak("Didn't catch that. Which city?")
                        continue

                    if self.is_exit(new_city_input):
                        break

                    new_home = self.extract_city_from_text(new_city_input)
                    if new_home:
                        new_home_weather = self.fetch_weather_data(new_home, days=3)
                        if new_home_weather:
                            prefs["home_city"] = new_home_weather["location"]
                            await self.save_preferences(prefs)
                            await self.capability_worker.speak(
                                f"{new_home_weather['location']} is now your home."
                            )
                            home_city = new_home_weather["location"]
                            await self.capability_worker.speak(
                                self.create_current_weather_briefing(
                                    new_home_weather, temp_unit,
                                    include_recommendations=True
                                )
                            )
                            break
                        else:
                            await self.capability_worker.speak(
                                f"Couldn't find {new_home}. Try another?"
                            )
                    else:
                        await self.capability_worker.speak("Couldn't understand. Which city?")

            # SETTINGS AND FAVORITES
            await self.worker.session_tasks.sleep(0.2)
            settings_response = await self.capability_worker.run_io_loop(
                "Do you want to change settings or manage favorites?"
            )

            if settings_response:
                should_enter_settings = (
                    self.is_yes_response(settings_response)
                    or "setting" in settings_response.lower()
                    or "favorite" in settings_response.lower()
                    or "favourites" in settings_response.lower()
                )

                if should_enter_settings:
                    await self.worker.session_tasks.sleep(0.1)
                    setting_choice = await self.capability_worker.run_io_loop(
                        "Say unit or favorites."
                    )

                    if setting_choice:
                        if (
                            "unit" in setting_choice.lower()
                            or "temperature" in setting_choice.lower()
                            or "celsius" in setting_choice.lower()
                            or "fahrenheit" in setting_choice.lower()
                        ):
                            await self.worker.session_tasks.sleep(0.1)
                            new_unit_response = await self.capability_worker.run_io_loop(
                                "Celsius or Fahrenheit?"
                            )
                            if new_unit_response:
                                if self.is_fahrenheit_response(new_unit_response):
                                    temp_unit = "fahrenheit"
                                    prefs["temp_unit"] = "fahrenheit"
                                    await self.save_preferences(prefs)
                                    await self.capability_worker.speak("Changed to Fahrenheit.")
                                else:
                                    temp_unit = "celsius"
                                    prefs["temp_unit"] = "celsius"
                                    await self.save_preferences(prefs)
                                    await self.capability_worker.speak("Changed to Celsius.")

                        elif (
                            "favorite" in setting_choice.lower()
                            or "favourites" in setting_choice.lower()
                        ):
                            await self.worker.session_tasks.sleep(0.1)
                            fav_action = await self.capability_worker.run_io_loop(
                                "Say add, remove, list, or check all."
                            )

                            if fav_action:
                                if "add" in fav_action.lower():
                                    await self.worker.session_tasks.sleep(0.1)
                                    fav_input = await self.capability_worker.run_io_loop(
                                        "Which city to add to favorites?"
                                    )
                                    fav_city = (
                                        self.extract_city_from_text(fav_input)
                                        if fav_input else None
                                    )
                                    if fav_city:
                                        test = self.fetch_weather_data(fav_city, days=1)
                                        if test:
                                            if await self.add_to_favorites(
                                                test["location"], prefs
                                            ):
                                                await self.capability_worker.speak(
                                                    f"{test['location']} added to favorites."
                                                )
                                        else:
                                            await self.capability_worker.speak(
                                                f"Couldn't find {fav_city}."
                                            )

                                elif (
                                    "remove" in fav_action.lower()
                                    or "delete" in fav_action.lower()
                                ):
                                    current_favorites = prefs.get("favorites", [])
                                    if not current_favorites:
                                        await self.capability_worker.speak(
                                            "No favorites to remove."
                                        )
                                    else:
                                        await self.worker.session_tasks.sleep(0.1)
                                        rem_input = await self.capability_worker.run_io_loop(
                                            "Which city to remove from favorites?"
                                        )
                                        rem_city = (
                                            self.extract_city_from_text(rem_input)
                                            if rem_input else None
                                        )
                                        if rem_city:
                                            if await self.remove_from_favorites(
                                                rem_city, prefs
                                            ):
                                                await self.capability_worker.speak(
                                                    f"{rem_city} removed from favorites."
                                                )

                                elif (
                                    "list" in fav_action.lower()
                                    or "show" in fav_action.lower()
                                ):
                                    current_favorites = prefs.get("favorites", [])
                                    if not current_favorites:
                                        await self.capability_worker.speak(
                                            "You have no favorites saved."
                                        )
                                    else:
                                        fav_list = ", ".join(current_favorites)
                                        await self.capability_worker.speak(
                                            f"Your favorites: {fav_list}."
                                        )

                                elif (
                                    "check" in fav_action.lower()
                                    or "all" in fav_action.lower()
                                ):
                                    await self.check_favorites_weather(prefs, temp_unit)

            # CHECK OTHER AREAS LOOP
            while True:
                await self.worker.session_tasks.sleep(0.2)
                check_response = await self.capability_worker.run_io_loop(
                    "Do you want to check other areas?"
                )

                if not check_response:
                    await self.capability_worker.speak("Didn't catch that.")
                    continue

                if self.is_no_response(check_response) or self.is_exit(check_response):
                    await self.capability_worker.speak("Goodbye.")
                    break

                other_city = None

                if self.is_yes_response(check_response):
                    await self.worker.session_tasks.sleep(0.1)
                    other_city_input = await self.capability_worker.run_io_loop(
                        "Which area?"
                    )

                    if not other_city_input:
                        await self.capability_worker.speak("Didn't catch that.")
                        continue

                    if self.is_exit(other_city_input):
                        await self.capability_worker.speak("Goodbye.")
                        break

                    other_city = self.extract_city_from_text(other_city_input)
                else:
                    other_city = self.extract_city_from_text(check_response)

                if not other_city:
                    await self.capability_worker.speak("Couldn't understand the city. Try again?")
                    continue

                other_weather = self.fetch_weather_data(other_city, days=3)
                if not other_weather:
                    await self.capability_worker.speak(
                        f"Couldn't find {other_city}. Try another city?"
                    )
                    continue

                await self.capability_worker.speak(
                    self.create_current_weather_briefing(
                        other_weather, temp_unit, include_recommendations=True
                    )
                )

                # ADD TO FAVORITES
                await self.worker.session_tasks.sleep(0.2)
                add_fav_response = await self.capability_worker.run_io_loop(
                    f"Add {other_weather['location']} to favorites?"
                )
                if add_fav_response and self.is_exit(add_fav_response):
                    await self.capability_worker.speak("Goodbye.")
                    break
                if add_fav_response and self.is_yes_response(add_fav_response):
                    if await self.add_to_favorites(other_weather["location"], prefs):
                        await self.capability_worker.speak(
                            f"{other_weather['location']} added to favorites."
                        )

                # 3-DAY FORECAST
                await self.worker.session_tasks.sleep(0.2)
                other_forecast = await self.capability_worker.run_io_loop(
                    "Want the 3-day forecast for this city?"
                )
                if other_forecast and self.is_exit(other_forecast):
                    await self.capability_worker.speak("Goodbye.")
                    break
                if other_forecast and self.is_yes_response(other_forecast):
                    await self.capability_worker.speak(
                        self.create_3day_forecast_briefing(other_weather, temp_unit)
                    )

                # HOURLY FORECAST
                await self.worker.session_tasks.sleep(0.2)
                other_hourly = await self.capability_worker.run_io_loop(
                    "Want the hourly forecast?"
                )
                if other_hourly and self.is_exit(other_hourly):
                    await self.capability_worker.speak("Goodbye.")
                    break
                if other_hourly and self.is_yes_response(other_hourly):
                    await self.capability_worker.speak(
                        self.create_hourly_forecast_briefing(other_weather, temp_unit)
                    )

                # SUNRISE / SUNSET
                await self.worker.session_tasks.sleep(0.2)
                other_sun = await self.capability_worker.run_io_loop(
                    "Want sunrise and sunset times for this city?"
                )
                if other_sun and self.is_exit(other_sun):
                    await self.capability_worker.speak("Goodbye.")
                    break
                if other_sun and self.is_yes_response(other_sun):
                    await self.capability_worker.speak(
                        self.create_sun_times_briefing(other_weather)
                    )

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Weather ability error: {e}")
            await self.capability_worker.speak("Something went wrong.")
        finally:
            self.capability_worker.resume_normal_flow()
