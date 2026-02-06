"""Tests for google_service.py - core business logic."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, AsyncMock
from app.services.google_service import normalize_text, GoogleService


class TestNormalizeText:
    """Test diacritics-free text normalization."""

    def test_removes_czech_diacritics(self):
        assert normalize_text("schůzka") == "schuzka"
        assert normalize_text("Příští") == "pristi"
        assert normalize_text("úterý") == "utery"

    def test_lowercases(self):
        assert normalize_text("Meeting") == "meeting"
        assert normalize_text("SCHŮZKA") == "schuzka"

    def test_empty_string(self):
        assert normalize_text("") == ""

    def test_no_diacritics(self):
        assert normalize_text("hello world") == "hello world"

    def test_combined_diacritics(self):
        assert normalize_text("Žluťoučký kůň") == "zlutoucky kun"


class TestDetectEventCategory:
    """Test work vs personal event detection."""

    def setup_method(self):
        self.service = GoogleService()

    def test_work_keyword(self):
        assert self.service.detect_event_category("Schůzka s klientem") == "work"

    def test_personal_keyword(self):
        assert self.service.detect_event_category("Narozeniny manželky") == "personal"

    def test_default_to_work(self):
        assert self.service.detect_event_category("Něco neurčitého") == "work"

    def test_diacritics_free_matching(self):
        """User types without diacritics, should still match."""
        assert self.service.detect_event_category("Schuzka s klientem") == "work"
        assert self.service.detect_event_category("narozeniny manzelky") == "personal"

    def test_mixed_keywords_higher_score_wins(self):
        assert self.service.detect_event_category("meeting") == "work"
        assert self.service.detect_event_category("narozeniny děti rodina") == "personal"


class TestGetCredentialsFromTokens:
    """Test credential creation with expiry handling."""

    def setup_method(self):
        self.service = GoogleService()

    @patch("app.services.google_service.Credentials")
    def test_with_valid_expiry(self, mock_creds):
        tokens = {
            "access_token": "token123",
            "refresh_token": "refresh456",
            "expires_at": "2025-06-01T12:00:00"
        }
        self.service.get_credentials_from_tokens(tokens)
        call_kwargs = mock_creds.call_args[1]
        assert call_kwargs["token"] == "token123"
        assert call_kwargs["refresh_token"] == "refresh456"
        assert call_kwargs["expiry"] is not None

    @patch("app.services.google_service.Credentials")
    def test_with_no_expiry(self, mock_creds):
        tokens = {
            "access_token": "token123",
            "refresh_token": "refresh456",
        }
        self.service.get_credentials_from_tokens(tokens)
        call_kwargs = mock_creds.call_args[1]
        assert call_kwargs["expiry"] is None

    @patch("app.services.google_service.Credentials")
    def test_with_malformed_expiry(self, mock_creds):
        tokens = {
            "access_token": "token123",
            "refresh_token": "refresh456",
            "expires_at": "not-a-date"
        }
        self.service.get_credentials_from_tokens(tokens)
        call_kwargs = mock_creds.call_args[1]
        assert call_kwargs["expiry"] is None

    @patch("app.services.google_service.Credentials")
    def test_with_utc_z_suffix(self, mock_creds):
        tokens = {
            "access_token": "t",
            "refresh_token": "r",
            "expires_at": "2025-06-01T12:00:00Z"
        }
        self.service.get_credentials_from_tokens(tokens)
        call_kwargs = mock_creds.call_args[1]
        assert call_kwargs["expiry"] is not None


class TestAllDayEventEndDate:
    """Test that all-day events use exclusive end dates per Google API."""

    def setup_method(self):
        self.service = GoogleService()

    @pytest.mark.asyncio
    @patch("app.services.google_service.build")
    async def test_all_day_event_end_date_is_next_day(self, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_events = mock_service.events.return_value
        mock_insert = mock_events.insert.return_value
        mock_insert.execute.return_value = {
            "id": "event1", "htmlLink": "http://link", "summary": "Test"
        }

        mock_calendar_list = mock_service.calendarList.return_value
        mock_calendar_list.list.return_value.execute.return_value = {
            "items": [{"summary": "Test Cal", "id": "cal1"}]
        }

        await self.service.create_calendar_event(
            token_data={"access_token": "t", "refresh_token": "r"},
            title="Test Event",
            date="2025-06-15",
            time=None
        )

        call_kwargs = mock_events.insert.call_args[1]
        event_body = call_kwargs["body"]
        assert event_body["end"]["date"] == "2025-06-16"
        assert event_body["start"]["date"] == "2025-06-15"

    @pytest.mark.asyncio
    @patch("app.services.google_service.build")
    async def test_timed_event_has_correct_duration(self, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_events = mock_service.events.return_value
        mock_insert = mock_events.insert.return_value
        mock_insert.execute.return_value = {
            "id": "event1", "htmlLink": "http://link", "summary": "Test"
        }

        mock_calendar_list = mock_service.calendarList.return_value
        mock_calendar_list.list.return_value.execute.return_value = {
            "items": [{"summary": "Test Cal", "id": "cal1"}]
        }

        await self.service.create_calendar_event(
            token_data={"access_token": "t", "refresh_token": "r"},
            title="Test Event",
            date="2025-06-15",
            time="10:00"
        )

        call_kwargs = mock_events.insert.call_args[1]
        event_body = call_kwargs["body"]
        assert "dateTime" in event_body["start"]
        assert "10:00" in event_body["start"]["dateTime"]
        assert "10:30" in event_body["end"]["dateTime"]


class TestEmptyTasklist:
    """Test handling of empty task lists."""

    def setup_method(self):
        self.service = GoogleService()

    @pytest.mark.asyncio
    @patch("app.services.google_service.build")
    async def test_create_task_empty_tasklist(self, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_tasklists = mock_service.tasklists.return_value
        mock_tasklists.list.return_value.execute.return_value = {"items": []}

        mock_tasks = mock_service.tasks.return_value
        mock_tasks.insert.return_value.execute.return_value = {
            "id": "task1", "title": "Test", "status": "needsAction"
        }

        result = await self.service.create_task(
            token_data={"access_token": "t", "refresh_token": "r"},
            title="Test Task"
        )

        call_args = mock_tasks.insert.call_args[1]
        assert call_args["tasklist"] == "@default"
        assert result["success"] is True
