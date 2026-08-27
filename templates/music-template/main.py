import json
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# MUSIC TEMPLATE
# For Abilities that play a track and stay in control of what happens next.
# Pattern: resolve a link -> stream_music_from_url() -> branch on outcome
#
# stream_music_from_url() blocks until playback genuinely ends and tells you
# why it ended. The audio pipeline, the device buffer, music mode and the
# recovery afterwards are all inside the call, so speak() works on the very
# next line no matter how it ended.
#
# Replace MUSIC_API, search_track() and stream_url() with your music service.
# =============================================================================

# Replace with your music service.
MUSIC_API = "https://api.example.com"


class MusicDocsCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    # Do not change following tag of register capability
    #{{register capability}}
    async def play_music(self, request: str):
        if not request:
            await self.capability_worker.speak("What would you like to hear?")
            request = await self.capability_worker.user_response()

        track = self.search_track(request)

        if track:
            position, offset = 0.0, 0
            while True:
                # Re-resolved on every pass, resumes included: signed stream
                # links expire while the user sits paused.
                url = self.stream_url(track)
                result = await self.capability_worker.stream_music_from_url(
                    url,
                    duration_seconds=track["duration"],
                    start_seconds=position,
                    byte_offset=offset,
                    announce=f"Playing {track['title']}." if position == 0.0 else "",
                )
                position, offset = result["position"], result["byte_offset"]

                # Only a pause continues the loop. finished, stopped, error and
                # unplayable all leave.
                if result["outcome"] != "paused":
                    break

                reply = await self.capability_worker.run_io_loop(
                    "Paused. Say resume or stop."
                )
                if "resume" not in (reply or "").lower():
                    break

            await self.capability_worker.speak("Okay, that's it for the music.")
        else:
            await self.capability_worker.speak("I couldn't find that one. Try again.")

        self.capability_worker.resume_normal_flow()

    def search_track(self, request: str):
        result = self.worker.session_tasks.get(
            f"{MUSIC_API}/search?q={request}&limit=1"
        ).json()
        tracks = result.get("tracks") or []
        if not tracks:
            return None
        track = tracks[0]
        return {
            "id": track["id"],
            "title": track["title"],
            "duration": track["duration_ms"] / 1000.0,   # FULL track length
        }

    def stream_url(self, track):
        result = self.worker.session_tasks.get(
            f"{MUSIC_API}/tracks/{track['id']}/stream"
        ).json()
        return result["mp3_url"]                          # progressive mp3

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self)
        self.worker.session_tasks.create(self.play_music(""))
