import base64
import json
import random
import time
from datetime import datetime, date, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

ZOOM_BASE_URL = "https://api.zoom.us/v2"
ZOOM_OAUTH_URL = "https://zoom.us/oauth/token"

# Replace with your Zoom Server-to-Server OAuth credentials (OpenHome ability settings).
ZOOM_ACCOUNT_ID = "<Your Zoom Account ID>"
ZOOM_CLIENT_ID = "<Your Zoom Client ID>"
ZOOM_CLIENT_SECRET = "<Your Zoom Client Secret>"

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "bye", "goodbye",
    "leave", "never mind", "nevermind", "nothing else", "no thanks",
    "i'm good", "im good", "all good", "nope",
}

FILLER_LINES = [
    "Let me check.",
    "One sec.",
    "Hang on.",
]

# -----------------------------------------------------------------------------
# Capability (ZoomAuth nested — in-memory tokens, never persisted)
# -----------------------------------------------------------------------------


class ZoomMeetingManagerCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    zoom_auth: Any = None

    # {{register_capability}}

    class ZoomAuth:
        """Server-to-Server OAuth token management. Tokens live in memory only."""

        def __init__(self, account_id: str, client_id: str, client_secret: str):
            self.account_id = account_id
            self.client_id = client_id
            self.client_secret = client_secret
            self.access_token: Optional[str] = None
            self.token_expiry: float = 0

        def get_token(self) -> str:
            if self.access_token and time.time() < self.token_expiry:
                return self.access_token
            creds = base64.b64encode(
                f"{self.client_id}:{self.client_secret}".encode()
            ).decode()
            resp = requests.post(
                ZOOM_OAUTH_URL,
                headers={"Authorization": f"Basic {creds}"},
                data={
                    "grant_type": "account_credentials",
                    "account_id": self.account_id,
                },
                timeout=10,
            )
            if resp.status_code != 200:
                raise ValueError(f"Zoom OAuth failed: {resp.status_code}")
            data = resp.json()
            self.access_token = data["access_token"]
            # Refresh 5 min before expiry
            self.token_expiry = time.time() + data.get("expires_in", 3600) - 300
            return self.access_token

        def auth_headers(self) -> Dict[str, str]:
            return {
                "Authorization": f"Bearer {self.get_token()}",
                "Content-Type": "application/json",
            }

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run_zoom_flow())

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    async def _speak_filler(self) -> None:
        line = random.choice(FILLER_LINES)
        await self.capability_worker.speak(line)

    def _strip_markdown_json(self, raw: str) -> str:
        return raw.replace("```json", "").replace("```", "").strip()

    def _is_free_plan(self, plan_type: int) -> bool:
        return plan_type == 1

    # -------------------------------------------------------------------------
    # Intent Classification
    # -------------------------------------------------------------------------

    def _classify_trigger(self, user_text: str) -> Dict[str, Any]:
        prompt = (
            "Classify this Zoom voice command. Return ONLY valid JSON. No markdown.\n"
            '{"mode": "today_schedule|whats_next|details|cancel|list_recordings|'
            'summarize|play_recording", "meeting_ref": "string or null", '
            '"question": "string or null"}\n'
            "Examples: 'what Zooms do I have today' -> today_schedule; "
            "'cancel my 11 o\'clock' -> cancel, meeting_ref 11 o'clock; "
            "'summarize standup' -> summarize, meeting_ref standup.\n"
            f"User: {user_text}"
        )
        raw = self.capability_worker.text_to_text_response(prompt)
        clean = self._strip_markdown_json(raw)
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            return {"mode": "today_schedule", "meeting_ref": None, "question": None}

    # -------------------------------------------------------------------------
    # API Calls
    # -------------------------------------------------------------------------

    def _get_user_profile(self) -> Optional[Dict[str, Any]]:
        try:
            resp = requests.get(
                f"{ZOOM_BASE_URL}/users/me",
                headers=self.zoom_auth.auth_headers(),
                timeout=10,
            )
            if resp.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"[Zoom] GET /users/me: {resp.status_code}"
                )
                return None
            return resp.json()
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[Zoom] User profile error: {e}"
            )
            return None

    def _get_meetings(self) -> List[Dict[str, Any]]:
        try:
            resp = requests.get(
                f"{ZOOM_BASE_URL}/users/me/meetings",
                headers=self.zoom_auth.auth_headers(),
                params={"type": "upcoming", "page_size": 30},
                timeout=10,
            )
            if resp.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"[Zoom] GET meetings: {resp.status_code}"
                )
                return []
            data = resp.json()
            return data.get("meetings", [])
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[Zoom] Get meetings error: {e}"
            )
            return []

    def _get_meeting_details(self, meeting_id: int) -> Optional[Dict[str, Any]]:
        try:
            resp = requests.get(
                f"{ZOOM_BASE_URL}/meetings/{meeting_id}",
                headers=self.zoom_auth.auth_headers(),
                timeout=10,
            )
            if resp.status_code != 200:
                return None
            return resp.json()
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[Zoom] Get meeting {meeting_id} error: {e}"
            )
            return None

    def _delete_meeting(self, meeting_id: int) -> bool:
        try:
            resp = requests.delete(
                f"{ZOOM_BASE_URL}/meetings/{meeting_id}",
                headers=self.zoom_auth.auth_headers(),
                timeout=10,
            )
            return resp.status_code == 204
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[Zoom] Delete meeting {meeting_id} error: {e}"
            )
            return False

    def _get_recordings(
        self, from_date: str, to_date: str
    ) -> Optional[List[Dict[str, Any]]]:
        try:
            resp = requests.get(
                f"{ZOOM_BASE_URL}/users/me/recordings",
                headers=self.zoom_auth.auth_headers(),
                params={"from": from_date, "to": to_date, "page_size": 10},
                timeout=10,
            )
            if resp.status_code in (401, 403):
                return None
            if resp.status_code != 200:
                self.worker.editor_logging_handler.error(
                    f"[Zoom] GET recordings: {resp.status_code}"
                )
                return []
            data = resp.json()
            return data.get("meetings", [])
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[Zoom] Get recordings error: {e}"
            )
            return []

    # -------------------------------------------------------------------------
    # Meeting / Recording Resolution
    # -------------------------------------------------------------------------

    def _resolve_meeting(
        self, meeting_ref: Optional[str], meetings: List[Dict]
    ) -> Optional[Dict[str, Any]]:
        if not meeting_ref or not meetings:
            return meetings[0] if meetings else None
        summaries = [
            {"id": m.get("id"), "topic": m.get("topic"), "start_time": m.get("start_time")}
            for m in meetings[:15]
        ]
        prompt = (
            "Match the user's reference to a meeting. Return ONLY valid JSON. No markdown.\n"
            '{"matched_meeting_id": <int or null>, "matched_topic": "string"}\n'
            f'User said: "{meeting_ref}"\n'
            f"Meetings: {json.dumps(summaries)}\n"
        )
        raw = self.capability_worker.text_to_text_response(prompt)
        clean = self._strip_markdown_json(raw)
        try:
            out = json.loads(clean)
            mid = out.get("matched_meeting_id")
            if mid is None:
                return None
            for m in meetings:
                if m.get("id") == mid:
                    return m
            return meetings[0] if meetings else None
        except json.JSONDecodeError:
            return meetings[0] if meetings else None

    def _resolve_recording(
        self, meeting_ref: Optional[str], recordings: List[Dict]
    ) -> Optional[Dict[str, Any]]:
        if not meeting_ref or not recordings:
            return recordings[0] if recordings else None
        summaries = []
        for r in recordings[:15]:
            topic = r.get("topic", "Untitled")
            start = r.get("start_time", "")[:10] if r.get("start_time") else ""
            summaries.append({"uuid": r.get("uuid"), "topic": topic, "start": start})
        prompt = (
            "Match the user's reference to a recording. Return ONLY valid JSON. No markdown.\n"
            '{"matched_uuid": "string or null"}\n'
            f'User said: "{meeting_ref}"\n'
            f"Recordings: {json.dumps(summaries)}\n"
        )
        raw = self.capability_worker.text_to_text_response(prompt)
        clean = self._strip_markdown_json(raw)
        try:
            out = json.loads(clean)
            uuid_val = out.get("matched_uuid")
            if not uuid_val:
                return recordings[0] if recordings else None
            for r in recordings:
                if r.get("uuid") == uuid_val:
                    return r
            return recordings[0] if recordings else None
        except json.JSONDecodeError:
            return recordings[0] if recordings else None

    def _parse_date_range(self, user_text: str) -> tuple:
        today = datetime.now(self._zoneinfo()).date()
        prompt = (
            "Parse the time range from this voice command. Return ONLY valid JSON. No markdown.\n"
            '{"from_date": "YYYY-MM-DD", "to_date": "YYYY-MM-DD"}\n'
            f'User said: "{user_text}"\n'
            f"Today is: {today.isoformat()}\n"
            "Examples: 'yesterday' -> from and to yesterday; 'this week' -> Mon to today; "
            "'recent' -> 7 days ago to today."
        )
        raw = self.capability_worker.text_to_text_response(prompt)
        clean = self._strip_markdown_json(raw)
        try:
            out = json.loads(clean)
            from_d = out.get("from_date", (today - timedelta(days=7)).isoformat())
            to_d = out.get("to_date", today.isoformat())
            return (from_d, to_d)
        except json.JSONDecodeError:
            from_d = (today - timedelta(days=7)).isoformat()
            to_d = today.isoformat()
            return (from_d, to_d)

    # -------------------------------------------------------------------------
    # Mode Handlers
    # -------------------------------------------------------------------------

    def _filter_today_meetings(
        self, meetings: List[Dict]
    ) -> List[Dict]:
        tz = self._zoneinfo()
        today = datetime.now(tz).date()
        out = []
        for m in meetings:
            st = m.get("start_time")
            if not st:
                continue
            st = st.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(st)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                d = dt.astimezone(tz).date()
                if d == today:
                    out.append(m)
            except (ValueError, TypeError):
                continue
        out.sort(key=lambda x: x.get("start_time", ""))
        return out

    def _zoneinfo(self) -> ZoneInfo:
        tz_name = self.capability_worker.get_timezone()
        if not tz_name or not str(tz_name).strip():
            tz_name = "America/Los_Angeles"
        try:
            return ZoneInfo(str(tz_name).strip())
        except Exception:
            return ZoneInfo("America/Los_Angeles")

    def _parse_meeting_start_utc(self, m: Dict[str, Any]) -> Optional[datetime]:
        st = m.get("start_time")
        if not st:
            return None
        st = st.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(st)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None

    def _format_dt_local_voice(self, dt_utc: datetime, tz: ZoneInfo) -> str:
        local = dt_utc.astimezone(tz)
        h = local.hour
        mi = local.minute
        if mi == 0:
            return f"{h % 12 or 12}am" if h < 12 else f"{h % 12 or 12}pm"
        return f"{h % 12 or 12}:{mi:02d}am" if h < 12 else f"{h % 12 or 12}:{mi:02d}pm"

    def _relative_day_phrase(self, local_dt: datetime, today_local: date) -> str:
        d = local_dt.date()
        delta = (d - today_local).days
        if delta == 1:
            return "tomorrow"
        if 2 <= delta <= 6:
            return f"on {local_dt.strftime('%A')}"
        return f"on {local_dt.strftime('%B')} {d.day}"

    async def _handle_today_schedule(self) -> None:
        await self._speak_filler()
        meetings = self._get_meetings()
        todays = self._filter_today_meetings(meetings)
        if not todays:
            await self.capability_worker.speak("No Zoom meetings today.")
            return
        summaries = [
            {
                "topic": m.get("topic", "Untitled"),
                "start_time": m.get("start_time", ""),
            }
            for m in todays[:10]
        ]
        prompt = (
            "Generate a concise spoken summary of today's Zoom schedule. "
            "1-2 sentences max. Format times naturally (e.g. 9am, 2:30pm). "
            "If more than 5 meetings, say 'You have N meetings today. The next one is...' "
            "Otherwise mention topic and time for each. "
            "This will be spoken aloud — no markdown, no lists.\n"
            f"Meetings: {json.dumps(summaries)}"
        )
        summary = self.capability_worker.text_to_text_response(prompt)
        await self.capability_worker.speak(summary.strip())
        await self.capability_worker.speak("Want details for any of these?")

    async def _handle_whats_next(self) -> None:
        await self._speak_filler()
        meetings = self._get_meetings()
        tz = self._zoneinfo()
        now_utc = datetime.now(timezone.utc)
        today_local = now_utc.astimezone(tz).date()

        parsed: List[Tuple[datetime, Dict[str, Any]]] = []
        for m in meetings:
            dt = self._parse_meeting_start_utc(m)
            if dt:
                parsed.append((dt, m))
        parsed.sort(key=lambda x: x[0])

        next_global: Optional[Tuple[datetime, Dict[str, Any]]] = None
        next_today: Optional[Tuple[datetime, Dict[str, Any]]] = None
        for dt, m in parsed:
            if dt <= now_utc:
                continue
            if next_global is None:
                next_global = (dt, m)
            if dt.astimezone(tz).date() == today_local:
                next_today = (dt, m)
                break

        if not next_global:
            await self.capability_worker.speak(
                "There are no more upcoming meetings."
            )
            return

        if not next_today:
            dt, m = next_global
            topic = m.get("topic", "Untitled")
            local_dt = dt.astimezone(tz)
            day_phrase = self._relative_day_phrase(local_dt, today_local)
            time_str = self._format_dt_local_voice(dt, tz)
            await self.capability_worker.speak(
                f"No more Zoom meetings today. Your next one is {topic} "
                f"{day_phrase} at {time_str}."
            )
            return

        dt, next_m = next_today
        topic = next_m.get("topic", "Untitled")
        mins = max(0, int((dt - now_utc).total_seconds() / 60))
        time_str = self._format_dt_local_voice(dt, tz)

        if mins < 15:
            detail = self._get_meeting_details(next_m.get("id"))
            if detail:
                mid = str(detail.get("id", ""))
                pwd = detail.get("password", detail.get("pstn_password", ""))
                mid_fmt = self._format_meeting_id_for_voice(mid)
                await self.capability_worker.speak(
                    f"Your {topic} starts in {mins} minutes. "
                    f"Meeting ID is {mid_fmt} and passcode is {pwd}."
                )
                return

        await self.capability_worker.speak(
            f"Your next Zoom is {topic} at {time_str} — that's in {mins} minutes."
        )

    def _format_time_for_voice(self, iso_str: str) -> str:
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            h = dt.hour
            m = dt.minute
            if m == 0:
                return f"{h % 12 or 12}am" if h < 12 else f"{h % 12 or 12}pm"
            return f"{h % 12 or 12}:{m:02d}am" if h < 12 else f"{h % 12 or 12}:{m:02d}pm"
        except (ValueError, TypeError):
            return iso_str

    def _format_meeting_id_for_voice(self, meeting_id: str) -> str:
        s = "".join(c for c in str(meeting_id) if c.isdigit())
        return f"{s[:3]}, {s[3:6]}, {s[6:]}"

    async def _handle_meeting_details(self, meeting_ref: Optional[str]) -> None:
        await self._speak_filler()
        meetings = self._get_meetings()
        todays = self._filter_today_meetings(meetings)
        if not todays:
            all_upcoming = meetings[:15]
        else:
            all_upcoming = todays
        matched = self._resolve_meeting(meeting_ref, all_upcoming)
        if not matched:
            await self.capability_worker.speak(
                "I don't see a meeting matching that. Here's what you have today."
            )
            await self._handle_today_schedule()
            return
        full = self._get_meeting_details(matched.get("id"))
        if not full:
            await self.capability_worker.speak(
                "I couldn't fetch the meeting details."
            )
            return
        topic = full.get("topic", "Untitled")
        st = full.get("start_time", "")
        time_str = self._format_time_for_voice(st)
        mid = str(full.get("id", ""))
        pwd = full.get("password", full.get("pstn_password", ""))
        mid_fmt = self._format_meeting_id_for_voice(mid)
        await self.capability_worker.speak(
            f"{topic} is at {time_str}. Meeting ID is {mid_fmt}. Passcode is {pwd}."
        )

    async def _handle_cancel(self, meeting_ref: Optional[str]) -> None:
        await self._speak_filler()
        meetings = self._get_meetings()
        todays = self._filter_today_meetings(meetings)
        all_upcoming = todays if todays else meetings[:15]
        matched = self._resolve_meeting(meeting_ref, all_upcoming)
        if not matched:
            await self.capability_worker.speak(
                "I don't see a meeting matching that."
            )
            return
        topic = matched.get("topic", "Untitled")
        st = matched.get("start_time", "")
        time_str = self._format_time_for_voice(st)
        confirmed = await self.capability_worker.run_confirmation_loop(
            f"Cancel {topic} at {time_str}? Participants will be notified."
        )
        if not confirmed:
            await self.capability_worker.speak("Okay, I didn't cancel it.")
            return
        ok = self._delete_meeting(matched.get("id"))
        if ok:
            await self.capability_worker.speak(f"Done, {topic} is cancelled.")
        else:
            await self.capability_worker.speak(
                "I couldn't cancel that meeting. You might not have permission."
            )

    async def _handle_list_recordings(
        self, meeting_ref: Optional[str]
    ) -> None:
        user_profile = self._get_user_profile()
        if not user_profile:
            await self.capability_worker.speak(
                "I couldn't reach your Zoom account. Try again later."
            )
            return
        plan_type = user_profile.get("type", 1)
        if self._is_free_plan(plan_type):
            await self.capability_worker.speak(
                "Cloud recordings aren't available on your Zoom plan. "
                "You need Zoom Pro or higher for that feature."
            )
            return
        user_text = meeting_ref or "recent recordings"
        from_d, to_d = self._parse_date_range(user_text)
        await self._speak_filler()
        recordings = self._get_recordings(from_d, to_d)
        if recordings is None:
            await self.capability_worker.speak(
                "Cloud recordings aren't available on your Zoom plan. "
                "You need Zoom Pro or higher."
            )
            return
        if not recordings:
            await self.capability_worker.speak("No Zoom recordings from that period.")
            return
        items = []
        for r in recordings[:5]:
            topic = r.get("topic", "Untitled")
            start = r.get("start_time", "")[:10]
            duration = r.get("duration", 0) or 0
            if duration >= 60:
                d_str = f"{duration // 60} hour {duration % 60} minutes"
            else:
                d_str = f"{duration} minutes"
            items.append({"topic": topic, "date": start, "duration": d_str})
        prompt = (
            "Speak this recording list naturally. 1-2 sentences. "
            "This will be spoken aloud — no markdown, no lists.\n"
            f"Items: {json.dumps(items)}"
        )
        summary = self.capability_worker.text_to_text_response(prompt)
        await self.capability_worker.speak(summary.strip())
        if len(recordings) > 5:
            await self.capability_worker.speak(
                f"Plus {len(recordings) - 5} more. Want me to keep going?"
            )
        await self.capability_worker.speak(
            "Want me to summarize any of these, or play one?"
        )

    async def _handle_summarize(
        self, meeting_ref: Optional[str], question: Optional[str]
    ) -> None:
        user_profile = self._get_user_profile()
        if not user_profile:
            await self.capability_worker.speak(
                "I couldn't reach your Zoom account. Try again later."
            )
            return
        if self._is_free_plan(user_profile.get("type", 1)):
            await self.capability_worker.speak(
                "Cloud recordings aren't available on your Zoom plan. "
                "You need Zoom Pro or higher."
            )
            return
        today = datetime.now(self._zoneinfo()).date()
        from_d = (today - timedelta(days=14)).isoformat()
        to_d = today.isoformat()
        await self._speak_filler()
        recordings = self._get_recordings(from_d, to_d)
        if not recordings:
            await self.capability_worker.speak("No recordings to summarize.")
            return
        matched = self._resolve_recording(meeting_ref, recordings)
        if not matched:
            await self.capability_worker.speak("I couldn't find that recording.")
            return
        rec_files = matched.get("recording_files", [])
        transcript_file = next(
            (f for f in rec_files if f.get("file_type") == "TRANSCRIPT"),
            None,
        )
        if not transcript_file:
            await self.capability_worker.speak(
                "This recording doesn't have a transcript. "
                "Make sure transcription is enabled in your Zoom settings."
            )
            return
        download_url = transcript_file.get("download_url")
        if not download_url:
            await self.capability_worker.speak(
                "I couldn't access the transcript for this recording."
            )
            return
        token = self.zoom_auth.get_token()
        try:
            vtt_resp = requests.get(
                f"{download_url}?access_token={token}",
                timeout=30,
            )
            if vtt_resp.status_code != 200:
                await self.capability_worker.speak(
                    "I couldn't download the transcript."
                )
                return
            vtt_text = vtt_resp.text
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[Zoom] Transcript download: {e}"
            )
            await self.capability_worker.speak(
                "I couldn't download the transcript."
            )
            return
        truncated = " ".join(vtt_text.split()[:4000])
        if question:
            prompt = (
                f"Based on this meeting transcript, answer: {question}\n\n"
                f"{truncated}"
            )
            sys_prompt = (
                "Answer the question based on the transcript. Be specific and concise. "
                "1-3 sentences. If the answer isn't in the transcript, say so. "
                "This will be spoken aloud — no markdown or formatting."
            )
        else:
            prompt = (
                f"Summarize this meeting transcript for voice output. "
                f"2-3 sentences covering decisions, action items, and key takeaways.\n\n"
                f"{truncated}"
            )
            sys_prompt = (
                "You summarize meeting transcripts into brief spoken summaries. "
                "Be concise. 2-3 sentences max. Focus on what matters. "
                "This will be spoken aloud — no markdown, no bullet points, no lists."
            )
        summary = self.capability_worker.text_to_text_response(
            prompt, system_prompt=sys_prompt
        )
        await self.capability_worker.speak(summary.strip())
        await self.capability_worker.speak(
            "Want me to go deeper on any topic, or play the recording?"
        )

    async def _handle_play_recording(self, meeting_ref: Optional[str]) -> None:
        user_profile = self._get_user_profile()
        if not user_profile:
            await self.capability_worker.speak(
                "I couldn't reach your Zoom account. Try again later."
            )
            return
        if self._is_free_plan(user_profile.get("type", 1)):
            await self.capability_worker.speak(
                "Cloud recordings aren't available on your Zoom plan. "
                "You need Zoom Pro or higher."
            )
            return
        today = datetime.now(self._zoneinfo()).date()
        from_d = (today - timedelta(days=14)).isoformat()
        to_d = today.isoformat()
        await self._speak_filler()
        recordings = self._get_recordings(from_d, to_d)
        if not recordings:
            await self.capability_worker.speak("No recordings to play.")
            return
        matched = self._resolve_recording(meeting_ref, recordings)
        if not matched:
            await self.capability_worker.speak("I couldn't find that recording.")
            return
        rec_files = matched.get("recording_files", [])
        audio_file = next(
            (f for f in rec_files if f.get("recording_type") == "audio_only"),
            None,
        )
        if not audio_file:
            audio_file = next(
                (f for f in rec_files if f.get("file_type") == "MP4"),
                None,
            )
        if not audio_file:
            await self.capability_worker.speak(
                "No playable audio file found for this recording."
            )
            return
        download_url = audio_file.get("download_url")
        if not download_url:
            await self.capability_worker.speak(
                "I couldn't access the recording file."
            )
            return
        await self.capability_worker.speak("Playing the recording now.")
        try:
            self.worker.music_mode_event.set()
            await self.capability_worker.send_data_over_websocket(
                "music-mode", {"mode": "on"}
            )
            await self.capability_worker.stream_init()
            token = self.zoom_auth.get_token()
            resp = requests.get(
                f"{download_url}?access_token={token}",
                stream=True,
                timeout=30,
            )
            if resp.status_code != 200:
                raise ValueError(f"Download failed: {resp.status_code}")
            chunk_size = 25 * 1024
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if chunk:
                    await self.capability_worker.send_audio_data_in_stream(
                        chunk, chunk_size=chunk_size
                    )
            await self.capability_worker.stream_end()
        except Exception as e:
            self.worker.editor_logging_handler.error(
                f"[Zoom] Play recording: {e}"
            )
            await self.capability_worker.speak(
                "Something went wrong playing the recording. Try again later."
            )
        finally:
            try:
                await self.capability_worker.send_data_over_websocket(
                    "music-mode", {"mode": "off"}
                )
                self.worker.music_mode_event.clear()
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Main Run
    # -------------------------------------------------------------------------

    async def run_zoom_flow(self):
        try:
            if not ZOOM_ACCOUNT_ID or not ZOOM_CLIENT_ID or not ZOOM_CLIENT_SECRET:
                await self.capability_worker.speak(
                    "I need your Zoom credentials first. I'll walk you through "
                    "the setup. Go to marketplace dot zoom dot us. Create a "
                    "Server-to-Server OAuth app with meeting read, meeting "
                    "write, recording read, and user read scopes. Then add "
                    "your Account ID, Client ID, and Client Secret in the "
                    "OpenHome dashboard under this ability's settings."
                )
                return

            self.zoom_auth = type(self).ZoomAuth(
                ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET
            )

            try:
                profile = self._get_user_profile()
            except Exception as e:
                self.worker.editor_logging_handler.error(
                    f"[Zoom] Auth validation: {e}"
                )
                await self.capability_worker.speak(
                    "Your Zoom credentials didn't work. Double-check the "
                    "Account ID, Client ID, and Client Secret."
                )
                return

            if not profile:
                await self.capability_worker.speak(
                    "Your Zoom credentials didn't work. Double-check the "
                    "Account ID, Client ID, and Client Secret."
                )
                return

            await self.capability_worker.speak(
                "What would you like to do with your Zoom?"
            )

            while True:
                user_input = await self.capability_worker.user_response()

                if not user_input or not user_input.strip():
                    await self.capability_worker.speak(
                        "I didn't catch that. What would you like to do with Zoom?"
                    )
                    continue

                if any(word in user_input.lower() for word in EXIT_WORDS):
                    await self.capability_worker.speak(
                        "Okay. Let me know if you need Zoom."
                    )
                    break

                classified = self._classify_trigger(user_input)
                mode = classified.get("mode", "today_schedule")
                meeting_ref = classified.get("meeting_ref")
                question = classified.get("question")

                if mode == "today_schedule":
                    await self._handle_today_schedule()
                elif mode == "whats_next":
                    await self._handle_whats_next()
                elif mode == "details":
                    await self._handle_meeting_details(meeting_ref)
                elif mode == "cancel":
                    await self._handle_cancel(meeting_ref)
                elif mode == "list_recordings":
                    await self._handle_list_recordings(meeting_ref)
                elif mode == "summarize":
                    await self._handle_summarize(meeting_ref, question)
                elif mode == "play_recording":
                    await self._handle_play_recording(meeting_ref)
                else:
                    await self._handle_today_schedule()

        except Exception as e:
            self.worker.editor_logging_handler.error(f"[Zoom] Run error: {e}")
            await self.capability_worker.speak(
                "Something went wrong. Let me hand you back."
            )
        finally:
            self.capability_worker.resume_normal_flow()
