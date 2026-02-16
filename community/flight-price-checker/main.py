from typing import ClassVar, Set
import json
import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker

class FlightFinderCapability(MatchingCapability):
    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # {{register capability}}

    API_URL_BASE: ClassVar[str] = "https://kiwi-com-cheap-flights.p.rapidapi.com"
    API_KEY: ClassVar[str] = "API_KEY"

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
        "dhargham": "DAC",
    }

    async def flight_loop(self):
        try:
            await self.capability_worker.speak(
                "Hi! I can check flight prices. Tell me where from and to, "
                "like 'Dhaka to Bangkok' or 'from Dhaka to Chittagong'. Say stop to exit."
            )

            while True:
                await self.worker.session_tasks.sleep(0.1)

                user_input = await self.capability_worker.run_io_loop(
                    "Where are you flying from and to?"
                )

                if not user_input:
                    await self.capability_worker.speak("Didn't catch that. Try again?")
                    continue

                input_lower = user_input.lower().strip()

                if any(word in input_lower for word in self.EXIT_WORDS):
                    await self.capability_worker.speak("Flight search finished. Safe travels!")
                    break

                # Simple keyword extraction
                origin = ""
                dest = ""
                words = input_lower.split()
                for i, word in enumerate(words):
                    if word in ["from", "starting", "depart"]:
                        if i + 1 < len(words):
                            origin = words[i + 1]
                    if word in ["to", "destination", "arrive", "fly"]:
                        if i + 1 < len(words):
                            dest = words[i + 1]

                if " to " in input_lower and not origin and not dest:
                    parts = input_lower.split(" to ")
                    if len(parts) >= 2:
                        origin = parts[0].split()[-1]
                        dest = parts[1].split()[0]

                if not origin or not dest:
                    await self.capability_worker.speak(
                        "Couldn't understand the cities. Try 'Dhaka to Bangkok'?"
                    )
                    continue

                origin_iata = self.IATA_MAP.get(origin) or self._guess_iata(origin)
                dest_iata = self.IATA_MAP.get(dest) or self._guess_iata(dest)

                if not origin_iata or not dest_iata:
                    await self.capability_worker.speak("Couldn't find airports. Try well-known cities?")
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
                    response.raise_for_status()
                    data = response.json()

                    itineraries = data.get("itineraries", [])
                    if not itineraries:
                        await self.capability_worker.speak("No flights found. Try other dates?")
                        continue

                    summary = "Cheapest flights: "
                    for i, itin in enumerate(itineraries[:3], 1):
                        price = itin.get("price", {}).get("amount", "unknown")
                        seg = itin.get("sector", {}).get("sectorSegments", [{}])[0]
                        carrier = seg.get("segment", {}).get("carrier", {}).get("name", "unknown airline")
                        dur_min = seg.get("segment", {}).get("duration", 0) // 60
                        summary += f"Option {i}: ${price} with {carrier}, ~{dur_min} min. "

                    await self.capability_worker.speak(summary + " Want more details?")

                    more = await self.capability_worker.run_io_loop(
                        "Say yes for more details, or no to search again."
                    )
                    if "yes" in more.lower():
                        details = "More info: "
                        for i, itin in enumerate(itineraries[:3], 1):
                            price = itin.get("price", {}).get("amount", "unknown")
                            seg = itin.get("sector", {}).get("sectorSegments", [{}])[0]
                            carrier = seg.get("segment", {}).get("carrier", {}).get("name", "unknown")
                            dur = seg.get("segment", {}).get("duration", 0) // 60
                            details += f"Option {i}: ${price}, {dur} min, {carrier}. "
                        await self.capability_worker.speak(details + " Anything else?")
                    else:
                        await self.capability_worker.speak("Okay, happy to search again!")

                except requests.exceptions.HTTPError:
                    await self.capability_worker.speak("Couldn't reach the flight API right now. Try again later?")
                except Exception:
                    await self.capability_worker.speak("Something went wrong while checking prices. Try again?")

        except Exception:
            await self.capability_worker.speak("Flight tool error. Ending now.")

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
