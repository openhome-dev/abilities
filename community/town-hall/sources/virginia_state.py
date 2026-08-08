import csv
import json
import re
from datetime import datetime, timedelta
from html import unescape

from .base import CivicSource

LIS_BASE = "https://lis.virginia.gov"
ICS_URL = "https://liscdn.blob.core.windows.net/cdn/meetings.ics"
BILLS_CSV_TMPL = "https://lis.blob.core.windows.net/lisfiles/{session_code}/BILLS.CSV"
# public schedule list (developer keys). partner endpoints need a partner key.
SCHEDULE_LIST_URL = f"{LIS_BASE}/Schedule/api/GetScheduleListAsync"
SCHEDULE_BY_ID_URL = f"{LIS_BASE}/Schedule/api/GetPartnerSchedulebyIdAsync"
TOPIC_QUERIES = ("housing", "education", "zoning")
MAX_BILLS = 8
MAX_MEETINGS = 8
MEETING_DAYS_AHEAD = 14
REQUEST_TIMEOUT = 60


class VirginiaStateSource(CivicSource):
    def __init__(self):
        super().__init__()
        self._topic_preferences = []
        self._session_code = None
        self._session_label = ""
        self._numbered_meetings = {}
        self._recent_bills = []

    def get_name(self) -> str:
        return "Virginia General Assembly"

    def get_source_url(self) -> str:
        return "https://lis.virginia.gov/"

    def required_api_key_name(self) -> str:
        return "LIS_API_KEY"

    @staticmethod
    def _describe_api_key(api_key: str | None) -> str:
        """safe key diagnostics for logs/spoken errors — never the secret itself."""
        if not api_key:
            return "missing"
        text = str(api_key).strip()
        parts = text.split("-")
        # full guid is 36 chars; accept near-misses after strip so ui clipping
        # is never confused with a truncated secret
        if len(text) >= 32 and len(parts) >= 4:
            return f"present ({len(text)} chars)"
        return (
            f"suspicious ({len(text)} chars, "
            f"expected a 36-character GUID from lis.virginia.gov/developers)"
        )

    def set_api_key(self, api_key) -> None:
        cleaned = api_key.strip() if isinstance(api_key, str) and api_key.strip() else None
        if cleaned:
            cleaned = cleaned.strip('"').strip("'")
        self._api_key = cleaned
        if self._worker:
            self._worker.editor_logging_handler.info(
                f"Virginia LIS key status: {self._describe_api_key(cleaned)}"
            )

    def trigger_keywords(self) -> tuple[str, ...]:
        return ("virginia",)

    def set_topic_preferences(self, topics: list[str]) -> None:
        self._topic_preferences = [t.lower() for t in topics]

    def get_topic_preferences(self) -> list[str]:
        return self._topic_preferences

    def _headers(self, api_key: str) -> dict:
        # lis docs use webapikey; keep both casings. omit content-type on gets.
        return {
            "webapikey": api_key,
            "WebAPIKey": api_key,
            "Accept": "application/json",
            "User-Agent": "OpenHome-TownHall/1.0",
        }

    # ------------------------------------------------------------------
    # session helpers
    # ------------------------------------------------------------------

    def _pick_session(self, sessions: list[dict]) -> tuple[int, str]:
        """prefer the current (or most recent past) regular session — never a future one."""
        session_code, label = 20261, "2026 Regular Session"
        if not sessions:
            return session_code, label

        now = datetime.now()
        now_year = now.year
        # late in the year, the next regular session may already be the default
        allow_next_year = now.month >= 11

        def year_of(s: dict) -> int:
            code = str(s.get("SessionCode") or "0")
            try:
                return int(s.get("SessionYear") or code[:4] or 0)
            except (TypeError, ValueError):
                return 0

        def is_regular(s: dict) -> bool:
            stype = str(s.get("SessionType") or "").lower()
            code = str(s.get("SessionCode") or "")
            return stype == "regular" or (code.endswith("1") and "special" not in stype)

        def eligible(s: dict) -> bool:
            year = year_of(s)
            if year <= 0:
                return False
            if year < now_year:
                return True
            if year == now_year:
                return True
            if year == now_year + 1 and allow_next_year:
                return True
            return False

        pool = [s for s in sessions if eligible(s)] or [
            s for s in sessions if year_of(s) <= now_year
        ] or list(sessions)

        def rank(s: dict) -> tuple:
            year = year_of(s)
            return (
                1 if (s.get("IsActive") and is_regular(s)) else 0,
                1 if (s.get("IsDefault") and is_regular(s)) else 0,
                1 if s.get("IsActive") else 0,
                1 if s.get("IsDefault") else 0,
                1 if is_regular(s) else 0,
                # closer to the current year wins; do not prefer far-future sessions
                -abs(year - now_year),
                year,
            )

        chosen = max(pool, key=rank)
        code = str(chosen.get("SessionCode") or "20261")
        year = chosen.get("SessionYear") or code[:4]
        stype = chosen.get("SessionType") or "Regular"
        return int(code), f"{year} {stype} Session"

    async def _resolve_session(self, api_key: str | None) -> tuple[int, str]:
        if self._session_code and self._session_label:
            return self._session_code, self._session_label

        if api_key:
            try:
                url = f"{LIS_BASE}/Session/api/getsessionlistasync"
                resp = await self._http_get(
                    url, headers=self._headers(api_key), timeout=REQUEST_TIMEOUT
                )
                if resp.status_code < 400 and resp.text:
                    data = json.loads(resp.text or "{}") or {}
                    sessions = data.get("Sessions") or []
                    code, label = self._pick_session(sessions)
                    self._session_code = code
                    self._session_label = label
                    return code, label
            except Exception:
                pass

        # guess regular-session codes for current/nearby years (YYYY1)
        year = datetime.now().year
        for y in (year, year - 1, year + 1):
            code = int(f"{y}1")
            self._session_code = code
            self._session_label = f"{y} Regular Session"
            return code, self._session_label

        self._session_code = 20261
        self._session_label = "2026 Regular Session"
        return self._session_code, self._session_label

    # ------------------------------------------------------------------
    # meetings — schedule api + ics fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_dt(value) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        text = str(value).strip()
        if not text:
            return None
        # ics style: 20260729T150000Z or 20260729
        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%m/%d/%Y %H:%M:%S",
            "%m/%d/%Y %I:%M %p",
            "%m/%d/%Y",
            "%Y%m%dT%H%M%SZ",
            "%Y%m%dT%H%M%S",
            "%Y%m%d",
        ):
            try:
                return datetime.strptime(text.replace("Z", ""), fmt.replace("Z", ""))
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None

    @staticmethod
    def _meeting_title(item: dict) -> str:
        # OwnerName is the body; Description is often location/html on lis
        for key in (
            "OwnerName",
            "CommitteeName",
            "ScheduleName",
            "Title",
            "Name",
            "summary",
            "ScheduleDescription",
            "MeetingDescription",
            "Description",
        ):
            val = (item.get(key) or "").strip()
            if val:
                return VirginiaStateSource._strip_html(val)
        return "Legislative meeting"

    @staticmethod
    def _apply_time(dt: datetime, time_part) -> datetime:
        if not time_part or not (dt.hour == 0 and dt.minute == 0 and dt.second == 0):
            return dt
        t = str(time_part).strip()
        for fmt in ("%I:%M %p", "%H:%M:%S", "%H:%M"):
            try:
                tm = datetime.strptime(t, fmt)
                return dt.replace(hour=tm.hour, minute=tm.minute, second=tm.second)
            except ValueError:
                continue
        return dt

    @staticmethod
    def _meeting_when(item: dict) -> datetime | None:
        dt = None
        for key in (
            "ScheduleDate",
            "MeetingDate",
            "StartDate",
            "StartDateTime",
            "ScheduleStartDate",
            "MeetingStartDate",
            "EventDate",
            "Date",
            "dtstart",
        ):
            dt = VirginiaStateSource._parse_dt(item.get(key))
            if dt:
                break
        if not dt:
            return None
        for key in ("ScheduleTime", "MeetingTime", "StartTime", "Time"):
            if item.get(key):
                return VirginiaStateSource._apply_time(dt, item.get(key))
        return dt

    @staticmethod
    def _meeting_id(item: dict) -> str:
        for key in ("ScheduleID", "ScheduleId", "Id", "ID", "MeetingId", "uid"):
            val = item.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
        return ""

    @staticmethod
    def _meeting_notes(item: dict) -> str:
        for key in (
            "MeetingNote",
            "Notes",
            "Location",
            "Room",
            "ScheduleLocation",
            "description",
        ):
            val = (item.get(key) or "").strip()
            if val:
                return VirginiaStateSource._strip_html(val)
        return ""

    def _normalize_meeting(self, item: dict) -> dict | None:
        if item.get("IsCancelled") is True:
            return None
        when = self._meeting_when(item)
        if not when:
            return None
        return {
            "id": self._meeting_id(item),
            "title": self._meeting_title(item),
            "when": when,
            "notes": self._meeting_notes(item),
            "raw": item,
        }

    def _filter_upcoming(self, meetings: list[dict], days_ahead: int = MEETING_DAYS_AHEAD) -> list[dict]:
        now = datetime.now() - timedelta(hours=6)
        end = now + timedelta(days=days_ahead)
        upcoming = [m for m in meetings if now <= m["when"] <= end]
        upcoming.sort(key=lambda m: m["when"])
        if upcoming:
            return upcoming
        # widen window when the near-term calendar is empty (ics can lag)
        end = now + timedelta(days=180)
        upcoming = [m for m in meetings if now <= m["when"] <= end]
        upcoming.sort(key=lambda m: m["when"])
        return upcoming

    def _merge_meetings(self, *groups: list[dict]) -> list[dict]:
        """dedupe meetings by id/title+when."""
        merged = []
        seen = set()
        for group in groups:
            for meeting in group or []:
                key = (
                    meeting.get("id")
                    or f"{meeting.get('title')}|{meeting.get('when')}"
                )
                if key in seen:
                    continue
                seen.add(key)
                merged.append(meeting)
        return merged

    async def _fetch_meetings_via_api(self, api_key: str) -> list[dict]:
        # date window keeps the payload small (~20kb vs ~2mb unfiltered)
        start = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        end = (datetime.now() + timedelta(days=180)).strftime("%Y-%m-%d")
        params = {"StartDate": start, "EndDate": end}
        resp = await self._http_get(
            SCHEDULE_LIST_URL,
            headers=self._headers(api_key),
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code in (401, 403):
            status = self._describe_api_key(api_key)
            self._api_key = None
            raise RuntimeError(
                f"schedule API key rejected (HTTP {resp.status_code}); key status: {status}"
            )
        if resp.status_code >= 400:
            body = (resp.text or "")[:120].replace("\n", " ")
            raise RuntimeError(
                f"schedule list HTTP {resp.status_code}: {body}"
            )
        if not resp.text:
            raise RuntimeError(
                f"schedule list returned empty body ({start}..{end})"
            )
        try:
            payload = json.loads(resp.text or "{}") or {}
        except Exception as e:
            raise RuntimeError(f"schedule list JSON parse failed: {e}") from e
        if isinstance(payload, dict) and payload.get("Success") is False:
            fail = (payload.get("FailureMessage") or "unknown failure").strip()
            raise RuntimeError(f"schedule list Success=false: {fail[:160]}")
        items = (
            payload.get("Schedules")
            or payload.get("ScheduleList")
            or payload.get("ListItems")
            or payload.get("Data")
            or []
        )
        if isinstance(payload, list):
            items = payload
        if (
            not items
            and isinstance(payload, dict)
            and not any(
                k in payload
                for k in ("Schedules", "ScheduleList", "ListItems", "Data")
            )
        ):
            raise RuntimeError(
                "schedule list had unexpected JSON shape "
                f"(keys={list(payload.keys())[:8]}, bytes={len(resp.text or '')})"
            )
        meetings = []
        skipped = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            normalized = self._normalize_meeting(item)
            if normalized:
                meetings.append(normalized)
            else:
                skipped += 1
        if self._worker:
            self._worker.editor_logging_handler.info(
                f"Virginia schedule API: {len(items)} raw, "
                f"{len(meetings)} parsed, {skipped} skipped "
                f"({start}..{end}, {len(resp.text or '')} bytes)"
            )
        return meetings

    async def _fetch_meetings_via_ics(self) -> list[dict]:
        resp = await self._http_get(ICS_URL, timeout=REQUEST_TIMEOUT)
        if resp.status_code >= 400 or not resp.text:
            body = (resp.text or "")[:120].replace("\n", " ")
            raise RuntimeError(
                f"ICS fetch HTTP {resp.status_code or 'empty'}: {body}"
            )
        return self._parse_ics(resp.text)

    @staticmethod
    def _unfold_ics(text: str) -> str:
        # rfc 5545 line folding: CRLF + space/tab continues previous line
        return re.sub(r"\r?\n[ \t]", "", text.replace("\r\n", "\n"))

    def _parse_ics(self, text: str) -> list[dict]:
        unfolded = self._unfold_ics(text or "")
        meetings = []
        blocks = re.split(r"BEGIN:VEVENT", unfolded, flags=re.IGNORECASE)
        for block in blocks[1:]:
            end = re.search(r"END:VEVENT", block, flags=re.IGNORECASE)
            body = block[: end.start()] if end else block
            fields = {}
            for line in body.split("\n"):
                line = line.strip()
                if not line or ":" not in line:
                    continue
                key, val = line.split(":", 1)
                key = key.split(";")[0].upper()
                fields[key] = val
            summary = self._strip_html(fields.get("SUMMARY") or "Legislative meeting")
            desc = self._strip_html(fields.get("DESCRIPTION") or "")
            dt = self._parse_dt(fields.get("DTSTART"))
            if not dt:
                continue
            meetings.append(
                {
                    "id": fields.get("UID") or "",
                    "title": summary,
                    "when": dt,
                    "notes": desc,
                    "raw": fields,
                }
            )
        return meetings

    def _format_meeting_title(self, index: int, meeting: dict) -> str:
        when = meeting["when"]
        # always include year — voice agents otherwise invent the wrong year
        day = when.strftime("%A, %B ") + str(when.day) + when.strftime(", %Y")
        time_part = when.strftime("%I:%M %p").lstrip("0")
        if when.hour == 0 and when.minute == 0 and when.second == 0:
            # date-only events
            return f"{index}. **{meeting['title']}** — {day}"
        return f"{index}. **{meeting['title']}** — {day} at {time_part}"

    async def fetch_updates(self) -> str:
        """upcoming ga / committee meetings; legislation is a separate trigger."""
        return await self.fetch_meetings()

    async def fetch_meetings(self) -> str:
        """upcoming ga / committee meetings only — never bills."""
        try:
            return await self._fetch_updates_inner()
        except Exception as e:
            return (
                "### Virginia General Assembly\n"
                f"- Error fetching meetings: {e}\n"
                f"- Fetch status: key {self._describe_api_key(self._api_key)}; "
                f"exception during meetings fetch\n"
                f"- Briefing type: meetings\n"
                f"- Source: {self.get_source_url()}"
            )

    async def _fetch_updates_inner(self) -> str:
        api_meetings: list[dict] = []
        ics_meetings: list[dict] = []
        source_note = ""
        api_key = self._api_key
        api_error = ""
        ics_error = ""

        if not api_key:
            api_error = (
                "LIS_API_KEY was not returned by get_api_keys. "
                "In the townhall Ability editor, add/link LIS_API_KEY under "
                "Behavior → API Keys (provider https://lis.virginia.gov/developers), "
                "then confirm the value in Settings → Third-Party Keys"
            )
            if self._worker:
                self._worker.editor_logging_handler.warning(api_error)
        else:
            key_status = self._describe_api_key(api_key)
            if key_status.startswith("suspicious"):
                api_error = (
                    f"LIS_API_KEY looks {key_status}. "
                    "Re-paste the full GUID from lis.virginia.gov/developers"
                )
                if self._worker:
                    self._worker.editor_logging_handler.warning(api_error)
                api_key = None
                self._api_key = None

        if api_key:
            try:
                api_meetings = await self._fetch_meetings_via_api(api_key)
                if api_meetings:
                    source_note = "Virginia schedule"
                elif self._worker:
                    self._worker.editor_logging_handler.warning(
                        "Virginia schedule API returned zero parseable meetings"
                    )
            except Exception as e:
                api_error = str(e)
                if "401" in api_error or "403" in api_error or "rejected" in api_error.lower():
                    api_error = (
                        f"{api_error}. Key status: {self._describe_api_key(self._api_key)}. "
                        "Re-paste the full 36-character GUID in Third-Party Keys"
                    )
                if self._worker:
                    self._worker.editor_logging_handler.warning(
                        f"Virginia schedule API: {api_error}"
                    )

        # ics is a backup only — the public file is often stale
        try:
            ics_meetings = await self._fetch_meetings_via_ics()
            if ics_meetings and not source_note:
                source_note = "Virginia calendar"
        except Exception as e:
            ics_error = str(e)
            if self._worker:
                self._worker.editor_logging_handler.warning(
                    f"Virginia calendar ICS: {e}"
                )

        meetings = self._merge_meetings(api_meetings, ics_meetings)
        if api_meetings and ics_meetings:
            source_note = "Virginia schedule"
        elif not source_note:
            source_note = "Virginia schedule" if api_meetings else "Virginia calendar"

        status_line = (
            f"- Fetch status: key {self._describe_api_key(self._api_key or api_key)}; "
            f"schedule API {len(api_meetings)} meeting(s)"
            + (f" ({api_error})" if api_error and not api_meetings else "")
            + f"; calendar ICS {len(ics_meetings)} meeting(s)"
            + (f" ({ics_error})" if ics_error and not ics_meetings else "")
        )
        type_line = "- Briefing type: meetings"

        if not meetings:
            detail = api_error or ics_error
            if not detail:
                detail = (
                    "LIS_API_KEY was not available to the ability"
                    if not self._api_key
                    else "both schedule feeds returned no meetings"
                )
            key_note = self._describe_api_key(self._api_key or api_key)
            return (
                "### Virginia General Assembly\n"
                f"- Error fetching meetings: {detail}\n"
                f"- LIS key status: {key_note}\n"
                f"{status_line}\n"
                f"{type_line}\n"
                f"- Source: {self.get_source_url()}"
            )

        upcoming = self._filter_upcoming(meetings)
        self._numbered_meetings = {}
        lines = ["### Virginia General Assembly"]

        if not upcoming:
            # stale ics-only with no near-term meetings is not a real empty calendar
            if not api_meetings:
                detail = api_error or (
                    "LIS schedule API returned no meetings; "
                    "public calendar has none upcoming"
                )
                return (
                    "### Virginia General Assembly\n"
                    f"- Error fetching meetings: {detail}\n"
                    f"{status_line}\n"
                    f"{type_line}\n"
                    f"- Source: {self.get_source_url()}"
                )
            lines.append(
                "- No upcoming committee or floor meetings in the next 6 months"
            )
            lines.append(
                f"- Parsed {len(meetings)} meeting(s) from the feed; none fall in that window"
            )
            soonest = min(meetings, key=lambda m: m["when"])["when"]
            latest = max(meetings, key=lambda m: m["when"])["when"]
            lines.append(
                "- Feed coverage: "
                f"{soonest.strftime('%Y-%m-%d')} to {latest.strftime('%Y-%m-%d')}"
            )
            lines.append(status_line)
            lines.append(type_line)
            lines.append(f"- Data source: {source_note}")
            lines.append(f"- Source: {self.get_source_url()}")
            return "\n".join(lines)

        display = upcoming[:MAX_MEETINGS]
        lines.append(f"\n{len(upcoming)} upcoming meetings:")
        for i, meeting in enumerate(display, 1):
            self._numbered_meetings[i] = meeting
            lines.append(self._format_meeting_title(i, meeting))
        if len(upcoming) > MAX_MEETINGS:
            lines.append(f"\n...plus {len(upcoming) - MAX_MEETINGS} more meetings")

        lines.append(
            "\nSay 'details on meeting [number]' or 'tell me about [committee name]'"
        )
        lines.append(f"\n{status_line}")
        lines.append(type_line)
        lines.append(f"- Data source: {source_note}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # legislation — lis api + bills.csv fallback
    # ------------------------------------------------------------------

    async def _fetch_bills_via_api(self, api_key: str) -> tuple[str, list[dict]]:
        code, label = await self._resolve_session(api_key)
        list_url = (
            f"{LIS_BASE}/Legislation/api/getlegislationsessionlistasync"
            f"?SessionCode={code}"
        )
        resp = await self._http_get(
            list_url, headers=self._headers(api_key), timeout=REQUEST_TIMEOUT
        )
        if resp.status_code in (401, 403):
            # bad/missing key — fall back to public feeds instead of hard-failing
            self._api_key = None
            raise RuntimeError(
                f"LIS API key rejected (HTTP {resp.status_code}) — verify LIS_API_KEY in Settings"
            )
        if resp.status_code == 204 or not resp.text:
            return label, []
        if resp.status_code >= 400:
            raise RuntimeError(f"legislation list HTTP {resp.status_code}")
        payload = json.loads(resp.text or "{}") or {}
        bills = payload.get("Legislations") or payload.get("ListItems") or []
        return label, bills

    async def _fetch_bills_via_csv(self, session_code: int, label: str) -> tuple[str, list[dict]]:
        codes_to_try = [session_code]
        year = datetime.now().year
        for y in (year, year - 1, year + 1):
            code = int(f"{y}1")
            if code not in codes_to_try:
                codes_to_try.append(code)

        last_error = "no csv found"
        for code in codes_to_try:
            url = BILLS_CSV_TMPL.format(session_code=code)
            resp = await self._http_get(url, timeout=REQUEST_TIMEOUT)
            text = resp.text or ""
            if resp.status_code >= 400 or not text or text.lstrip().startswith("<"):
                last_error = f"HTTP {resp.status_code} for session {code}"
                continue
            if "Bill_id" not in text[:200]:
                preview = text[:80].replace("\n", " ")
                last_error = f"unexpected csv for session {code}: {preview}"
                continue
            bills = self._parse_bills_csv(text)
            self._session_code = code
            self._session_label = label if code == session_code else f"{str(code)[:4]} Regular Session"
            return self._session_label, bills
        raise RuntimeError(f"BILLS.CSV fallback failed: {last_error}")

    def _parse_bills_csv(self, text: str) -> list[dict]:
        # DictReader accepts an iterable of lines — avoid import io (cloud-blocked)
        reader = csv.DictReader((text or "").splitlines())
        bills = []
        for row in reader:
            bill_id = (row.get("Bill_id") or "").strip()
            if not bill_id:
                continue
            failed = (row.get("Failed") or "").upper() == "Y"
            status_parts = []
            if (row.get("Approved") or "").upper() == "Y":
                status_parts.append("Approved")
            elif (row.get("Vetoed") or "").upper() == "Y":
                status_parts.append("Vetoed")
            elif (row.get("Passed") or "").upper() == "Y":
                status_parts.append("Passed")
            elif failed:
                status_parts.append("Failed")
            else:
                house = (row.get("Last_house_action") or "").strip()
                senate = (row.get("Last_senate_action") or "").strip()
                status_parts.append(house or senate or "In progress")
            bills.append(
                {
                    "FullNumber": bill_id,
                    "Description": (row.get("Bill_description") or "").strip(),
                    "LegislationStatus": status_parts[0],
                    "Patrons": [{"Name": (row.get("Patron_name") or "").strip()}],
                    "LegislationTypeCode": "B" if bill_id.upper().startswith(("HB", "SB")) else "",
                    "_failed": failed,
                    "_csv": True,
                    "LegislationSummary": "",
                    "Last_house_action": row.get("Last_house_action") or "",
                    "Last_senate_action": row.get("Last_senate_action") or "",
                    "Introduction_date": row.get("Introduction_date") or "",
                }
            )
        return bills

    @staticmethod
    def _strip_html(text: str) -> str:
        if not text:
            return ""
        cleaned = re.sub(r"<[^>]+>", " ", text)
        cleaned = unescape(cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()

    @staticmethod
    def _bill_number(bill: dict) -> str:
        return (
            bill.get("FullNumber")
            or bill.get("LegislationNumber")
            or f"ID {bill.get('LegislationID', '?')}"
        )

    @staticmethod
    def _bill_description(bill: dict) -> str:
        desc = bill.get("Description") or bill.get("LegislationTitle") or ""
        if not desc:
            desc = VirginiaStateSource._strip_html(bill.get("LegislationSummary") or "")
        desc = desc.strip()
        if len(desc) > 160:
            desc = desc[:157].rstrip() + "..."
        return desc

    @staticmethod
    def _search_text(bill: dict) -> str:
        parts = [
            bill.get("Description") or "",
            bill.get("LegislationTitle") or "",
            VirginiaStateSource._strip_html(bill.get("LegislationSummary") or ""),
        ]
        return " ".join(parts).lower()

    @staticmethod
    def _is_bill(bill: dict) -> bool:
        type_code = (bill.get("LegislationTypeCode") or "").upper()
        number = VirginiaStateSource._bill_number(bill).upper()
        if type_code == "B" or number.startswith(("HB", "SB")):
            return True
        return False

    @staticmethod
    def _patron_name(bill: dict) -> str:
        patrons = bill.get("Patrons") or []

        def clean(p: dict) -> str:
            for field in ("Name", "MemberDisplayName", "PatronDisplayName", "DisplayName"):
                val = (p.get(field) or "").strip()
                if val and val.lower() not in ("chief patron", "(chief patron)"):
                    return val
            return ""

        for p in patrons:
            if p.get("IsIntroducing"):
                name = clean(p)
                if name:
                    return name
        for p in patrons:
            name = clean(p)
            if name:
                return name
        return ""

    @staticmethod
    def _bill_url(bill: dict) -> str:
        lid = bill.get("LegislationID")
        if lid:
            return f"https://lis.virginia.gov/bill-details/{lid}"
        num = VirginiaStateSource._bill_number(bill)
        return f"https://lis.virginia.gov/?bill={num}"

    def _format_bill_line(self, bill: dict) -> str:
        number = self._bill_number(bill)
        desc = self._bill_description(bill)
        status = bill.get("LegislationStatus") or "Unknown"
        patron = self._patron_name(bill)
        meta = f"Status: {status}"
        if patron:
            meta += f" | Patron: {patron}"
        return f"- **{number}** — {desc} | {meta}\n  - {self._bill_url(bill)}"

    def _select_bills(self, bills: list[dict]) -> list[dict]:
        topics = self.get_topic_preferences() or list(TOPIC_QUERIES)

        topic_hits: list[dict] = []
        other_bills: list[dict] = []
        seen: set[str] = set()

        for bill in bills:
            if bill.get("_failed"):
                continue
            status = (bill.get("LegislationStatus") or "").lower()
            if "fail" in status:
                continue
            key = str(bill.get("LegislationID") or self._bill_number(bill))
            if key in seen:
                continue
            seen.add(key)
            text = self._search_text(bill)
            if any(topic in text for topic in topics):
                topic_hits.append(bill)
            elif self._is_bill(bill):
                other_bills.append(bill)

        selected = topic_hits[:MAX_BILLS]
        if len(selected) < MAX_BILLS:
            selected.extend(other_bills[: MAX_BILLS - len(selected)])
        return selected

    async def fetch_legislation(self) -> str:
        """active bills via lis api, with public bills.csv fallback."""
        api_key = self._api_key
        label = ""
        bills: list[dict] = []
        source_note = "Virginia bills"

        if api_key:
            try:
                label, bills = await self._fetch_bills_via_api(api_key)
                source_note = "Virginia bills"
            except Exception as e:
                if self._worker:
                    self._worker.editor_logging_handler.warning(
                        f"Virginia legislation API: {e}"
                    )
                bills = []

        if not bills:
            code, guessed_label = await self._resolve_session(api_key)
            try:
                label, bills = await self._fetch_bills_via_csv(code, guessed_label or label)
                source_note = "Virginia bill list"
            except Exception as e:
                return (
                    "### Virginia General Assembly Legislation\n"
                    f"- Error fetching legislation: {e}\n"
                    f"- Source: {self.get_source_url()}"
                )

        selected = self._select_bills(bills)
        self._recent_bills = selected
        lines = [f"### Virginia General Assembly Legislation ({label or 'current session'})"]
        if not selected:
            lines.append("- No matching legislation found for current focus topics.")
            lines.append(f"- Data source: {source_note}")
            lines.append(f"- Source: {self.get_source_url()}")
            return "\n".join(lines)

        for bill in selected:
            lines.append(self._format_bill_line(bill))
        lines.append(f"\n- Data source: {source_note}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # details
    # ------------------------------------------------------------------

    async def _fetch_schedule_by_id(self, schedule_id: str) -> dict | None:
        """partner-only detail endpoint; developer keys usually get 401 — return none."""
        api_key = self._api_key
        if not api_key or not schedule_id:
            return None
        url = f"{SCHEDULE_BY_ID_URL}?ScheduleId={schedule_id}"
        try:
            resp = await self._http_get(
                url, headers=self._headers(api_key), timeout=REQUEST_TIMEOUT
            )
            # do not clear api_key on 401 here — partner scope differs from list
            if resp.status_code >= 400 or not resp.text:
                return None
            payload = json.loads(resp.text or "{}") or {}
            schedules = payload.get("Schedules") or []
            if schedules and isinstance(schedules[0], dict):
                return schedules[0]
            if isinstance(payload, dict) and (
                payload.get("ScheduleID") or payload.get("ScheduleId")
            ):
                return payload
        except Exception:
            return None
        return None

    def _format_meeting_details(self, meeting: dict) -> str:
        when = meeting["when"]
        day = when.strftime("%A, %B ") + str(when.day) + when.strftime(", %Y")
        time_part = when.strftime("%I:%M %p").lstrip("0")
        lines = [
            f"### {meeting['title']}",
            f"- When: {day}" + (f" at {time_part}" if not (when.hour == 0 and when.minute == 0) else ""),
        ]
        if meeting.get("notes"):
            notes = meeting["notes"]
            if len(notes) > 600:
                notes = notes[:597].rstrip() + "..."
            lines.append(f"- Notes: {notes}")
        if meeting.get("id"):
            lines.append(f"- Schedule id: {meeting['id']}")
        lines.append(f"- Source: {self.get_source_url()}")
        return "\n".join(lines)

    def _format_bill_details(self, bill: dict) -> str:
        number = self._bill_number(bill)
        desc = self._bill_description(bill)
        status = bill.get("LegislationStatus") or "Unknown"
        patron = self._patron_name(bill)
        summary = self._strip_html(bill.get("LegislationSummary") or "")
        lines = [
            f"### {number}",
            f"- Description: {desc}",
            f"- Status: {status}",
        ]
        if patron:
            lines.append(f"- Patron: {patron}")
        if bill.get("Last_house_action"):
            lines.append(f"- Last house action: {bill['Last_house_action']}")
        if bill.get("Last_senate_action"):
            lines.append(f"- Last senate action: {bill['Last_senate_action']}")
        if summary:
            if len(summary) > 800:
                summary = summary[:797].rstrip() + "..."
            lines.append(f"- Summary: {summary}")
        lines.append(f"- Link: {self._bill_url(bill)}")
        return "\n".join(lines)

    def _find_bill(self, ref: str) -> dict | None:
        text = (ref or "").strip().upper()
        text = re.sub(r"\s+", "", text)
        # hb 1234 / house bill 1234
        m = re.search(r"\b([HS]B)\s*(\d+)\b", (ref or "").upper())
        if m:
            needle = f"{m.group(1)}{m.group(2)}"
        else:
            needle = text

        for bill in self._recent_bills:
            number = re.sub(r"\s+", "", self._bill_number(bill).upper())
            if number == needle or needle in number:
                return bill
            desc = (bill.get("Description") or "").lower()
            if ref.lower() in desc:
                return bill
        return None

    def _find_meeting(self, ref: str) -> dict | None:
        text = (ref or "").strip()
        if text.isdigit():
            return self._numbered_meetings.get(int(text))

        m = re.search(r"(?:meeting|number)\s*(\d+)", text, flags=re.IGNORECASE)
        if m:
            return self._numbered_meetings.get(int(m.group(1)))

        needle = text.lower()
        # strip filler so "science and technology meeting" can match
        needle = re.sub(
            r"\b(meeting|meetings|committee|commission|joint|the|a|an)\b",
            " ",
            needle,
        )
        needle = re.sub(r"\s+", " ", needle).strip()
        if not needle:
            return None

        for meeting in self._numbered_meetings.values():
            title = meeting["title"].lower()
            if needle in title or title in needle:
                return meeting

        # token overlap: "science technology" → technology and science commission
        tokens = [t for t in re.findall(r"[a-z0-9]+", needle) if len(t) > 2]
        if not tokens:
            return None
        best = None
        best_score = 0
        for meeting in self._numbered_meetings.values():
            title = meeting["title"].lower()
            score = sum(1 for t in tokens if t in title)
            need = 2 if len(tokens) >= 2 else 1
            if score >= need and score > best_score:
                best_score = score
                best = meeting
        return best

    async def get_details(self, item_ref: str) -> str:
        ref = (item_ref or "").strip()
        if not ref:
            return "### Details\n- No meeting or bill reference provided."

        # bill numbers first
        if re.search(r"\b([HS]B)\s*\d+\b", ref, flags=re.IGNORECASE) or (
            self._recent_bills and self._find_bill(ref)
        ):
            if not self._recent_bills:
                await self.fetch_legislation()
            bill = self._find_bill(ref)
            if bill:
                return self._format_bill_details(bill)
            return (
                f"### Legislation\n"
                f"- Could not find '{ref}' in the current Virginia bill list. "
                f"Say 'virginia legislation' to hear recent bills."
            )

        meeting = self._find_meeting(ref)
        if meeting:
            if meeting.get("id") and self._api_key:
                remote = await self._fetch_schedule_by_id(meeting["id"])
                if remote:
                    normalized = self._normalize_meeting(remote) or meeting
                    # prefer richer notes from remote
                    if not normalized.get("notes") and meeting.get("notes"):
                        normalized["notes"] = meeting["notes"]
                    return self._format_meeting_details(normalized)
            return self._format_meeting_details(meeting)

        # last chance: treat as bill title search after ensuring cache
        if not self._recent_bills:
            try:
                await self.fetch_legislation()
            except Exception:
                pass
        bill = self._find_bill(ref)
        if bill:
            return self._format_bill_details(bill)

        hints = []
        for num, meeting in sorted(self._numbered_meetings.items()):
            hints.append(f"{num}: {meeting['title']}")
        hint = ""
        if hints:
            hint = " Try meeting " + "; or ".join(hints[:5]) + "."
        return (
            f"### Details\n"
            f"- Could not find a Virginia meeting or bill matching '{ref}'.{hint}"
        )
