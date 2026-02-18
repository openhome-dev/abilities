import asyncio
import os
import json
import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


class SpaceflightTrackerCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"], matching_hotwords=data["matching_hotwords"]
        )

    async def get_iss_location(self) -> str:
        """Fetch the current location of the International Space Station."""
        try:
            response = requests.get("http://api.open-notify.org/iss-now.json")
            self.worker.editor_logging_handler.debug(
                f"ISS Location Response: {response.json()}"
            )

            if response.status_code == 200:
                data = response.json()
                lat = float(data["iss_position"]["latitude"])
                lon = float(data["iss_position"]["longitude"])

                lat_direction = "North" if lat >= 0 else "South"
                lon_direction = "East" if lon >= 0 else "West"

                return f"The International Space Station is currently at {abs(lat):.2f} degrees {lat_direction} latitude and {abs(lon):.2f} degrees {lon_direction} longitude."

            return "I'm having trouble getting the ISS location right now."

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"Error fetching ISS location: {e}"
            )
            return "Sorry, I couldn't get the current location of the ISS."

    async def get_astronauts(self) -> str:
        """Fetch information about current astronauts in space."""
        try:
            # Add callback parameter for JSONP format
            response = requests.get("http://api.open-notify.org/astros.json?callback=?")
            self.worker.editor_logging_handler.debug(
                f"Raw Astronauts Response: {response.text}"
            )

            if response.status_code == 200:
                # Extract the JSON data from the JSONP response
                # JSONP response looks like "?({"people": [...], "number": n})"
                text = response.text
                # Remove the callback wrapper and get just the JSON part
                json_str = text[text.index("(") + 1 : text.rindex(")")]
                data = json.loads(json_str)

                self.worker.editor_logging_handler.debug(
                    f"Parsed Astronauts Data: {data}"
                )

                num_people = data["number"]

                if num_people == 0:
                    return "There are currently no humans in space."

                astronaut_list = [person["name"] for person in data["people"]]

                if num_people == 1:
                    return f"There is currently 1 person in space: {astronaut_list[0]}."

                astronauts_text = (
                    ", ".join(astronaut_list[:-1]) + f", and {astronaut_list[-1]}"
                )
                return f"There are currently {num_people} people in space: {astronauts_text}."

            return "I'm having trouble getting information about astronauts in space."

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"Error fetching astronaut info: {e}"
            )
            return "Sorry, I couldn't get information about who's currently in space."

    def format_for_speech(self, text: str) -> str:
        """Format the space information to be more natural for speech."""
        prompt = f"""Make this space information more conversational and engaging for speech. The raw data includes latitude and longitude, after you say it, you should contextualize where that is (e.g., over Greenland, over Singapore, etc.).
        Don't be too casual or verbose in your answer. Sound official and concise.
        Input: "{text}"
Output:"""
        return self.capability_worker.text_to_text_response(prompt).strip()

    async def main_flow(self):
        """Main flow for the space information ability."""
        try:
            # Initialize response components
            response_parts = []

            # Try to get ISS location
            try:
                iss_location = await self.get_iss_location()
                if not iss_location.startswith("Sorry") and not iss_location.startswith(
                    "I'm having trouble"
                ):
                    response_parts.append(iss_location)
            except Exception as e:
                self.worker.editor_logging_handler.error(
                    f"Error getting ISS location: {e}"
                )

            # Try to get astronaut information
            try:
                astronaut_info = await self.get_astronauts()
                if not astronaut_info.startswith(
                    "Sorry"
                ) and not astronaut_info.startswith("I'm having trouble"):
                    response_parts.append(astronaut_info)
            except Exception as e:
                self.worker.editor_logging_handler.error(
                    f"Error getting astronaut info: {e}"
                )

            # If we have any information to share
            if response_parts:
                combined_info = " ".join(response_parts)
                formatted_info = self.format_for_speech(combined_info)
                await self.capability_worker.speak(formatted_info)
            else:
                await self.capability_worker.speak(
                    "I'm having trouble getting space information right now. Please try again later."
                )

        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"Error in Space Info ability: {e}"
            )
            await self.capability_worker.speak(
                "I'm having trouble getting space information right now. Please try again later."
            )
        finally:
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        asyncio.create_task(self.main_flow())
