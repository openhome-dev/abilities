import re
import json
from datetime import datetime, timedelta

from .base import CivicSource

# granicus legistar web api - public, no auth required
# https://webapi.legistar.com/Home/Examples
LEGISTAR_API_ROOT = "https://webapi.legistar.com/v1"

DEFAULT_TOPICS = {
    'housing': ['housing', 'affordable housing', 'residential', 'development'],
    'zoning': ['zoning', 'planning', 'land use', 'rezoning'],
    'transportation': ['transportation', 'transit', 'traffic', 'road', 'parking'],
    'education': ['school', 'education', 'schools'],
    'public safety': ['police', 'fire', 'safety', 'emergency'],
    'budget': ['budget', 'finance', 'appropriation'],
}


class LegistarCitySource(CivicSource):
    """shared legistar web api implementation for city/county council sources."""

    def __init__(
        self,
        *,
        client_id: str,
        display_name: str,
        trigger_keywords: tuple[str, ...],
        priority_bodies: tuple[str, ...] = ("City Council",),
        matter_type_names: tuple[str, ...] = ("Ordinance", "Resolution"),
        legislation_name: str | None = None,
        calendar_url: str | None = None,
    ):
        super().__init__()
        self._client_id = client_id
        self._display_name = display_name
        self._trigger_keywords = trigger_keywords
        self._priority_bodies = priority_bodies
        self._matter_type_names = matter_type_names
        self._legislation_name = legislation_name or f"{display_name} Legislation"
        self._calendar_url = (
            calendar_url or f"https://{client_id}.legistar.com/Calendar.aspx"
        )
        self._api_base = f"{LEGISTAR_API_ROOT}/{client_id}"
        self._recent_meetings = []
        self._numbered_meetings = {}
        self._topic_preferences = []
        self._recent_legislation = []

    def get_name(self) -> str:
        return self._display_name

    def get_source_url(self) -> str:
        return self._calendar_url

    def trigger_keywords(self) -> tuple[str, ...]:
        # jurisdiction only — "legislation" is handled as an intent in main.py
        return self._trigger_keywords

    def _primary_keyword(self) -> str:
        return self._trigger_keywords[0] if self._trigger_keywords else self._client_id

    def set_topic_preferences(self, topics: list[str]) -> None:
        """store user's topic interests."""
        self._topic_preferences = [t.lower() for t in topics]

    def get_topic_preferences(self) -> list[str]:
        """retrieve stored topic preferences."""
        return self._topic_preferences

    def _matches_topics(self, meeting: dict, topics: list[str]) -> bool:
        """check if meeting matches any user topic interest (catalog or free-form)."""
        body = meeting.get('body', '').lower()
        return self._text_matches_topics(body, topics)

    def _text_matches_topics(self, text: str, topics: list[str]) -> bool:
        """true if text contains any keyword for the user's topics."""
        text_lower = (text or '').lower()
        for topic in topics:
            keywords = list(DEFAULT_TOPICS.get(topic, [topic]))
            # free-form multi-word topics: also match significant individual words
            if topic not in DEFAULT_TOPICS:
                for word in topic.split():
                    if len(word) > 3 and word not in keywords:
                        keywords.append(word)
            if any(kw in text_lower for kw in keywords):
                return True
        return False

    def _legislation_matches_topics(self, leg: dict, topics: list[str]) -> bool:
        """check if a legislation item matches user topic preferences."""
        blob = f"{leg.get('description', '')} {leg.get('file', '')}"
        return self._text_matches_topics(blob, topics)

    # ------------------------------------------------------------------
    # legistar web api helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _encode_query_value(value: str) -> str:
        """minimal url encoding for odata query values (spaces and quotes)."""
        return value.replace("%", "%25").replace("'", "%27").replace(" ", "%20").replace("+", "%2B")

    async def _api_get(self, path: str, params: dict = None):
        """get json from the legistar web api. returns parsed json (list or dict)."""
        url = f"{self._api_base}/{path}"
        if params:
            query = "&".join(
                f"{key}={self._encode_query_value(str(value))}" for key, value in params.items()
            )
            url = f"{url}?{query}"
        resp = await self._http_get(url, headers={"Accept": "application/json"})
        if resp.status_code >= 400:
            raise RuntimeError(f"legistar api HTTP {resp.status_code} for {path}")
        return json.loads(resp.text)

    def _matter_type_filter(self) -> str:
        parts = [f"MatterTypeName eq '{name}'" for name in self._matter_type_names]
        if len(parts) == 1:
            return parts[0]
        return "(" + " or ".join(parts) + ")"

    async def _refresh_legislation_cache(self, days_back: int = 60) -> list[dict]:
        """fetch recent ordinances and resolutions from the web api into the cache."""
        since = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        odata_filter = (
            f"MatterIntroDate ge datetime'{since}' and "
            f"{self._matter_type_filter()}"
        )
        matters = await self._api_get("matters", {"$filter": odata_filter, "$top": 100})

        current_year = datetime.now().year
        legislation = []
        for matter in matters:
            file_ref = (matter.get('MatterFile') or '').strip()
            title = (matter.get('MatterTitle') or '').strip()
            if not file_ref or not title:
                continue

            # strip "ORD. " / "RES. " prefix to get the bare id (e.g. 2026-172)
            id_match = re.match(r'^(ORD|RES)\.?\s*(.+)$', file_ref, re.IGNORECASE)
            leg_id = id_match.group(2).strip() if id_match else file_ref

            # some api rows carry dirty dates; sanity-check the file number year
            year_match = re.match(r'^(\d{4})-', leg_id)
            if year_match and int(year_match.group(1)) < current_year - 1:
                continue

            description = re.sub(r'\s+', ' ', title)
            if len(description) > 200:
                description = description[:197] + '...'

            legislation.append({
                'type': matter.get('MatterTypeName', 'Ordinance'),
                'id': leg_id,
                'file': file_ref,
                'description': description,
                'status': matter.get('MatterStatusName') or 'Unknown',
                'matter_id': matter.get('MatterId'),
                'intro_date': matter.get('MatterIntroDate') or '',
            })

        # newest first
        legislation.sort(key=lambda item: item.get('intro_date') or '', reverse=True)
        self._recent_legislation = legislation
        return legislation

    async def _fetch_agenda_items(self, event_id: str) -> list[dict]:
        """fetch agenda items for a meeting from the web api."""
        raw_items = await self._api_get(f"events/{event_id}/eventitems", {"$top": 100})

        items = []
        for item in raw_items:
            title = (item.get('EventItemTitle') or '').strip()
            if not title:
                continue
            items.append({
                'title': re.sub(r'\s+', ' ', title),
                'file': (item.get('EventItemMatterFile') or '').strip(),
                'status': (item.get('EventItemMatterStatus') or '').strip(),
                'agenda_number': (item.get('EventItemAgendaNumber') or '').strip(),
            })
        return items

    def _format_legislation_entry(self, leg: dict) -> str:
        """format one legislation item as a markdown bullet."""
        status = f" ({leg['status']})" if leg.get('status') and leg['status'] != 'Unknown' else ""
        return f"- **{leg['file']}**{status} — {leg['description']}"

    # ------------------------------------------------------------------
    # meetings (legistar web api /events)
    # ------------------------------------------------------------------

    async def _fetch_meetings(self, days_back: int = 3, days_ahead: int = 14) -> list[dict]:
        """fetch meetings from the web api and normalize into meeting dicts."""
        start = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        end = (datetime.now() + timedelta(days=days_ahead + 1)).strftime('%Y-%m-%d')
        odata_filter = f"EventDate ge datetime'{start}' and EventDate lt datetime'{end}'"
        events = await self._api_get("events", {"$filter": odata_filter, "$orderby": "EventDate", "$top": 100})

        meetings = []
        for event in events:
            date_raw = (event.get('EventDate') or '')[:10]
            try:
                date = datetime.strptime(date_raw, '%Y-%m-%d')
            except ValueError:
                continue

            meetings.append({
                'id': str(event.get('EventId', '')),
                'body': event.get('EventBodyName') or 'Unknown Body',
                'date': date,
                'time': event.get('EventTime') or '',
                'location': event.get('EventLocation') or '',
                'has_agenda': bool(event.get('EventAgendaFile')),
                'agenda_url': event.get('EventAgendaFile') or '',
                'has_minutes': bool(event.get('EventMinutesFile')),
                'minutes_url': event.get('EventMinutesFile') or '',
                'has_video': (event.get('EventVideoStatus') or '') == 'Public',
                'detail_url': event.get('EventInSiteURL') or '',
            })
        return meetings

    def _format_date(self, dt: datetime) -> str:
        """format date as 'Monday, July 28, 2026' (year avoids wrong-year voice answers)."""
        return dt.strftime('%A, %B ') + str(dt.day) + dt.strftime(', %Y')

    def _format_meeting_title(self, number: int, meeting: dict) -> str:
        """format meeting as compact title line for initial briefing."""
        body = meeting.get('body', 'Unknown Body')
        date = meeting.get('date')
        time = meeting.get('time', '')

        date_str = self._format_date(date) if date else '?'
        return f"{number}. **{body}** - {date_str} at {time}"

    def _format_meeting_line(self, meeting: dict, number: int) -> str:
        """format a single meeting as markdown with ordinal number."""
        body = meeting.get('body', 'Unknown Body')
        date = meeting.get('date')
        time = meeting.get('time', '')
        location = meeting.get('location', '')

        date_str = self._format_date(date) if date else '?'
        line = f"- **{number}. {body}** meets {date_str}"
        if time:
            line += f" at {time}"

        if location:
            line += f"\n  Location: {location}"

        available = []
        if meeting.get('has_agenda'):
            available.append('Agenda')
        if meeting.get('has_minutes'):
            available.append('Minutes')
        if meeting.get('has_video'):
            available.append('Video')

        if available:
            line += f"\n  {', '.join(available)} available"

        return line

    def _filter_meetings(
        self, meetings: list[dict], days_ahead: int = 14, priority_bodies: tuple = None, topics: list = None
    ) -> list[dict]:
        """filter to upcoming meetings only (small grace for in-progress ones)."""
        now = datetime.now() - timedelta(hours=2)
        cutoff_future = now + timedelta(days=days_ahead)

        relevant = [
            m for m in meetings
            if m.get('date') and now <= m['date'] <= cutoff_future
        ]

        relevant.sort(key=lambda m: m['date'])

        if topics:
            priority = []
            other = []
            for m in relevant:
                if self._matches_topics(m, topics):
                    priority.append(m)
                else:
                    other.append(m)
            return priority + other

        if priority_bodies:
            priority = []
            other = []
            for m in relevant:
                body = m.get('body', '').lower()
                if any(p.lower() in body for p in priority_bodies):
                    priority.append(m)
                else:
                    other.append(m)
            return priority + other

        return relevant

    async def fetch_updates(self) -> str:
        """fetch upcoming meetings and format for voice."""
        try:
            meetings = await self._fetch_meetings()

            self._recent_meetings = meetings

            topics = self.get_topic_preferences()
            filtered = self._filter_meetings(
                meetings,
                days_ahead=7,
                priority_bodies=self._priority_bodies if not topics else None,
                topics=topics,
            )

            self._numbered_meetings = {}
            lines = [f"### {self.get_name()}"]

            if not filtered:
                lines.append("- No upcoming meetings in the next week")
                lines.append(f"- Source: {self.get_source_url()}")
                return "\n".join(lines)

            display_count = min(8, len(filtered))
            lines.append(f"\n{len(filtered)} upcoming meetings this week:")

            for i, meeting in enumerate(filtered[:display_count], 1):
                self._numbered_meetings[i] = meeting.get('id')
                lines.append(self._format_meeting_title(i, meeting))

            if len(filtered) > display_count:
                lines.append(f"\n...plus {len(filtered) - display_count} more meetings")

            lines.append(
                "\nSay 'details on meeting [number]' or 'tell me about [body name]'"
            )

            leg_summary = self._get_legislation_summary()
            if leg_summary:
                lines.append(f"\n{leg_summary}")

            return "\n".join(lines)

        except Exception as e:
            return f"### {self.get_name()}\n- Error fetching calendar: {str(e)}"

    # ------------------------------------------------------------------
    # legislation (legistar web api)
    # ------------------------------------------------------------------

    def _get_legislation_summary(self) -> str:
        """hint line appended to the main briefing."""
        kw = self._primary_keyword()
        return (
            f"**Pending Legislation:** Say '{kw} legislation' for active "
            f"ordinances and resolutions"
        )

    async def fetch_legislation(self) -> str:
        """fetch and summarize recent legislation from the legistar web api."""
        try:
            legislation = await self._refresh_legislation_cache()
        except Exception as e:
            return f"### {self._legislation_name}\n- Error fetching legislation: {str(e)}"

        if not legislation:
            return (
                f"### {self._legislation_name}\n"
                "- No ordinances or resolutions introduced in the last 60 days."
            )

        topics = self.get_topic_preferences()
        lines = [f"### {self._legislation_name}"]
        lines.append(f"\n{len(legislation)} items introduced in the last 60 days:\n")

        if topics:
            topic_hits = [
                item for item in legislation
                if self._legislation_matches_topics(item, topics)
            ]
            others = [item for item in legislation if item not in topic_hits]

            if topic_hits:
                topic_list = ", ".join(topics)
                lines.append(f"**Matching your topics ({topic_list}) — {len(topic_hits)}:**")
                for leg in topic_hits[:10]:
                    lines.append(self._format_legislation_entry(leg))
                if len(topic_hits) > 10:
                    lines.append(f"\n...plus {len(topic_hits) - 10} more topic matches")

            if others:
                lines.append(f"\n**Other recent items ({len(others)}):**")
                for leg in others[:10]:
                    lines.append(self._format_legislation_entry(leg))
                if len(others) > 10:
                    lines.append(f"\n...plus {len(others) - 10} more items")
        else:
            ordinances = [
                item for item in legislation
                if 'ordinance' in (item.get('type') or '').lower()
            ]
            resolutions = [
                item for item in legislation
                if 'resolution' in (item.get('type') or '').lower()
            ]
            other = [
                item for item in legislation
                if item not in ordinances and item not in resolutions
            ]

            if ordinances:
                lines.append(f"**Ordinances ({len(ordinances)}):**")
                for leg in ordinances[:10]:
                    lines.append(self._format_legislation_entry(leg))

            if resolutions:
                lines.append(f"\n**Resolutions ({len(resolutions)}):**")
                for leg in resolutions[:10]:
                    lines.append(self._format_legislation_entry(leg))

            if other:
                lines.append(f"\n**Other items ({len(other)}):**")
                for leg in other[:10]:
                    lines.append(self._format_legislation_entry(leg))

            shown = min(len(ordinances), 10) + min(len(resolutions), 10) + min(len(other), 10)
            if len(legislation) > shown:
                lines.append(f"\n*Showing {shown} of {len(legislation)} items.*")

        lines.append(
            "\nAsk about any item by number (e.g., 'ORD. 2026-172') or by topic "
            "(e.g., 'the housing ordinance')."
        )

        return '\n'.join(lines)

    def _search_legislation(self, query: str) -> list[dict]:
        """search cached legislation by keywords in description."""
        query_lower = query.lower()
        query_words = query_lower.split()

        matches = []
        for leg in self._recent_legislation:
            desc_lower = leg['description'].lower()

            if all(word in desc_lower for word in query_words):
                matches.append(leg)
            elif len(query_words) == 1 and len(query_words[0]) > 4 and query_words[0] in desc_lower:
                matches.append(leg)

        return matches

    def _format_legislation_details(self, leg: dict) -> str:
        """full detail block for one legislation item."""
        return (
            f"### {leg['file']}\n"
            f"**Status:** {leg['status']}\n"
            f"**Description:** {leg['description']}\n\n"
            f"*Full text and voting record available on {self.get_name()} Legistar.*"
        )

    # ------------------------------------------------------------------
    # details (meetings and legislation)
    # ------------------------------------------------------------------

    async def get_details(self, item_ref: str) -> str:
        """fetch details by meeting number, body name, meeting ID, ORD/RES number, or legislation search."""
        leg_match = re.match(r'^(ORD\.?|RES\.?)\s*(\d{4}-[A-Z]?\d+)$', item_ref.upper().strip())
        if leg_match:
            leg_type = 'Ordinance' if leg_match.group(1).startswith('ORD') else 'Resolution'
            leg_id = leg_match.group(2)

            if not self._recent_legislation:
                try:
                    await self._refresh_legislation_cache()
                except Exception:
                    pass

            for leg in self._recent_legislation:
                if leg['id'].upper() == leg_id:
                    return self._format_legislation_details(leg)

            kw = self._primary_keyword()
            return (
                f"### {leg_type} {leg_id}\n"
                f"This {leg_type.lower()} was not found in legislation from the last 60 days. "
                f"Say '{kw} legislation' to hear all recent items."
            )

        leg_keywords = ['ordinance', 'resolution', 'zoning', 'housing', 'development',
                        'authorize', 'amend', 'close', 'special use', 'bond', 'budget',
                        'street', 'avenue', 'road', 'boulevard', 'trust', 'fund', 'transportation']
        item_lower = item_ref.lower()

        should_search_legislation = (
            any(kw in item_lower for kw in leg_keywords)
            or (self._recent_legislation and not item_ref.isdigit() and len(item_ref) > 4)
        )

        if should_search_legislation:
            if not self._recent_legislation:
                try:
                    await self._refresh_legislation_cache()
                except Exception:
                    pass

            matches = self._search_legislation(item_ref)

            if len(matches) == 1:
                return self._format_legislation_details(matches[0])
            elif len(matches) > 1:
                lines = [f"Found {len(matches)} matching items:"]
                for i, leg in enumerate(matches[:10], 1):
                    lines.append(f"{i}. **{leg['file']}** — {leg['description'][:80]}...")
                if len(matches) > 10:
                    lines.append(f"\n...plus {len(matches) - 10} more matches")
                lines.append(f"\nSay the ORD or RES number to get full details (e.g., '{matches[0]['file']}')")
                return "\n".join(lines)

        meeting = None

        if item_ref.isdigit():
            number = int(item_ref)
            if number in self._numbered_meetings:
                meeting_id = self._numbered_meetings[number]
                meeting = next((m for m in self._recent_meetings if m.get('id') == meeting_id), None)

        if not meeting:
            meeting = next((m for m in self._recent_meetings if m.get('id') == item_ref), None)

        if not meeting:
            item_lower = item_ref.lower()
            for m in self._recent_meetings:
                if item_lower in m.get('body', '').lower():
                    meeting = m
                    break

        if not meeting:
            return (
                f"Could not find meeting or legislation matching '{item_ref}'. "
                f"Try using the meeting number from the briefing or a legislation ID like 'ORD. 2026-172'."
            )

        body = meeting.get('body', 'Meeting')
        date_str = self._format_date(meeting['date']) if meeting.get('date') else 'Unknown date'

        lines = [
            f"### {body} - {date_str}",
            f"- Time: {meeting.get('time', 'TBD')}",
            f"- Location: {meeting.get('location', 'TBD')}",
        ]

        agenda_items = []
        if meeting.get('id'):
            try:
                agenda_items = await self._fetch_agenda_items(meeting['id'])
            except Exception:
                agenda_items = []

        if agenda_items:
            matter_items = [it for it in agenda_items if it.get('file')]
            display_items = matter_items if matter_items else agenda_items

            lines.append("\n**Agenda Items:**")
            for i, item in enumerate(display_items[:15], 1):
                entry = item['title']
                if len(entry) > 150:
                    entry = entry[:147] + '...'
                if item.get('file'):
                    entry = f"{item['file']} — {entry}"
                lines.append(f"{i}. {entry}")

            if len(display_items) > 15:
                lines.append(f"\n...plus {len(display_items) - 15} more items")
        else:
            if meeting.get('has_agenda'):
                lines.append(f"- Agenda: {meeting.get('agenda_url')}")
            if meeting.get('has_minutes'):
                lines.append(f"- Minutes: {meeting.get('minutes_url')}")
            if not meeting.get('has_agenda') and not meeting.get('has_minutes'):
                lines.append("- No agenda or minutes available yet for this meeting")

        return '\n'.join(lines)
