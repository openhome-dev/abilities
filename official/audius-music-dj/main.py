import logging
import os
import json
import httpx
import asyncio
import requests
import re

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# API configuration
AUDIUS_API = "https://api.audius.co"

# Prompts
CONTINUE_PROMPT = "What would you like me to do next? You can say 'PLAY SOMETHING SIMILAR', 'ADD TO FAVORITES','PLAY MY FAVORITES', or 'STOP' to exit."
ERROR_PROMPT = "Sorry, I couldn't play the song at this moment."

# Full official genres (Audius is case-sensitive!)
AUDIUS_GENRES = {
    "alternative": "Alternative",
    "ambient": "Ambient",
    "acoustic": "Acoustic",
    "audiobooks": "Audiobooks",
    "blues": "Blues",
    "comedy": "Comedy",
    "country": "Country",
    "dancehall": "Dancehall",
    "devotional": "Devotional",
    "electronic": "Electronic",
    "experimental": "Experimental",
    "folk": "Folk",
    "hip-hop/rap": "Hip-Hop/Rap",
    "hyperpop": "Hyperpop",
    "indie": "Indie",
    "jazz": "Jazz",
    "kids": "Kids",
    "latin": "Latin",
    "lo-fi": "Lo-Fi",
    "metal": "Metal",
    "mood": "Mood",
    "podcasts": "Podcasts",
    "pop": "Pop",
    "punk": "Punk",
    "r&b/soul": "R&B/Soul",
    "reggae": "Reggae",
    "rock": "Rock",
    "soundtrack": "Soundtrack",
    "spoken word": "Spoken Word",
    "world": "World",
    "classical": "Classical",
    "funk": "Funk",
    "other": "Other"
}

# Aliases for genres → canonical keys
GENRE_ALIASES = {
    "hip hop": "hip-hop/rap",
    "hiphop": "hip-hop/rap",
    "hip-hop": "hip-hop/rap",
    "rap": "hip-hop/rap",
    "rnb": "r&b/soul",
    "r&b": "r&b/soul",
    "soul": "r&b/soul",
    "spoken": "spoken word",
    "lofi": "lo-fi",
    "rb": "r&b/soul",
    "randb": "r&b/soul",
    "electro": "electronic",
    "alt": "alternative"
}

# Full moods
AUDIUS_MOODS = {
    "aggressive": "Aggressive",
    "brooding": "Brooding",
    "cool": "Cool",
    "defiant": "Defiant",
    "easygoing": "Easygoing",
    "empowering": "Empowering",
    "energizing": "Energizing",
    "excited": "Excited",
    "fiery": "Fiery",
    "gritty": "Gritty",
    "melancholy": "Melancholy",
    "other": "Other",
    "peaceful": "Peaceful",
    "romantic": "Romantic",
    "rowdy": "Rowdy",
    "sensual": "Sensual",
    "sentimental": "Sentimental",
    "serious": "Serious",
    "sophisticated": "Sophisticated",
    "stirring": "Stirring",
    "tender": "Tender",
    "upbeat": "Upbeat",
    "yearning": "Yearning"
}

# Aliases for moods
MOOD_ALIASES = {
    "chill": "easygoing",
    "relaxed": "easygoing",
    "calm": "peaceful",
    "love": "romantic",
    "sad": "melancholy",
    "happy": "upbeat",
    "party": "rowdy",
    "angry": "aggressive",
    "cool vibe": "cool",
    "sexy": "sensual"
}


class AudiusMusicDjCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    host: str = None
    app_name: str = "ability"

    # Class-level context (shared across songs & sessions)
    global_context: dict = {
        "last_song_id": None,
        "context_summary": None,
        "last_played_message": None
    }
    
    # Store played songs inside the class
    played_songs: dict = {
        "titles": []
    }

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

    def _get_host(self):
        """Get the best available host from Audius"""
        try:
            response = requests.get(AUDIUS_API)
            if response.status_code == 200:
                return response.json().get('data')[0]
            return None
        except Exception as e:
            self.worker.editor_logging_handler.error(f"Error getting host: {str(e)}")
            return None

    async def stream_audio_simple_2(self, stream_response):
        """
        Stream audio chunks directly as they arrive from the server,
        with correct pause/stop handling.
        """
        try:
            self.worker.editor_logging_handler.info("🔊 Stream initialized (direct mode) before")
            await self.capability_worker.stream_init()
            self.worker.editor_logging_handler.info("🔊 Stream initialized (direct mode) after")

            # Stream incoming audio chunks
            async for chunk in stream_response.aiter_bytes(chunk_size=25*1024):
                if not chunk:
                    continue

                # Stop check
                if self.worker.music_mode_stop_event.is_set():
                    self.worker.editor_logging_handler.error("[Direct] Stop event triggered, stopping playback.")
                    await self.capability_worker.stream_end()
                    return

                # Pause check
                while self.worker.music_mode_pause_event.is_set():
                    self.worker.editor_logging_handler.info("[Direct] Pause active...waiting")
                    await asyncio.sleep(0.1)

                # Send the chunk directly as soon as received
                self.worker.editor_logging_handler.warning("Sending audio chunk to stream")
                await self.capability_worker.send_audio_data_in_stream(chunk)
                self.worker.editor_logging_handler.warning("Sent audio chunk to stream %s" % len(chunk))

            # End normally
            await self.capability_worker.stream_end()
            self.worker.editor_logging_handler.info("🎵 Stream ended cleanly (direct mode)")

        except Exception as e:
            self.worker.editor_logging_handler.error(f"❌ Error streaming audio (direct mode): {str(e)}")
            await self.capability_worker.speak(ERROR_PROMPT)

    def normalize_genre(self, raw: str | None) -> str | None:
        """Normalize genre string to Audius format"""
        if not raw:
            return None
        key = raw.strip().lower()
        if key in GENRE_ALIASES:
            key = GENRE_ALIASES[key]
        return AUDIUS_GENRES.get(key)

    def normalize_mood(self, raw: str | None) -> str | None:
        """Normalize mood string to Audius format"""
        if not raw:
            return None
        key = raw.strip().lower()
        if key in MOOD_ALIASES:
            key = MOOD_ALIASES[key]
        return AUDIUS_MOODS.get(key)

    def _initialize_played_songs(self):
        """Initialize or sync played_songs from storage"""
        response = self.capability_worker.get_single_key("played_songs")

        if response.get("key", "") == "":
            self.capability_worker.create_key("played_songs", {"titles": []})
            self.played_songs = {"titles": []}
        else:
            self.played_songs = response.get("value", {"titles": []})

    def _update_played_songs(self, title: str):
        """Add a song title to played songs and persist"""
        if title and title not in self.played_songs["titles"]:
            self.played_songs["titles"].append(title)

        # Keep last 20 songs only
        if len(self.played_songs["titles"]) > 20:
            self.played_songs["titles"].pop(0)

        response = self.capability_worker.update_key("played_songs", self.played_songs)
        self.worker.editor_logging_handler.info(f"[Update] played_songs response: {response}")
        self.worker.editor_logging_handler.info(f"Updated Played Songs -> {self.played_songs}")

    def _update_global_context(self, selected_track: dict, request_dict: dict):
        """Update global context after playing a song"""
        self.global_context["last_song_id"] = selected_track["id"]
        self.global_context["last_played_message"] = (
            f"Now playing {selected_track.get('title')} by {selected_track['user'].get('name')}."
        )

        if request_dict.get("session", False) or not request_dict.get("use_context", False):
            self.global_context["context_summary"] = request_dict.get(
                "summary", self.global_context["context_summary"]
            )

        self.worker.editor_logging_handler.error(f"Updated Context -> {self.global_context}")

        response = self.capability_worker.update_key("global_context", self.global_context)
        self.worker.editor_logging_handler.info(f"✅ Updated global_context in DB -> {response}")

    async def play_song(self, request_dict: dict):
        """Play a song based on a structured request dict"""
        try:
            await self.capability_worker.speak("I am searching a song for you, please wait!")

            # Build query from structured fields
            details = request_dict.get("details", {}) or {}
            song = details.get("song")
            artist = details.get("artist")
            genre = self.normalize_genre(details.get("genre"))
            mood = self.normalize_mood(details.get("mood"))
            context = details.get("context")
            time_era = details.get("time_era")

            # Initialize played songs
            self._initialize_played_songs()
            already_played_titles = self.played_songs["titles"][-5:]

            # Priority: exact song + artist > song > artist > genre > mood/context/era
            query_parts = []
            if song and artist:
                query_parts = [song, artist]
            elif song:
                query_parts = [song]
            elif artist:
                query_parts = [artist]
            else:
                soft = " ".join(p for p in [context, time_era] if p)
                if soft:
                    query_parts = [soft]

            search_query = " ".join(p for p in query_parts if p).strip()
            self.worker.editor_logging_handler.info(f"Search query built from dict: {search_query!r}")

            # GPT fallback if no query/filters
            if not search_query and not genre and not mood:
                summary = request_dict.get("summary", "").strip()

                gpt_prompt = f"""
                You MUST return only the name of a single song.
                Do not include the artist name, explanations, punctuation, quotes, or any additional text.

                The user gave this summary for music preference: "{summary}"

                Return ONLY the song title on one line.
                """

                search_query = self.capability_worker.text_to_text_response(gpt_prompt, [])
                search_query = (search_query or "").strip()
                self.worker.editor_logging_handler.info(f"🎯 GPT-generated query: {search_query!r}")

            # Build params for Audius
            params = {
                "query": search_query,
                "app_name": self.app_name,
                "limit": 5
            }

            if genre:
                params["genre"] = genre
            if mood:
                params["mood"] = mood

            self.worker.editor_logging_handler.info(f"[Audius Params] -> {params}")

            # Search tracks on Audius
            search_endpoint = f"{self.host}/v1/tracks/search"
            response = requests.get(
                search_endpoint,
                params=params,
                headers={
                    "Accept": "application/json",
                    "User-Agent": f"{self.app_name}/1.0"
                }
            )

            if response.status_code == 200:
                tracks = response.json().get("data", [])
                
                # Fallback with GPT suggestion if no tracks found
                if not tracks:
                    summary = request_dict.get("summary", "").strip()

                    gpt_prompt = f"""
                        The user gave this summary for music preference: "{summary}".

                        Suggest ONE most popular song title that best matches this preference.
                        Do NOT suggest any of these songs that have been played recently: {already_played_titles}.
                        Do not explain, return ONLY the song name.
                    """

                    search_query = self.capability_worker.text_to_text_response(gpt_prompt, [])
                    search_query = (search_query or "").strip()
                    
                    if search_query:
                        params["query"] = search_query
                        response = requests.get(search_endpoint, params=params, headers={
                            "Accept": "application/json",
                            "User-Agent": f"{self.app_name}/1.0"
                        })
                        tracks = response.json().get("data", [])
                    
                    if not tracks:
                        await self.capability_worker.speak(
                            "Sorry, I couldn't find any tracks for that request even after trying a suggestion."
                        )
                        return

                # Let LLM pick best track
                track_list = "\n".join([
                    f"{i+1}. {t.get('title','')} by {t.get('user',{}).get('name','')}, genre: {t.get('genre','Unknown')}"
                    for i, t in enumerate(tracks)
                ])
                
                selection_prompt = f"""
                    User request: {request_dict}
                    Tracks:
                    {track_list}

                    Pick the BEST matching track number (1-5), making sure NOT to pick any of these recently played songs: {already_played_titles}.
                    Return ONLY the number.
                """
                
                choice = self.capability_worker.text_to_text_response(selection_prompt, [])
                self.worker.editor_logging_handler.info(f"Track choice: {choice}")

                try:
                    idx = int(choice.strip()) - 1
                    if 0 <= idx < len(tracks):
                        selected = tracks[idx]
                        stream_url = f"{self.host}/v1/tracks/{selected['id']}/stream"

                        async with httpx.AsyncClient(timeout=None) as client:
                            async with client.stream("GET", stream_url, follow_redirects=True) as stream_response:

                                self.worker.editor_logging_handler.error(
                                    f"[STREAM DEBUG] status={stream_response.status_code}"
                                )

                                if stream_response.status_code == 200:
                                    await self.capability_worker.speak(
                                        f"Now playing {selected['title']} by {selected['user']['name']}."
                                    )

                                    formatted_song_data = {
                                        "title": selected.get("title", ""),
                                        "artist": (selected.get("user") or {}).get("name", ""),
                                        "image": (selected.get("artwork") or {}).get("480x480", ""),
                                        "genre": selected.get("genre", ""),
                                        "mood": selected.get("mood", ""),
                                        "release_date": selected.get("release_date", "")
                                    }
                                    self.worker.editor_logging_handler.info(formatted_song_data)

                                    await self.capability_worker.send_data_over_websocket(
                                        data_type="audius_song_playing",
                                        data=formatted_song_data
                                    )

                                    await self.stream_audio_simple_2(stream_response)

                                    # Update context and played songs
                                    self._update_global_context(selected, request_dict)
                                    self._update_played_songs(selected.get("title"))
                                    return

                                self.worker.editor_logging_handler.info("Hello lag check")

                except Exception as e:
                    self.worker.editor_logging_handler.error(f"Selection failed: {e}")

                await self.capability_worker.speak("I couldn't pick the right track, please try again.")
            else:
                await self.capability_worker.speak("Error reaching the music service, please try later.")

        except Exception as e:
            self.worker.editor_logging_handler.error(f"Error in play_song: {e}")
            await self.capability_worker.speak("Sorry, something went wrong while searching for a song.")

    async def check_song_request(self, message: str) -> dict:
        """Check if the message contains a song request"""
        check_prompt = f"""
        You are a DJ assistant.  
        Your job is to analyze the user's request and return a JSON object ONLY in the following schema:

        {{
        "intent": "<intent>",
        "details": {{
            "genre": null,
            "artist": null,
            "song": null,
            "mood": null,
            "context": null,
            "time_era": null,
            "extra": null
        }},
        "summary": "",
        "needs_more_info": false,
        "use_context": false,
        "session": false
        }}

        ---

        ### INTENTS (choose only one):
        - "direct_play"
        - "stop"
        - "pause" → pause / hold / stop for now
        - "resume" → resume / continue / pick up where we left off / carry on
        - "add_to_favorites"
        - "remove_from_favorites"
        - "play_favorites"
        - "conversation"

        ---

        ### RULES
        1. Respond with **only valid JSON**. No text, no markdown, no explanations.  
        2. Always fill all fields. Use `null` when a detail is not provided.  
        3. If the user asks to "play" music (even vaguely, e.g., "Play some vibes", "Play music for tonight"), always map to "direct_play".  
        Do not classify as "conversation".
        4. Set `"needs_more_info" = true` only if the request is too vague to act on (e.g., "Play", "Play music", "Play something") with no actionable instruction. Do **not** mark as needing more info if the user asks for continuation 
           (e.g., "Play another song", "Next", "Something else", "Keep going"). In those cases, set `"needs_more_info" = false` and `"use_context" = true`.
        5. For vague requests with at least some hint (mood, time, vibe), fill that detail and set "needs_more_info" = false.  
        6. Set "needs_more_info" = true if the request is too vague (e.g., "Play", "Play music", "Play something") and does not specify any detail such as genre, artist, mood, time, or context.  
        7. `"summary"` must be a short natural language description.  
        8. If the user requests something similar to the last song (e.g., "more like this", "something similar", "continue this mood"), map to `"direct_play"` and set `"use_context": true`.  
        9. `"use_context"` = false otherwise.  
        10. `"session"` = true if the user's request establishes a broader theme for multiple songs (artist, genre, mood, or context).  
        11. `"session"` = false if the request is for a specific single song or too vague to establish a theme.  
        12. Don't use JSON fences (```), return plain JSON only.  

        ---

        Message: "{message}"  
        Return ONLY the JSON object.
        """
        
        response = self.capability_worker.text_to_text_response(check_prompt, [])

        self.worker.editor_logging_handler.error(response)
        cleaned = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", response.strip())
        response = json.loads(response)
        self.worker.editor_logging_handler.error(response)
        return response

    async def _handle_favorites_playback(self):
        """Handle playing favorite songs with removal option"""
        favorites = self.capability_worker.get_single_key("favorites").get("value", [])
        self.worker.editor_logging_handler.info(f"Type of favorites: {type(favorites)}")

        if not favorites:
            await self.capability_worker.speak("Your favorites list is empty.")
            return

        await self.capability_worker.speak("Playing your favorite songs.")
        self.worker.editor_logging_handler.info(f"testing favorites: {favorites}")
        favorites = list(reversed(favorites))
        
        for fav in favorites:
            try:
                track_id = fav["song_id"]
                track_endpoint = f"{self.host}/v1/tracks/{track_id}"

                track_response = requests.get(
                    track_endpoint,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": f"{self.app_name}/1.0"
                    }
                )

                if track_response.status_code != 200:
                    self.worker.editor_logging_handler.error(
                        f"[Favorites] Failed to fetch track {track_id}"
                    )
                    continue

                selected = track_response.json().get("data", {})
                if not selected:
                    continue

                # Get stream URL
                stream_url = f"{self.host}/v1/tracks/{track_id}/stream"
                async with httpx.AsyncClient(timeout=None) as client:
                    async with client.stream("GET", stream_url, follow_redirects=True) as stream_response:

                        self.worker.editor_logging_handler.error(
                            f"[STREAM DEBUG] status={stream_response.status_code}"
                        )

                        if stream_response.status_code != 200:
                            self.worker.editor_logging_handler.error(
                                f"[Favorites] Failed to stream track {selected['id']}"
                            )
                            continue

                        # Announce playback
                        await self.capability_worker.speak(
                            f"Now playing {selected['title']} by {selected['user']['name']}."
                        )

                        # Prepare metadata
                        formatted_song_data = {
                            "title": selected.get("title", ""),
                            "artist": (selected.get("user") or {}).get("name", ""),
                            "image": (selected.get("artwork") or {}).get("480x480", ""),
                            "genre": selected.get("genre", ""),
                            "mood": selected.get("mood", ""),
                            "release_date": selected.get("release_date", "")
                        }

                        # Send metadata to frontend
                        await self.capability_worker.send_data_over_websocket(
                            data_type="audius_song_playing",
                            data=formatted_song_data
                        )

                        # Play the song stream
                        await self.stream_audio_simple_2(stream_response)

                        # Ask user about removing song from favorites
                        await self.capability_worker.speak(
                            f"Would you like to remove this song from your favorites? "
                            f"Say 'YES' to remove, 'NO' to keep it, or 'EXIT' anytime to stop playing favorites."
                        )

                        user_reply_1 = await self.capability_worker.user_response()

                        # Normalize user reply
                        normalized_reply = ""
                        if user_reply_1:
                            normalized_reply = re.sub(r"[^\w\s]", "", user_reply_1).strip().lower()

                        if normalized_reply in ["yes", "remove", "delete", "yep", "yeah"]:
                            favorites = self.capability_worker.get_single_key("favorites").get("value", [])
                            self.worker.editor_logging_handler.info(f"Before removal: {favorites}")

                            new_favorites = [
                                f for f in favorites if str(f.get("song_id")) != str(selected["id"])
                            ]

                            self.worker.editor_logging_handler.info(f"After removal attempt: {new_favorites}")

                            if len(new_favorites) < len(favorites):
                                self.capability_worker.update_key("favorites", new_favorites)
                                await self.capability_worker.speak(
                                    "This song has been removed from your favorites."
                                )
                            else:
                                await self.capability_worker.speak(
                                    "That song is not in your favorites."
                                )

                        elif normalized_reply in ["no", "nope", "keep", "skip", "cancel"]:
                            await self.capability_worker.speak("Okay, keeping this song in your favorites.")

                        elif normalized_reply in ["exit", "stop", "quit", "end", "pause"]:
                            await self.capability_worker.speak("Exiting your favorites playback. Goodbye!")
                            break

                        else:
                            await self.capability_worker.speak(
                                "I didn't understand. Moving on to the next song."
                            )

            except Exception as e:
                self.worker.editor_logging_handler.error(f"[Favorites] Error playing song: {e}")
                continue

    async def first_setup(self):
        """Main setup and conversation loop"""
        try:
            self.worker.music_mode_event.set()
            await self.capability_worker.send_data_over_websocket("music-mode", {"mode": "on"})

            # Check if "global_context" key exists
            response = self.capability_worker.get_single_key("global_context")

            if response.get("key", "") == "":
                self.capability_worker.create_key(
                    "global_context",
                    {
                        "last_song_id": None,
                        "context_summary": None,
                        "last_played_message": None
                    }
                )
                self.worker.editor_logging_handler.error("[Setup] Created 'global_context' key with default attributes")
            else:
                self.worker.editor_logging_handler.error(f"[Setup] 'global_context' already exists → {response}")

            # Check if "favorites" key exists
            response = self.capability_worker.get_single_key("favorites")

            if response.get("key", "") == "":
                self.capability_worker.create_key("favorites", [])
                self.worker.editor_logging_handler.error("[Setup] Created 'favorites' key with empty list")
            else:
                self.worker.editor_logging_handler.error(f"[Setup] 'favorites' already exists → {response}")

            first_time = True

            while True:  # conversation loop
                if first_time:
                    msg = await self.capability_worker.wait_for_complete_transcription()
                    self.worker.editor_logging_handler.error(f"User said: {msg}")
                    first_time = False
                else:
                    await self.capability_worker.speak(CONTINUE_PROMPT)

                    raw_msg = await self.capability_worker.user_response()

                    if raw_msg and raw_msg.strip() != "":
                        msg = raw_msg
                    else:
                        self.worker.editor_logging_handler.error("⚠️ Empty transcription result, keeping last msg")

                    self.worker.editor_logging_handler.error(f"User said (raw): {msg}")

                    msg = f"Question: {CONTINUE_PROMPT} Answer: {msg}"
                    self.worker.editor_logging_handler.error(f"User said (formatted): {msg}")
                    
                    if not msg:
                        await self.capability_worker.speak("I didn't catch that. Could you repeat?")
                        continue

                if not msg:
                    await self.capability_worker.speak("I didn't catch that. Could you repeat?")
                    continue

                # Extract intent
                self.worker.editor_logging_handler.error(f"User said: {msg}")
                us_response = await self.check_song_request(msg)
                self.worker.editor_logging_handler.error(f"Response: {json.dumps(us_response, indent=2)}")

                # Handle intents
                intent = us_response.get("intent", None)

                if intent == "direct_play":
                    if us_response.get("use_context"):
                        us_response["summary"] = self.global_context.get("context_summary", us_response.get("summary"))
                        final_request = us_response
                    else:
                        self.global_context["context_summary"] = us_response.get("summary")
                    
                    if us_response.get("needs_more_info"):
                        clarification_prompt = "Could you tell me the genre, artist, or song?"
                        await self.capability_worker.speak(clarification_prompt)

                        user_reply = await self.capability_worker.user_response()
                        self.worker.editor_logging_handler.error(f"Clarification: {user_reply}")

                        if user_reply is None or user_reply.strip() == "":
                            self.worker.editor_logging_handler.error("User did not provide clarification.")
                            us_response["needs_more_info"] = False
                            final_request = us_response
                        else:
                            final_request = await self.check_song_request(user_reply)
                    else:
                        final_request = us_response

                    self.worker.editor_logging_handler.error(f"Final request: {final_request}")                    
                    await self.play_song(final_request)

                elif intent == "stop":
                    await self.capability_worker.speak("Music off! Hope you enjoyed the vibes — catch you later!")
                    break

                elif intent == "add_to_favorites":
                    gc = self.capability_worker.get_single_key("global_context").get("value", {})
                    song_id = gc.get("last_song_id")
                    song_message = gc.get("last_played_message")

                    if song_id:
                        favorites = self.capability_worker.get_single_key("favorites").get("value", [])
                        
                        if not any(fav["song_id"] == song_id for fav in favorites):
                            favorites.append({"song_id": song_id, "song_message": song_message})
                            self.capability_worker.update_key("favorites", favorites)
                            await self.capability_worker.speak("Song added to your favorites.")
                        else:
                            await self.capability_worker.speak("This song is already in your favorites.")
                    else:
                        await self.capability_worker.speak("No song is currently playing to add to favorites.")

                elif intent == "remove_from_favorites":
                    gc = self.capability_worker.get_single_key("global_context").get("value", {})
                    song_id = gc.get("last_song_id")

                    if song_id:
                        favorites = self.capability_worker.get_single_key("favorites").get("value", [])
                        
                        new_favorites = [fav for fav in favorites if fav["song_id"] != song_id]
                        if len(new_favorites) < len(favorites):
                            self.capability_worker.update_key("favorites", new_favorites)
                            await self.capability_worker.speak("Song removed from your favorites.")
                        else:
                            await self.capability_worker.speak("That song is not in your favorites.")
                    else:
                        await self.capability_worker.speak("No song is currently playing to remove from favorites.")

                elif intent == "play_favorites":
                    await self._handle_favorites_playback()

                else:
                    await self.capability_worker.speak("I can only play songs or stop right now.")

            await self.capability_worker.send_data_over_websocket("music-mode", {"mode": "off"})
            self.worker.music_mode_event.clear()
            
            await asyncio.sleep(1)
            self.capability_worker.resume_normal_flow()

        except Exception as e:
            self.worker.editor_logging_handler.error(str(e))

    def call(self, worker: AgentWorker):
        try:
            worker.editor_logging_handler.info("AUDIUS MUSIC PLAYER")
            self.worker = worker
            self.capability_worker = CapabilityWorker(self.worker)
            self.host = self._get_host()
            
            if not self.host:
                worker.editor_logging_handler.error("Failed to get Audius host")
                return
            
            self.worker.session_tasks.create(self.first_setup())
        except Exception as e:
            self.worker.editor_logging_handler.warning(e)