import json
from typing import ClassVar, Set

import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

class FlightPriceCheckerCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    
    # Do not change
    #{{register capability}}

    API_URL_BASE: ClassVar[str] = "https://kiwi-com-cheap-flights.p.rapidapi.com"
    API_KEY: ClassVar[str] = "YOUR_API_KEY"

    EXIT_WORDS: ClassVar[Set[str]] = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye"}

    IATA_MAP: ClassVar[dict] = {
        "california": "LAX",
        "texas": "DFW",
        "new york": "JFK",
        "london": "LHR",
        "paris": "CDG",
        "dhaka": "DAC",
        "khulna": "DAC",
        "cox's bazar": "CXB",
        "chittagong": "CGP",
        "chitran": "CGP",
        "chitang": "CGP",
        "cheetahung": "CGP",
        "haga": "DAC",
        "bangkok": "BKK",
        "dubai": "DXB",
        "dhargham": "DAC",  # typo fix
    }

    async def flight_loop(self):
        try:
            # Greeting FIRST
            await self.capability_worker.speak(
                "Hi mate! Flight prices ready. Tell me where from and to, "
                "like 'Dhaka to Bangkok' or 'from Dhaka to Chittagong'. Say stop to exit."
            )

            while True:
                await self.worker.session_tasks.sleep(0.1)

                user_input = await self.capability_worker.run_io_loop(
                    "What's your flight query? Say stop or exit when done."
                )

                if not user_input:
                    await self.capability_worker.speak("Didn't hear you. Try again?")
                    continue

                input_lower = user_input.lower().strip()

                if any(word in input_lower for word in self.EXIT_WORDS):
                    await self.capability_worker.speak("Flight search finished. Safe travels!")
                    break

                # Simple keyword extraction (no LLM)
                origin = ""
                dest = ""
                words = input_lower.split()
                for i, word in enumerate(words):
                    if word in ["from", "starting", "depart"]:
                        if i+1 < len(words):
                            origin = words[i+1]
                    if word in ["to", "destination", "arrive", "fly"]:
                        if i+1 < len(words):
                            dest = words[i+1]

                # Fallback for common patterns like "Dhaka to Bangkok"
                if not origin or not dest:
                    if " to " in input_lower:
                        parts = input_lower.split(" to ")
                        if len(parts) == 2:
                            origin = parts[0].split()[-1]
                            dest = parts[1].split()[0]

                if not origin or not dest:
                    await self.capability_worker.speak(
                        "Couldn't find cities. Try 'Dhaka to Bangkok' or 'from Dhaka to Chittagong'?"
                    )
                    continue

                # Success feedback
                await self.capability_worker.speak(f"Understood — from {origin} to {dest}. Checking prices now...")

                origin_iata = self.IATA_MAP.get(origin) or self._guess_iata(origin)
                dest_iata = self.IATA_MAP.get(dest) or self._guess_iata(dest)

                if not origin_iata or not dest_iata:
                    await self.capability_worker.speak("Couldn't match airports. Try well-known cities?")
                    continue

                url = f"{self.API_URL_BASE}/one-way"
                headers = {"x-rapidapi-key": self.API_KEY}
                params = {
                    "source": f"Airport:{origin_iata}",
                    "destination": f"Airport:{dest_iata}",
                    "currency": "usd",
                    "locale": "en",
                    "adults": "1",
                    "sortBy": "PRICE",
                    "sortOrder": "ASCENDING",
                    "limit": "3",
                }

                try:
                    response = requests.get(url, params=params, headers=headers, timeout=12)
                    # await self.capability_worker.speak(f"API status: {response.status_code}")

                    response.raise_for_status()
                    data = response.json()

                    itineraries = data.get("itineraries", [])
                    if not itineraries:
                        await self.capability_worker.speak("No flights found for that route. Try other dates?")
                        continue

                    summary = "Cheapest flights: "
                    for i, itin in enumerate(itineraries[:3], 1):
                        price = itin.get("price", {}).get("amount", "unknown")
                        seg = itin.get("sector", {}).get("sectorSegments", [{}])[0]
                        carrier = seg.get("segment", {}).get("carrier", {}).get("name", "unknown airline")
                        dur_min = seg.get("segment", {}).get("duration", 0) // 60
                        summary += f"Option {i}: ${price} with {carrier}, ~{dur_min} min. "

                    await self.capability_worker.speak(summary + " Want more details?")
                
                except requests.exceptions.HTTPError as http_err:
                    await self.capability_worker.speak(f"API error — status {response.status_code}. Quota or key issue?")
                except Exception as e:
                    await self.capability_worker.speak("Couldn't fetch prices. Try again?")
                    if hasattr(self.worker, 'editor_logging_handler'):
                        self.worker.editor_logging_handler.warning(f"Flight API failed: {str(e)}")

        except Exception as e:
            await self.capability_worker.speak(f"Flight tool error: {str(e)[:100]}")
            if hasattr(self.worker, 'editor_logging_handler'):
                self.worker.editor_logging_handler.warning(f"Loop error: {str(e)}")
        
        finally:
            self.capability_worker.resume_normal_flow()

    def _guess_iata(self, city: str) -> str | None:
        prompt = f"Return ONLY the 3-letter uppercase IATA code for the main airport of {city}. No other text."
        code = self.capability_worker.text_to_text_response(prompt).strip().upper()
        return code if len(code) == 3 else None

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.flight_loop())
