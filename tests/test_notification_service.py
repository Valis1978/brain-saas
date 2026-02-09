"""Tests for notification_service.py - memory leak fix and deduplication."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock


class TestNotificationDeduplication:
    """Test that the notification deduplication dict doesn't grow unbounded."""

    def setup_method(self):
        from app.services.notification_service import NotificationService
        NotificationService._notified_events = {}

    @pytest.mark.asyncio
    async def test_marks_as_notified(self):
        from app.services.notification_service import NotificationService

        assert not await NotificationService._already_notified("user1", "event1")
        await NotificationService._mark_notified("user1", "event1")
        assert await NotificationService._already_notified("user1", "event1")

    @pytest.mark.asyncio
    async def test_different_events_independent(self):
        from app.services.notification_service import NotificationService

        await NotificationService._mark_notified("user1", "event1")
        assert not await NotificationService._already_notified("user1", "event2")
        assert not await NotificationService._already_notified("user2", "event1")

    @pytest.mark.asyncio
    async def test_cleanup_on_overflow(self):
        from app.services.notification_service import NotificationService, _NOTIFIED_EVENTS_MAX

        # Fill with old entries so they'll be cleaned on overflow
        old_time = datetime.now() - timedelta(hours=25)
        for i in range(_NOTIFIED_EVENTS_MAX):
            NotificationService._notified_events[f"user{i}:event{i}"] = old_time

        # This entry triggers cleanup since we exceed the max
        await NotificationService._mark_notified("overflow_user", "overflow_event")

        # Old entries should have been cleaned, only the new one remains
        assert len(NotificationService._notified_events) <= _NOTIFIED_EVENTS_MAX

    @pytest.mark.asyncio
    async def test_recent_entries_preserved_after_cleanup(self):
        from app.services.notification_service import NotificationService, _NOTIFIED_EVENTS_MAX

        # Add old entries manually
        old_time = datetime.now() - timedelta(hours=25)
        for i in range(_NOTIFIED_EVENTS_MAX):
            key = f"old_user:{i}"
            NotificationService._notified_events[key] = old_time

        # Add one recent entry that triggers cleanup
        await NotificationService._mark_notified("recent_user", "recent_event")

        # Recent entry should survive
        assert await NotificationService._already_notified("recent_user", "recent_event")
        # Old entries should be cleaned (they are >24h old)
        assert len(NotificationService._notified_events) < _NOTIFIED_EVENTS_MAX


class TestNotificationServiceMessages:
    """Test the notification message builder uses shared build_summary."""

    @pytest.mark.asyncio
    async def test_morning_summary_uses_build_summary(self):
        from app.services.notification_service import NotificationService

        with patch.object(NotificationService, "send_telegram_message", new_callable=AsyncMock) as mock_send, \
             patch("app.services.notification_service.google_service") as mock_google:

            mock_google.get_events = AsyncMock(return_value={
                "success": True,
                "events": [{"start": "2025-06-01T09:00:00", "emoji": "🧠", "title": "Standup"}]
            })
            mock_google.get_pending_tasks = AsyncMock(return_value={
                "success": True,
                "tasks": [{"title": "Buy milk", "is_overdue": False}]
            })
            mock_send.return_value = True

            user = {
                "user_id": "123",
                "telegram_chat_id": "456",
                "access_token": "tok",
                "refresh_token": "ref"
            }

            await NotificationService._send_user_morning_summary(user)

            mock_send.assert_called_once()
            sent_text = mock_send.call_args[1]["msg_text"]
            assert "Standup" in sent_text
            assert "Buy milk" in sent_text
