"""
Package Tracker — Voice ability to track parcels via real tracking numbers.
Uses TrackingMore API (external integration).
"""
import json
import os
import re
from typing import ClassVar, Set

import requests
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# TrackingMore API (get free key at https://www.trackingmore.com)
API_BASE = "https://api.trackingmore.com/v2/trackings"
API_KEY: ClassVar[str] = "5slor2rf-pr0h-0t1u-w0fn-0fg9hf7zy8rd"

EXIT_WORDS: ClassVar[Set[str]] = {"stop", "exit", "quit", "done", "cancel", "bye", "goodbye", "never mind"}

# Common carrier codes for TrackingMore
CARRIER_ALIASES: ClassVar[dict] = {
    "usps": "usps",
    "ups": "ups",
    "fedex": "fedex",
    "dhl": "dhl",
    "amazon": "amazon",
    "ontrac": "ontrac",
    "auto": "auto",
}


class PackageTracker(MatchingCapability):
    #{{register capability}}
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        return cls(
            unique_name="package_tracker",
            matching_hotwords=["track my package", "where's my package", "package status", "tracking"],
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.tracking_loop())

    def _normalize_tracking_number(self, raw: str) -> str:
        """Strip spaces and keep alphanumerics; many carriers allow letters."""
        return re.sub(r"[^A-Za-z0-9]", "", raw.strip()) if raw else ""

    def _carrier_from_input(self, text: str) -> str:
        """Infer carrier code from user input; default to usps for common US format."""
        lower = text.lower().strip()
        for alias, code in CARRIER_ALIASES.items():
            if alias in lower:
                return code
        return "usps"

    def _fetch_tracking(self, tracking_number: str, carrier_code: str) -> dict | None:
        """Call TrackingMore API. Returns parsed result dict or None on failure."""
        if not tracking_number or API_KEY == "YOUR_TRACKINGMORE_API_KEY":
            return None
        url = f"{API_BASE}/{carrier_code}/{tracking_number}"
        headers = {
            "Content-Type": "application/json",
            "Trackingmore-Api-Key": API_KEY,
        }
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                self.worker.editor_logging_handler.warning(
                    f"[PackageTracker] API {response.status_code}: {response.text[:200]}"
                )
                return None
            return response.json()
        except requests.exceptions.Timeout:
            self.worker.editor_logging_handler.warning("[PackageTracker] API timeout")
            return None
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[PackageTracker] API error: {e}")
            return None

    def _speakable_status(self, data: dict) -> str:
        """Turn API response into a short spoken summary."""
        try:
            meta = data.get("data", {}) or data
            if not meta:
                return "No tracking details returned."
            # v2 structure: often info.tracking_number, origin, destination, lastEvent
            info = meta.get("info") or meta
            origin = (info.get("origin_info", {}) or {}).get("country") or (info.get("origin") or "Unknown")
            dest = (info.get("destination_info", {}) or {}).get("country") or (info.get("destination") or "Unknown")
            last_event = meta.get("lastEvent") or meta.get("last_update") or info.get("last_update")
            if isinstance(last_event, dict):
                status = last_event.get("status") or last_event.get("description") or "In transit"
                place = last_event.get("location") or last_event.get("sub_status") or ""
            else:
                status = str(last_event) if last_event else "In transit"
                place = ""
            parts = [f"Status: {status}."]
            if place:
                parts.append(f" Last location: {place}.")
            parts.append(f" From {origin} to {dest}.")
            return " ".join(parts)
        except Exception as e:
            self.worker.editor_logging_handler.warning(f"[PackageTracker] Parse error: {e}")
            return "Got the tracking data but couldn't summarize it. Check the dashboard for details."

    async def tracking_loop(self):
        try:
            await self.capability_worker.speak(
                "Package tracker here. Say a tracking number to check status, or say stop to exit."
            )
            while True:
                await self.worker.session_tasks.sleep(0.1)
                user_input = await self.capability_worker.run_io_loop(
                    "What's the tracking number? You can say the carrier too, like USPS or FedEx. Say stop when done."
                )
                if not user_input or not user_input.strip():
                    await self.capability_worker.speak("I didn't catch that. Try again or say stop to exit.")
                    continue
                input_lower = user_input.lower().strip()
                if any(word in input_lower for word in EXIT_WORDS):
                    await self.capability_worker.speak("Exiting package tracker. Goodbye.")
                    break
                tracking = self._normalize_tracking_number(user_input)
                if not tracking:
                    await self.capability_worker.speak("That doesn't look like a tracking number. Try again?")
                    continue
                carrier = self._carrier_from_input(user_input)
                await self.capability_worker.speak(f"Checking {carrier} tracking for {tracking}...")
                result = self._fetch_tracking(tracking, carrier)
                if result is None:
                    await self.capability_worker.speak(
                        "Couldn't get tracking info. Check the number and carrier, or try again later."
                    )
                    continue
                summary = self._speakable_status(result)
                await self.capability_worker.speak(summary)
        except Exception as e:
            self.worker.editor_logging_handler.error(f"[PackageTracker] Loop error: {e}")
            await self.capability_worker.speak("Something went wrong. Exiting tracker.")
        finally:
            self.capability_worker.resume_normal_flow()
