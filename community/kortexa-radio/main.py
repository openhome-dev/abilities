import asyncio
import httpx

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

STREAM_URL = "https://api.kortexa.ai/radio/stream"
EVENTS_URL = "https://api.kortexa.ai/radio/events"
CHUNK_SIZE = 25 * 1024
TAG = "[KortexaRadio]"

STOP_WORDS = ["stop", "off", "exit", "quit", "turn it off"]


class KortexaRadioCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    #{{register_capability}}

    async def _stream(self):
        """Stream radio audio with pause/stop handling."""
        try:

            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", STREAM_URL, follow_redirects=True) as response:
                    self.worker.editor_logging_handler.info(f"{TAG} Connected, status={response.status_code}")

                    if response.status_code != 200:
                        await self.capability_worker.speak("Could not connect to the radio stream.")
                        return

                    await self.capability_worker.stream_init()

                    async for chunk in response.aiter_bytes(chunk_size=CHUNK_SIZE):
                        if not chunk:
                            self.worker.editor_logging_handler.info(f"{TAG} No chunk")
                            continue

                        if self.worker.music_mode_stop_event.is_set():
                            self.worker.editor_logging_handler.info(f"{TAG} Stop event, ending stream")
                            await self.capability_worker.stream_end()
                            return

                        while self.worker.music_mode_pause_event.is_set():
                            await self.worker.session_tasks.sleep(0.1)

                        await self.capability_worker.send_audio_data_in_stream(chunk)

            await self.capability_worker.stream_end()

        except asyncio.CancelledError as e:
            self.worker.editor_logging_handler.info(f"{TAG} Stream cancelled: {e}")
        except Exception as e:
            self.worker.editor_logging_handler.error(f"{TAG} Stream error: {e}")

    async def _keep_events_connected(self):
        """Stay connected to SSE to register as a listener. Events are not processed."""
        try:
            while True:
                try:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                        async with client.stream("GET", EVENTS_URL) as response:
                            async for _ in response.aiter_lines():
                                pass
                except httpx.HTTPError as e:
                    self.worker.editor_logging_handler.error(f"{TAG} SSE error: {e}")
                    pass

                await self.worker.session_tasks.sleep(5)
        except asyncio.CancelledError:
            self.worker.editor_logging_handler.info(f"{TAG} SSE cancelled")

            pass

    async def run(self):
        """Auto-start radio, listen for stop command, exit cleanly."""

        stream_task = None
        events_task = None

        try:
            await self.capability_worker.speak("Tuning in to Kortexa Radio.")

            # Subscribe to events (registers us as a listener)
            self.worker.editor_logging_handler.info(f"{TAG} Register as a listener")
            events_task = self.worker.session_tasks.create(self._keep_events_connected())

            # Turn on music mode
            self.worker.editor_logging_handler.info(f"{TAG} Turn on music mode")
            self.worker.music_mode_event.set()
            await self.capability_worker.send_data_over_websocket("music-mode", {"mode": "on"})

            # Stream audio in background so the loop stays responsive
            self.worker.editor_logging_handler.info(f"{TAG} Start streaming")
            stream_task = self.worker.session_tasks.create(self._stream())

            # Wait for stop command
            while not self.worker.music_mode_stop_event.is_set():
                msg = await self.capability_worker.user_response()

                if self.worker.music_mode_stop_event.is_set():
                    break

                if msg:
                    normalized = msg.strip().lower()
                    self.worker.editor_logging_handler.info(f"{TAG} Command: {normalized}")

                    if any(word in normalized for word in STOP_WORDS):
                        self.worker.editor_logging_handler.info(f"{TAG} Stop requested")
                        self.worker.music_mode_stop_event.set()
                        break

            await self.capability_worker.speak("Radio off! Catch you later.")

        except Exception as e:
            self.worker.editor_logging_handler.error(f"{TAG} Error: {e}")

        finally:
            self.worker.editor_logging_handler.info(f"{TAG} Clean up")

            self.worker.music_mode_stop_event.set()

            if stream_task:
                stream_task.cancel()
            if events_task:
                events_task.cancel()

            await self.capability_worker.send_data_over_websocket("music-mode", {"mode": "off"})
            self.worker.music_mode_event.clear()
            self.worker.music_mode_stop_event.clear()

            self.worker.editor_logging_handler.info(f"{TAG} Radio OFF")

            await self.worker.session_tasks.sleep(1)
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        try:
            self.worker = worker
            self.capability_worker = CapabilityWorker(self.worker)
            self.worker.editor_logging_handler.info(f"{TAG} Radio ON")

            self.worker.session_tasks.create(self.run())
        except Exception as e:
            self.worker.editor_logging_handler.warning(e)
