import asyncio
import httpx

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

STREAM_URL = "https://api.kortexa.ai/radio/stream"
EVENTS_URL = "https://api.kortexa.ai/radio/events"
CHUNK_SIZE = 25 * 1024
TAG = "[KortexaRadio]"

CONTINUE_PROMPT = "Say 'play' to start the radio, or 'stop' to exit."


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
                            await asyncio.sleep(0.1)

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

                await asyncio.sleep(5)
        except asyncio.CancelledError as e:
            self.worker.editor_logging_handler.error(f"{TAG} SSE cancelled: {e}")

            pass

    async def run(self):
        """Main setup and conversation loop."""

        first_time = True
        is_playing = False
        is_stopping = False
        events_task = None

        # await self.capability_worker.wait_for_complete_transcription()

        # self.worker.music_mode_event.set()
        # await self.capability_worker.send_data_over_websocket("music-mode", {"mode": "on"})

        # await asyncio.sleep(5)

        # await self.capability_worker.send_data_over_websocket("music-mode", {"mode": "off"})
        # self.worker.music_mode_event.clear()

        # await self.capability_worker.speak("Nope, don't want to")

        # await asyncio.sleep(1)

        # self.capability_worker.resume_normal_flow()

        try:
            while True:
                if is_stopping:
                    self.worker.editor_logging_handler.info(f"{TAG} Waiting for stream to finish")

                    await asyncio.sleep(0.1)

                    if not events_task:
                        self.worker.editor_logging_handler.info(f"{TAG} No events task")

                        break

                    continue

                if first_time:
                    self.worker.editor_logging_handler.info(f"{TAG} First trigger")

                    msg = "start"
                    first_time = False
                else:
                    self.worker.editor_logging_handler.info(f"{TAG} Interruption")

                    msg = await self.capability_worker.user_response()

                if not msg or not msg.strip():
                    self.worker.editor_logging_handler.info(f"{TAG} User silent")

                    if is_playing:
                        msg = "stop"
                    else:
                        msg = "start"

                normalized = msg.strip().lower()

                self.worker.editor_logging_handler.info(f"{TAG} Command: {normalized}")

                if "stop" in normalized or "off" in normalized:
                    is_stopping = True

                    self.worker.editor_logging_handler.info(f"{TAG} Stop stream")

                    self.worker.music_mode_stop_event.set()

                    self.worker.editor_logging_handler.info(f"{TAG} Turn off music mode")

                    await self.capability_worker.send_data_over_websocket("music-mode", {"mode": "off"})
                    self.worker.music_mode_event.clear()

                elif "play" in normalized or "start" in normalized or "on" in normalized or "radio" in normalized:
                    self.worker.editor_logging_handler.info(f"{TAG} Start playing")

                    is_playing = True

                    await self.capability_worker.speak("Tuning in to Kortexa Radio.")

                    # Subscribe to events (registers us as a listener)
                    self.worker.editor_logging_handler.info(f"{TAG} Register as a listener")
                    events_task = self.worker.session_tasks.create(self._keep_events_connected())

                    self.worker.editor_logging_handler.info(f"{TAG} Turn on music mode")

                    self.worker.music_mode_event.set()
                    await self.capability_worker.send_data_over_websocket("music-mode", {"mode": "on"})

                    # Stream audio (blocks until stop event or error)
                    await self._stream()

                    if events_task:
                        self.worker.editor_logging_handler.info(f"{TAG} Unregister as a listener")

                        events_task.cancel()
                        events_task = None

                    await self.capability_worker.speak("Radio off! Catch you later.")

                    self.worker.music_mode_stop_event.clear()

                    is_playing = False

                    self.worker.editor_logging_handler.info(f"{TAG} Stop playing")

                    break

        except Exception as e:
            self.worker.editor_logging_handler.error(f"{TAG} Error: {e}")

        finally:
            self.worker.editor_logging_handler.info(f"{TAG} Clean up")

            if events_task:
                self.worker.editor_logging_handler.info(f"{TAG} Unregister as a listener")

                events_task.cancel()
                events_task = None

            if is_playing:
                self.worker.editor_logging_handler.info(f"{TAG} Turn off music mode")

                await self.capability_worker.send_data_over_websocket("music-mode", {"mode": "off"})
                self.worker.music_mode_event.clear()

            self.worker.editor_logging_handler.info(f"{TAG} Radio OFF")

            await asyncio.sleep(1)
            self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        try:
            self.worker = worker
            self.capability_worker = CapabilityWorker(self.worker)
            self.worker.editor_logging_handler.info(f"{TAG} Radio ON")

            self.worker.session_tasks.create(self.run())
        except Exception as e:
            self.worker.editor_logging_handler.warning(e)
