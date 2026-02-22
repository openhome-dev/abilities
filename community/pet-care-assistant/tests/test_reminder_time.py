"""Tests for _parse_reminder_time — natural language time parsing."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest


class TestParseReminderTime:
    """Tests for PetCareAssistantCapability._parse_reminder_time."""

    # ── Returns None for unparseable input ────────────────────────────────

    def test_none_input(self, capability):
        assert capability._parse_reminder_time(None) is None

    def test_empty_string(self, capability):
        assert capability._parse_reminder_time("") is None

    def test_garbage_input(self, capability):
        assert capability._parse_reminder_time("blah blah blah") is None

    # ── "in X minutes/hours" ──────────────────────────────────────────────

    def test_in_30_minutes(self, capability):
        now = datetime.now()
        result = capability._parse_reminder_time("in 30 minutes")
        assert result is not None
        diff = (result - now).total_seconds()
        assert 1790 < diff < 1810  # ~30 minutes

    def test_in_2_hours(self, capability):
        now = datetime.now()
        result = capability._parse_reminder_time("in 2 hours")
        assert result is not None
        diff = (result - now).total_seconds()
        assert 7190 < diff < 7210  # ~2 hours

    # ── "tomorrow at HH:MM" ──────────────────────────────────────────────

    def test_tomorrow_at_10am(self, capability):
        now = datetime.now()
        result = capability._parse_reminder_time("tomorrow at 10 am")
        assert result is not None
        assert result.hour == 10
        assert result.minute == 0
        assert result.date() == (now + timedelta(days=1)).date()

    def test_tomorrow_at_3pm(self, capability):
        now = datetime.now()
        result = capability._parse_reminder_time("tomorrow at 3pm")
        assert result is not None
        assert result.hour == 15
        assert result.date() == (now + timedelta(days=1)).date()

    # ── "at HH:MM" (today or tomorrow) ───────────────────────────────────

    def test_at_time_future_today(self, capability):
        """'at' a future time today should return today."""
        # Use a time far enough in the future to always be valid
        result = capability._parse_reminder_time("at 11:59 pm")
        assert result is not None
        assert result.hour == 23
        assert result.minute == 59

    # ── Day-of-week: "next Monday", "on Friday", "this Wednesday" ────────

    @pytest.mark.parametrize("prefix", ["next", "this", "on"])
    def test_day_of_week_with_prefix(self, capability, prefix):
        """'next/this/on <day>' should resolve to correct future date."""
        # Pick a day that's NOT today to avoid edge cases
        now = datetime.now()
        # Use a day 3 days from now
        target_day = (now + timedelta(days=3)).strftime("%A").lower()
        result = capability._parse_reminder_time(f"{prefix} {target_day}")
        assert result is not None
        expected_date = (now + timedelta(days=3)).date()
        assert result.date() == expected_date
        # Default time should be 9 AM
        assert result.hour == 9
        assert result.minute == 0

    def test_next_monday_at_5pm(self, capability):
        """'next Monday at 5PM' should resolve to next Monday at 17:00."""
        # Mock datetime.now() to a known date (Wednesday 2026-02-18)
        fake_now = datetime(2026, 2, 18, 12, 0, 0)  # Wednesday
        with patch("main.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = capability._parse_reminder_time("next Monday at 5pm")
        assert result is not None
        # Next Monday from Wednesday Feb 18 = Monday Feb 23
        assert result.month == 2
        assert result.day == 23
        assert result.hour == 17
        assert result.minute == 0

    def test_next_same_day_means_7_days(self, capability):
        """'next <today>' should mean 7 days from now, not today."""
        fake_now = datetime(2026, 2, 18, 12, 0, 0)  # Wednesday
        with patch("main.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = capability._parse_reminder_time("next wednesday")
        assert result is not None
        assert result.date() == datetime(2026, 2, 25).date()

    def test_on_friday_at_3pm(self, capability):
        """'on Friday at 3PM' should resolve to next Friday at 15:00."""
        fake_now = datetime(2026, 2, 18, 12, 0, 0)  # Wednesday
        with patch("main.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = capability._parse_reminder_time("on friday at 3pm")
        assert result is not None
        assert result.month == 2
        assert result.day == 20  # Friday
        assert result.hour == 15

    def test_bare_day_name_monday(self, capability):
        """'Monday at 5PM' without prefix should still work."""
        fake_now = datetime(2026, 2, 18, 12, 0, 0)  # Wednesday
        with patch("main.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = capability._parse_reminder_time("monday at 5pm")
        assert result is not None
        assert result.day == 23  # Next Monday
        assert result.hour == 17

    def test_bare_day_name_no_time(self, capability):
        """'Friday' without time should default to 9 AM."""
        fake_now = datetime(2026, 2, 18, 12, 0, 0)  # Wednesday
        with patch("main.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = capability._parse_reminder_time("friday")
        assert result is not None
        assert result.day == 20  # Friday
        assert result.hour == 9
        assert result.minute == 0

    # ── Case insensitivity ────────────────────────────────────────────────

    def test_case_insensitive_day(self, capability):
        """Day names should be case-insensitive."""
        result = capability._parse_reminder_time("Next MONDAY at 5PM")
        assert result is not None
        assert result.hour == 17

    # ── _parse_hm helper ─────────────────────────────────────────────────

    def test_parse_hm_am(self, capability):
        import re

        m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", "10:30 am")
        h, mi = capability._parse_hm(m)
        assert h == 10
        assert mi == 30

    def test_parse_hm_pm(self, capability):
        import re

        m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", "5pm")
        h, mi = capability._parse_hm(m)
        assert h == 17
        assert mi == 0

    def test_parse_hm_12am_is_midnight(self, capability):
        import re

        m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", "12 am")
        h, mi = capability._parse_hm(m)
        assert h == 0
        assert mi == 0

    def test_parse_hm_12pm_is_noon(self, capability):
        import re

        m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", "12pm")
        h, mi = capability._parse_hm(m)
        assert h == 12
        assert mi == 0
