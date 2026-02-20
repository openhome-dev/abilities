"""External API Service - Handles all external API integrations.

Responsibilities:
- Weather API (Open-Meteo)
- Emergency vet search (Serper Maps)
- Food recall checking (openFDA + Serper News)
- Geolocation (IP-based + geocoding)
"""

import asyncio
import json
from typing import Optional

import requests


class ExternalAPIService:
    """Service for external API integrations (weather, vets, recalls, geocoding)."""

    def __init__(self, worker, serper_api_key=None):
        """Initialize ExternalAPIService.

        Args:
            worker: AgentWorker for logging
            serper_api_key: Optional Serper API key for vet search and news
        """
        self.worker = worker
        self.serper_api_key = serper_api_key

    async def get_weather_data(self, lat: float, lon: float) -> Optional[dict]:
        """Fetch weather data from Open-Meteo API (non-blocking).

        Args:
            lat: Latitude
            lon: Longitude

        Returns:
            Weather data dict or None if API call fails
        """
        try:
            url = "https://api.open-meteo.com/v1/forecast"
            params = {
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,weather_code,wind_speed_10m",
                "hourly": "uv_index",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "timezone": "auto",
            }

            resp = await asyncio.to_thread(requests.get, url, params=params, timeout=10)

            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if "current" not in data:
                        self.worker.editor_logging_handler.error(
                            "[PetCare] Weather API response missing 'current' field"
                        )
                        return None
                    return data
                except json.JSONDecodeError as e:
                    self.worker.editor_logging_handler.error(
                        f"[PetCare] Invalid JSON from Weather API: {e}"
                    )
                    return None
            else:
                self.worker.editor_logging_handler.warning(
                    f"[PetCare] Weather API returned {resp.status_code}"
                )
                return None

        except requests.exceptions.Timeout:
            self.worker.editor_logging_handler.error("[PetCare] Weather API timeout")
            return None
        except requests.exceptions.ConnectionError:
            self.worker.editor_logging_handler.error(
                "[PetCare] Could not connect to Weather API"
            )
            return None
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PetCare] Unexpected Weather API error: {e}"
            )
            return None

    async def search_emergency_vets(
        self, lat: float, lon: float, location: str
    ) -> list:
        """Search for emergency vets using Serper Maps API (non-blocking).

        Args:
            lat: Latitude
            lon: Longitude
            location: Human-readable location string

        Returns:
            List of vet dicts with title, rating, openNow, phoneNumber
        """
        if not self.serper_api_key or self.serper_api_key == "your_serper_api_key_here":
            self.worker.editor_logging_handler.warning(
                "[PetCare] Serper API key not configured"
            )
            return []

        try:
            resp = await asyncio.to_thread(
                requests.post,
                "https://google.serper.dev/maps",
                headers={
                    "X-API-KEY": self.serper_api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "q": f"emergency vet near {location}",
                    "lat": lat,
                    "lon": lon,
                    "num": 5,
                },
                timeout=10,
            )

            if resp.status_code == 200:
                try:
                    data = resp.json()
                    return data.get("places", [])
                except json.JSONDecodeError as e:
                    self.worker.editor_logging_handler.error(
                        f"[PetCare] Invalid JSON from Serper Maps: {e}"
                    )
                    return []
            elif resp.status_code in (401, 403):
                self.worker.editor_logging_handler.error(
                    f"[PetCare] Serper API authentication failed: {resp.status_code}"
                )
                return []
            elif resp.status_code == 429:
                self.worker.editor_logging_handler.warning(
                    "[PetCare] Serper API rate limit exceeded"
                )
                return []
            else:
                self.worker.editor_logging_handler.warning(
                    f"[PetCare] Serper Maps returned {resp.status_code}"
                )
                return []

        except requests.exceptions.Timeout:
            self.worker.editor_logging_handler.error("[PetCare] Serper Maps timeout")
            return []
        except requests.exceptions.ConnectionError:
            self.worker.editor_logging_handler.error(
                "[PetCare] Could not connect to Serper Maps"
            )
            return []
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PetCare] Unexpected Serper Maps error: {e}"
            )
            return []

    async def fetch_fda_events(self, species: str) -> list:
        """Fetch FDA adverse events for a specific species (non-blocking).

        Args:
            species: Pet species ("dog" or "cat")

        Returns:
            List of FDA event dicts with source, species, brand, date
        """
        results = []
        try:
            url = "https://api.fda.gov/animalandtobacco/event.json"
            params = {
                "search": f'animal.species:"{species}"',
                "limit": 5,
                "sort": "original_receive_date:desc",
            }

            resp = await asyncio.to_thread(requests.get, url, params=params, timeout=10)

            if resp.status_code == 200:
                try:
                    data = resp.json()
                except json.JSONDecodeError as e:
                    self.worker.editor_logging_handler.error(
                        f"[PetCare] Invalid JSON from FDA API: {e}"
                    )
                    return results

                for r in data.get("results", []):
                    products = r.get("product", [])
                    for prod in products:
                        brand = prod.get("brand_name", "Unknown brand")
                        results.append(
                            {
                                "source": "FDA",
                                "species": species,
                                "brand": brand,
                                "date": r.get("original_receive_date", "unknown date"),
                            }
                        )
            elif resp.status_code == 404:
                self.worker.editor_logging_handler.info(
                    f"[PetCare] No FDA events found for {species}"
                )
            elif resp.status_code == 429:
                self.worker.editor_logging_handler.warning(
                    "[PetCare] FDA API rate limit exceeded"
                )
            else:
                self.worker.editor_logging_handler.warning(
                    f"[PetCare] FDA API returned {resp.status_code}"
                )

        except requests.exceptions.Timeout:
            self.worker.editor_logging_handler.error(
                f"[PetCare] FDA API timeout for {species}"
            )
        except requests.exceptions.ConnectionError:
            self.worker.editor_logging_handler.error(
                f"[PetCare] Could not connect to FDA API for {species}"
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PetCare] Unexpected FDA error for {species}: {e}"
            )

        return results

    async def fetch_serper_news(self, species_set: set) -> list:
        """Fetch Serper News headlines for food recalls (non-blocking).

        Args:
            species_set: Set of pet species

        Returns:
            List of news headline dicts with source, title, snippet, date
        """
        if not self.serper_api_key or self.serper_api_key == "your_serper_api_key_here":
            return []

        headlines = []
        species_labels = " or ".join(s for s in species_set if s in ("dog", "cat"))
        search_query = (
            f"pet food recall {species_labels} 2025"
            if species_labels
            else "pet food recall 2025"
        )

        try:
            news_resp = await asyncio.to_thread(
                requests.post,
                "https://google.serper.dev/news",
                headers={
                    "X-API-KEY": self.serper_api_key,
                    "Content-Type": "application/json",
                },
                json={"q": search_query, "num": 5},
                timeout=10,
            )

            if news_resp.status_code == 200:
                try:
                    news_data = news_resp.json()
                except json.JSONDecodeError as e:
                    self.worker.editor_logging_handler.error(
                        f"[PetCare] Invalid JSON from Serper News: {e}"
                    )
                    return headlines

                for item in news_data.get("news", [])[:5]:
                    title = item.get("title", "")
                    snippet = item.get("snippet", "")
                    date = item.get("date", "")
                    if title:
                        headlines.append(
                            {
                                "source": "News",
                                "title": title,
                                "snippet": snippet,
                                "date": date,
                            }
                        )
            elif news_resp.status_code in (401, 403):
                self.worker.editor_logging_handler.error(
                    f"[PetCare] Serper News authentication failed: {news_resp.status_code}"
                )
            elif news_resp.status_code == 429:
                self.worker.editor_logging_handler.warning(
                    "[PetCare] Serper News rate limit exceeded"
                )
            else:
                self.worker.editor_logging_handler.warning(
                    f"[PetCare] Serper News returned {news_resp.status_code}"
                )

        except requests.exceptions.Timeout:
            self.worker.editor_logging_handler.error("[PetCare] Serper News timeout")
        except requests.exceptions.ConnectionError:
            self.worker.editor_logging_handler.error(
                "[PetCare] Could not connect to Serper News"
            )
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PetCare] Unexpected Serper News error: {e}"
            )

        return headlines

    async def detect_location_by_ip(self, client_ip: str) -> Optional[dict]:
        """Detect user location from IP address (non-blocking).

        Args:
            client_ip: Client IP address

        Returns:
            Dict with lat, lon, city, region, isp or None if detection fails
        """
        try:
            url = f"http://ip-api.com/json/{client_ip}"
            resp = await asyncio.to_thread(requests.get, url, timeout=5)

            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    # Check for cloud/VPN IPs
                    isp = data.get("isp", "").lower()
                    # Warn if cloud/VPN IP detected (location may be inaccurate)
                    if any(
                        cloud in isp
                        for cloud in [
                            "amazon",
                            "google",
                            "microsoft",
                            "cloudflare",
                            "digital ocean",
                        ]
                    ):
                        self.worker.editor_logging_handler.warning(
                            f"[PetCare] Detected cloud/VPN IP ({isp}), location may be inaccurate"
                        )

                    return {
                        "lat": data.get("lat"),
                        "lon": data.get("lon"),
                        "city": data.get("city"),
                        "region": data.get("regionName"),
                        "isp": data.get("isp"),
                    }

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PetCare] IP geolocation error: {e}"
            )

        return None

    async def geocode_location(
        self, location: str, geocode_cache: dict
    ) -> Optional[dict]:
        """Geocode a location string to lat/lon (non-blocking, with caching).

        Args:
            location: Location string (e.g., "Austin, Texas")
            geocode_cache: Cache dict for storing results

        Returns:
            Dict with lat, lon or None if geocoding fails
        """
        if location in geocode_cache:
            self.worker.editor_logging_handler.info(
                f"[PetCare] Geocoding cache hit for: {location}"
            )
            return geocode_cache[location]

        try:
            url = "https://geocoding-api.open-meteo.com/v1/search"
            params = {"name": location, "count": 1}

            resp = await asyncio.to_thread(requests.get, url, params=params, timeout=5)

            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                if results:
                    result = {
                        "lat": results[0]["latitude"],
                        "lon": results[0]["longitude"],
                    }
                    geocode_cache[location] = result
                    return result

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[PetCare] Geocoding error for {location}: {e}"
            )

        return None
