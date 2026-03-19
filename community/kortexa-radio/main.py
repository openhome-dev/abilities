"""OpenHome skill — Kortexa Radio.

Trigger word: "start radio"

Streams AI-generated radio from radio.kortexa.ai.
Stream runs in a session task. Main flow monitors for stop event
and cleans up properly so the agent regains control.
"""

import asyncio
import httpx
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

STREAM_URL = "https://api.kortexa.ai/radio/stream"
TAG = "[KortexaRadio]"
CHUNK_SIZE = 25 * 1024


class KortexaRadioCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    _streaming = False

    # Do not change following tag of register capability
    #{{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def run(self):
        try:
            await self.capability_worker.speak("Tuning in to Kortexa Radio.")

            self.worker.music_mode_event.set()
            await self.capability_worker.send_data_over_websocket("music-mode", {"mode": "on"})

            # Launch streaming in a separate task
            KortexaRadioCapability._streaming = True
            stream_task = self.worker.session_tasks.create(self._stream())

            # Monitor for stop event
            while KortexaRadioCapability._streaming:
                if self.worker.music_mode_stop_event.is_set():
                    self.worker.editor_logging_handler.info(f"{TAG} Stop event detected")
                    KortexaRadioCapability._streaming = False
                    break
                await self.worker.session_tasks.sleep(0.5)

            # Cancel the stream task
            if stream_task:
                stream_task.cancel()

            self.worker.editor_logging_handler.info(f"{TAG} Cleaning up")

        except Exception as e:
            self.worker.editor_logging_handler.error(f"{TAG} Error: {e}")
        finally:
            KortexaRadioCapability._streaming = False
            try:
                await self.capability_worker.stream_end()
            except Exception:
                pass
            try:
                await self.capability_worker.send_data_over_websocket("music-mode", {"mode": "off"})
            except Exception:
                pass
            self.worker.music_mode_event.clear()
            self.worker.music_mode_stop_event.clear()
            self.capability_worker.resume_normal_flow()
            self.worker.editor_logging_handler.info(f"{TAG} Done, control returned")

    async def _stream(self):
        """Stream audio in a cancellable task."""
        try:
            self.worker.editor_logging_handler.info(f"{TAG} Connecting...")
            await self.capability_worker.stream_init()

            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", STREAM_URL, follow_redirects=True) as response:
                    self.worker.editor_logging_handler.info(f"{TAG} Connected, status={response.status_code}")

                    if response.status_code != 200:
                        KortexaRadioCapability._streaming = False
                        return

                    async for chunk in response.aiter_bytes(chunk_size=CHUNK_SIZE):
                        if not chunk:
                            continue
                        if not KortexaRadioCapability._streaming:
                            break

                        while self.worker.music_mode_pause_event.is_set():
                            await asyncio.sleep(0.1)

                        await self.capability_worker.send_audio_data_in_stream(chunk)

        except asyncio.CancelledError:
            self.worker.editor_logging_handler.info(f"{TAG} Stream task cancelled")
        except Exception as e:
            self.worker.editor_logging_handler.error(f"{TAG} Stream error: {e}")
        finally:
            KortexaRadioCapability._streaming = False
