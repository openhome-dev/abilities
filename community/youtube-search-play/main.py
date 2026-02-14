"""
YouTube Search & Play — OpenHome Voice Ability
Searches YouTube and plays audio via voice command.
Uses two RapidAPI services (both have free tiers):
1. YouTube Search API (by Elis) - for searching
2. YouTube MP3 (by ytjar) - for getting direct audio URL
"""

import asyncio
import hashlib
import json
import os
import re
from typing import Optional, Dict

import requests
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# RapidAPI Configuration
# Get your free API key at: https://rapidapi.com
# Same key works for both APIs
RAPIDAPI_KEY = "6426a44151mshd127f11cad8339ap167bb3jsn1e08fc0ffaea"
# Your RapidAPI username (profile name) - required to fix 404 when streaming MP3
# Find it at: https://rapidapi.com/developer/app - or your profile URL
RAPIDAPI_USERNAME = "ammyyou112"

# API 1: YouTube Search API (by Elis)
SEARCH_API_HOST = "youtube-search-api.p.rapidapi.com"

# API 2: YouTube MP3 (by ytjar) - direct audio URL
DOWNLOAD_API_HOST = "youtube-mp36.p.rapidapi.com"
DOWNLOAD_API_URL = f"https://{DOWNLOAD_API_HOST}/dl"

# Max retries when API returns "processing" status
MAX_PROCESSING_RETRIES = 3

# Exit words
EXIT_WORDS = ["stop", "exit", "quit", "done", "cancel", "pause", "end"]


class YouTubePlayCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

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

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run_youtube_flow())

    def _search_youtube(self, query: str) -> Optional[Dict]:
        """
        Search YouTube for a video using YouTube Search API.
        Returns video info (title, url, channel) or None on failure.
        """
        try:
            url = f"https://{SEARCH_API_HOST}/search"

            headers = {
                "X-RapidAPI-Key": RAPIDAPI_KEY,
                "X-RapidAPI-Host": SEARCH_API_HOST
            }

            payload = {
                "search_query": query
            }

            self.worker.editor_logging_handler.info(f"Searching YouTube for: {query}")

            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=10
            )

            if response.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"YouTube Search API error: {response.status_code}"
                )
                return None

            data = response.json()
            # Some APIs wrap results in "contents" or "items"
            if isinstance(data, dict):
                data = data.get("contents") or data.get("items") or data.get("results") or []
            # Get first video result
            if isinstance(data, list) and len(data) > 0:
                item = data[0]
                # Some APIs nest video data under "video" key
                video = item.get("video", item) if isinstance(item, dict) else item
                # Elis API may return url, link, or video_id in different formats
                video_url = (
                    video.get("url")
                    or video.get("link")
                    or video.get("videoUrl")
                )
                # Build URL from video_id if URL not present
                if not video_url:
                    vid = video.get("video_id") or video.get("videoId") or video.get("id")
                    if vid:
                        video_url = f"https://www.youtube.com/watch?v={vid}"
                # Extract from thumbnail URL if still missing (e.g. i.ytimg.com/vi/VIDEO_ID/...)
                if not video_url:
                    thumb = video.get("thumbnail")
                    if not thumb and isinstance(video.get("thumbnails"), dict):
                        t = video["thumbnails"]
                        thumb = t.get("url") or (t.get("high") or {}).get("url") or (t.get("default") or {}).get("url")
                    if thumb and "/vi/" in str(thumb):
                        vid = self._extract_video_id(str(thumb))
                        if vid:
                            video_url = f"https://www.youtube.com/watch?v={vid}"
                channel = video.get("channel")
                channel_name = (
                    channel.get("name", "Unknown")
                    if isinstance(channel, dict)
                    else (channel if channel else "Unknown")
                )
                video_info = {
                    "title": video.get("title", "Unknown"),
                    "url": video_url or "",
                    "channel": channel_name,
                    "duration": video.get("duration", ""),
                }

                self.worker.editor_logging_handler.info(
                    f"Found: {video_info['title']} by {video_info['channel']}"
                )

                return video_info

            return None

        except Exception as e:
            self.worker.editor_logging_handler.error(f"YouTube search error: {e}")
            return None

    def _extract_video_id(self, youtube_url: str) -> Optional[str]:
        """
        Extract YouTube video ID from URL or raw ID.
        Supports: watch?v=ID, youtu.be/ID, embed/ID, raw 11-char ID.
        """
        if not youtube_url or not youtube_url.strip():
            return None
        s = youtube_url.strip()
        # Already a raw 11-char video ID
        if re.match(r"^[a-zA-Z0-9_-]{11}$", s):
            return s
        # watch?v=VIDEO_ID or /v/VIDEO_ID
        match = re.search(r"[?&]v=([a-zA-Z0-9_-]{11})", s)
        if match:
            return match.group(1)
        match = re.search(r"/v/([a-zA-Z0-9_-]{11})", s)
        if match:
            return match.group(1)
        # youtu.be/VIDEO_ID
        match = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", s)
        if match:
            return match.group(1)
        # embed/VIDEO_ID or /embed/VIDEO_ID
        match = re.search(r"embed/([a-zA-Z0-9_-]{11})", s)
        if match:
            return match.group(1)
        # ytimg.com/vi/VIDEO_ID (thumbnail URLs)
        match = re.search(r"/vi/([a-zA-Z0-9_-]{11})", s)
        if match:
            return match.group(1)
        # Fallback: any 11-char YouTube ID in string
        match = re.search(r"([a-zA-Z0-9_-]{11})", s)
        if match:
            return match.group(1)
        return None

    async def _get_audio_url(self, youtube_url: str) -> Optional[str]:
        """
        Get audio download URL using YouTube MP3 API.
        Handles "processing" status with 1-second retry.
        Returns direct audio URL or None on failure.
        """
        video_id = self._extract_video_id(youtube_url)
        if not video_id:
            preview = str(youtube_url)[:80] + ("..." if len(str(youtube_url)) > 80 else "")
            self.worker.editor_logging_handler.error(
                f"Could not extract video ID from URL: {preview!r}"
            )
            return None

        headers = {
            "X-RapidAPI-Key": RAPIDAPI_KEY,
            "X-RapidAPI-Host": DOWNLOAD_API_HOST,
        }

        for attempt in range(MAX_PROCESSING_RETRIES):
            try:
                self.worker.editor_logging_handler.info(
                    f"Getting audio URL (attempt {attempt + 1}/{MAX_PROCESSING_RETRIES})..."
                )

                response = await asyncio.to_thread(
                    requests.get,
                    DOWNLOAD_API_URL,
                    headers=headers,
                    params={"id": video_id},
                    timeout=15,
                )

                if response.status_code != 200:
                    self.worker.editor_logging_handler.error(
                        f"Failed to get audio URL: {response.status_code}"
                    )
                    return None

                data = response.json()

                if not isinstance(data, dict):
                    return None

                status = data.get("status", "")
                link = data.get("link")

                if status == "ok" and link:
                    self.worker.editor_logging_handler.info("Got audio URL successfully")
                    return link

                if status == "fail":
                    self.worker.editor_logging_handler.error(
                        f"API conversion failed: {data.get('msg', 'Unknown error')}"
                    )
                    return None

                if status == "processing":
                    if attempt < MAX_PROCESSING_RETRIES - 1:
                        await asyncio.sleep(1)
                    else:
                        self.worker.editor_logging_handler.error(
                            "Audio still processing after max retries"
                        )
                        return None

            except Exception as e:
                self.worker.editor_logging_handler.error(f"Audio URL error: {e}")
                return None

        return None

    async def _play_video(self, video_info: Dict) -> bool:
        """
        Play the video audio.
        Returns True on success, False on failure.
        """
        try:
            # Run announcement and API call in parallel to reduce wait time
            _, audio_url = await asyncio.gather(
                self.capability_worker.speak(
                    f"Playing {video_info['title']} by {video_info['channel']}"
                ),
                self._get_audio_url(video_info["url"]),
            )

            if not audio_url:
                self.worker.editor_logging_handler.error("Failed to get audio URL")
                return False

            # Enter music mode
            self.worker.music_mode_event.set()
            await self.capability_worker.send_data_over_websocket(
                "music-mode",
                {"mode": "on"}
            )
            # Brief delay for audio routing to switch before streaming
            await asyncio.sleep(0.5)

            # Stream the audio (wrap blocking request in asyncio.to_thread)
            # YouTube MP3 API requires whitelist headers to avoid 404 on secure links
            self.worker.editor_logging_handler.info("Starting audio stream")
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            stream_headers = {
                "User-Agent": user_agent,
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.youtube.com/",
            }
            # Whitelist to fix 404 - append username to User-Agent, add X-RUN with MD5
            if RAPIDAPI_USERNAME:
                stream_headers["User-Agent"] = f"{user_agent} {RAPIDAPI_USERNAME}"
                stream_headers["X-RUN"] = hashlib.md5(
                    RAPIDAPI_USERNAME.encode("utf-8")
                ).hexdigest()
            audio_response = await asyncio.to_thread(
                requests.get,
                audio_url,
                headers=stream_headers,
                stream=True,
                timeout=30,
                allow_redirects=True,
            )

            status = audio_response.status_code
            content_length = audio_response.headers.get("Content-Length", "unknown")
            content_type = audio_response.headers.get("Content-Type", "unknown")
            self.worker.editor_logging_handler.info(
                f"Stream response: status={status}, content-type={content_type}, "
                f"content-length={content_length}"
            )

            # Reject HTML responses (some CDNs return 200 with error page)
            if status == 200 and "text/html" in str(content_type).lower():
                self.worker.editor_logging_handler.error(
                    "Stream returned HTML instead of audio - URL may be invalid"
                )
                return False

            if status == 200:
                await self.capability_worker.stream_init()
                # SDK expects bytes, not Response object (per Audius DJ pattern)
                audio_data = await asyncio.to_thread(lambda: audio_response.content)
                CHUNK_SIZE = 25 * 1024  # 25 KB, same as Audius DJ

                chunk_start = 0
                while chunk_start < len(audio_data):
                    # Stop check
                    if (
                        hasattr(self.worker, "music_mode_stop_event")
                        and self.worker.music_mode_stop_event.is_set()
                    ):
                        self.worker.editor_logging_handler.info(
                            "Stop requested, ending playback"
                        )
                        await self.capability_worker.stream_end()
                        return True

                    # Pause check - wait until user says "continue"
                    if hasattr(self.worker, "music_mode_pause_event"):
                        while self.worker.music_mode_pause_event.is_set():
                            await asyncio.sleep(0.1)
                            if (
                                hasattr(self.worker, "music_mode_stop_event")
                                and self.worker.music_mode_stop_event.is_set()
                            ):
                                await self.capability_worker.stream_end()
                                return True

                    chunk = audio_data[chunk_start : chunk_start + CHUNK_SIZE]
                    if chunk:
                        await self.capability_worker.send_audio_data_in_stream(
                            chunk
                        )
                    chunk_start += CHUNK_SIZE

                await self.capability_worker.stream_end()
                self.worker.editor_logging_handler.info("Audio stream completed")

                # Exit music mode
                await self.capability_worker.send_data_over_websocket(
                    "music-mode",
                    {"mode": "off"}
                )
                self.worker.music_mode_event.clear()

                return True
            else:
                self.worker.editor_logging_handler.error(
                    f"Failed to stream audio: {audio_response.status_code}"
                )
                return False

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Playback error: {e}")

            # Clean up music mode on error
            try:
                await self.capability_worker.send_data_over_websocket(
                    "music-mode",
                    {"mode": "off"}
                )
                self.worker.music_mode_event.clear()
            except Exception:
                pass

            return False

    async def run_youtube_flow(self):
        """Main YouTube search and play flow."""
        try:
            await self.capability_worker.speak(
                "What would you like to play from YouTube?"
            )

            while True:
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    await self.capability_worker.speak(
                        "I didn't catch that. What should I search for?"
                    )
                    continue

                # Check for exit
                if any(word in user_input.lower() for word in EXIT_WORDS):
                    await self.capability_worker.speak("Okay, stopping YouTube.")
                    break

                # Search YouTube
                await self.capability_worker.speak("Searching YouTube...")

                video_info = await asyncio.to_thread(
                    self._search_youtube, user_input
                )

                if not video_info:
                    # Fallback: Ask LLM for alternative query
                    await self.capability_worker.speak(
                        "I couldn't find that. Let me try a different search."
                    )

                    # Get LLM to rephrase the query
                    prompt = f"""User wants to play: "{user_input}"
The search failed. Suggest a better YouTube search query.
Reply with ONLY the search query, nothing else."""

                    alt_query = self.capability_worker.text_to_text_response(prompt)
                    alt_query = alt_query.strip().strip('"').strip("'")

                    self.worker.editor_logging_handler.info(
                        f"Trying alternative query: {alt_query}"
                    )

                    video_info = await asyncio.to_thread(
                        self._search_youtube, alt_query
                    )

                    if not video_info:
                        await self.capability_worker.speak(
                            "Sorry, I couldn't find that video. Try another search or say stop."
                        )
                        continue

                # Try to play
                success = await self._play_video(video_info)

                if success:
                    await self.capability_worker.speak(
                        "Done playing. Want to play something else?"
                    )
                else:
                    await self.capability_worker.speak(
                        "Sorry, I couldn't play that video. The audio might not be available. "
                        "Try another search or say stop."
                    )

        except Exception as e:
            self.worker.editor_logging_handler.error(f"YouTube ability error: {e}")
            await self.capability_worker.speak(
                "Something went wrong with YouTube. Try again later."
            )
        finally:
            # Make sure music mode is off
            try:
                await self.capability_worker.send_data_over_websocket(
                    "music-mode",
                    {"mode": "off"}
                )
                self.worker.music_mode_event.clear()
            except Exception:
                pass

            self.capability_worker.resume_normal_flow()
