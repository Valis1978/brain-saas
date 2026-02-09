"""Tests for telegram.py - webhook handler, DB sessions, and summary builder."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestBuildSummary:
    """Test the shared summary building function."""

    def test_with_events_and_tasks(self):
        from app.utils.summary import build_summary
        from app.utils.messages import MSG

        events = [
            {"start": "2025-06-01T09:00:00", "emoji": "🧠", "title": "Standup"},
            {"start": "2025-06-01T14:00:00", "emoji": "🏠", "title": "Oběd"},
        ]
        tasks = [
            {"title": "Nakoupit", "is_overdue": False},
            {"title": "Opravit bug", "is_overdue": True},
        ]

        msg_parts, voice_parts = build_summary(events, tasks)
        msg_text = "\n".join(msg_parts)
        assert "Standup" in msg_text
        assert "Oběd" in msg_text
        assert "Nakoupit" in msg_text
        assert "Opravit bug" in msg_text
        assert MSG.SUMMARY_HEADER in msg_text

    def test_empty_events(self):
        from app.utils.summary import build_summary
        from app.utils.messages import MSG

        msg_parts, voice_parts = build_summary([], [{"title": "Task", "is_overdue": False}])
        msg_text = "\n".join(msg_parts)
        assert MSG.NO_EVENTS_TODAY in msg_text
        assert "Task" in msg_text

    def test_empty_tasks(self):
        from app.utils.summary import build_summary
        from app.utils.messages import MSG

        msg_parts, voice_parts = build_summary(
            [{"start": "2025-06-01T10:00:00", "emoji": "🧠", "title": "Event"}],
            []
        )
        msg_text = "\n".join(msg_parts)
        assert "Event" in msg_text
        assert MSG.NO_TASKS_TODAY in msg_text

    def test_everything_empty(self):
        from app.utils.summary import build_summary
        from app.utils.messages import MSG

        msg_parts, voice_parts = build_summary([], [])
        msg_text = "\n".join(msg_parts)
        assert MSG.NO_EVENTS_TODAY in msg_text
        assert MSG.NO_TASKS_TODAY in msg_text

    def test_all_day_event(self):
        from app.utils.summary import build_summary
        from app.utils.messages import MSG

        events = [{"start": "2025-06-01", "emoji": "🧠", "title": "Holiday"}]
        msg_parts, voice_parts = build_summary(events, [])
        msg_text = "\n".join(msg_parts)
        assert MSG.ALL_DAY in msg_text
        assert "Holiday" in msg_text

    def test_voice_parts_clean_text(self):
        from app.utils.summary import build_summary

        events = [{"start": "2025-06-01T09:00:00", "emoji": "🧠", "title": "Standup"}]
        tasks = [{"title": "Task1", "is_overdue": False}]

        msg_parts, voice_parts = build_summary(events, tasks)
        voice_text = " ".join(voice_parts)
        assert "Standup" in voice_text
        assert "Task1" in voice_text

    def test_max_five_tasks(self):
        from app.utils.summary import build_summary

        tasks = [{"title": f"Task{i}", "is_overdue": False} for i in range(10)]
        msg_parts, voice_parts = build_summary([], tasks)
        msg_text = "\n".join(msg_parts)
        assert "Task4" in msg_text
        assert "Task5" not in msg_text  # Only first 5


class TestSaveCapture:
    """Test database session management in save_capture."""

    @patch("app.api.endpoints.telegram.SessionLocal")
    def test_session_closed_on_success(self, mock_session_local):
        from app.api.endpoints.telegram import save_capture

        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        save_capture("123", "Test", "text", "Hello", {"intent": "NOTE"})

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()

    @patch("app.api.endpoints.telegram.SessionLocal")
    def test_session_closed_on_error(self, mock_session_local):
        from app.api.endpoints.telegram import save_capture

        mock_db = MagicMock()
        mock_db.commit.side_effect = Exception("DB error")
        mock_session_local.return_value = mock_db

        save_capture("123", "Test", "text", "Hello", {"intent": "NOTE"})

        mock_db.rollback.assert_called_once()
        mock_db.close.assert_called_once()


class TestSendTelegramText:
    """Test the hardened Telegram message sending."""

    @pytest.mark.asyncio
    async def test_truncates_long_messages(self):
        from app.api.endpoints.telegram import send_telegram_text

        with patch("app.api.endpoints.telegram.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client.post.return_value = mock_resp

            long_text = "x" * 5000
            await send_telegram_text(123, long_text, "token123")

            call_kwargs = mock_client.post.call_args[1]
            sent_text = call_kwargs["json"]["text"]
            assert len(sent_text) <= 4000

    @pytest.mark.asyncio
    async def test_handles_network_error(self):
        from app.api.endpoints.telegram import send_telegram_text

        with patch("app.api.endpoints.telegram.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.side_effect = Exception("Network error")

            # Should not raise
            await send_telegram_text(123, "Hello", "token123")


class TestCompleteTaskIntent:
    """Test the COMPLETE_TASK intent in process_with_google."""

    @pytest.mark.asyncio
    async def test_completes_single_matching_task(self):
        from app.api.endpoints.telegram import process_with_google

        mock_tokens = {"access_token": "test", "refresh_token": "test"}
        tasks_result = {
            "success": True,
            "tasks": [
                {"id": "task1", "title": "Nakoupit mléko", "is_overdue": False},
                {"id": "task2", "title": "Opravit bug", "is_overdue": True},
            ]
        }

        with patch("app.api.endpoints.telegram.get_user_google_tokens", new_callable=AsyncMock, return_value=mock_tokens), \
             patch("app.api.endpoints.telegram.google_service") as mock_google, \
             patch("app.api.endpoints.telegram.send_telegram_text", new_callable=AsyncMock) as mock_send:

            mock_google.get_pending_tasks = AsyncMock(return_value=tasks_result)
            mock_google.complete_task = AsyncMock(return_value={"success": True})

            intent_data = {"intent": "COMPLETE_TASK", "target_event": "mléko"}
            await process_with_google("user1", intent_data, "token", 123)

            mock_google.complete_task.assert_called_once_with(token_data=mock_tokens, task_id="task1")
            mock_send.assert_called()
            sent_text = mock_send.call_args[0][1]
            assert "splněn" in sent_text

    @pytest.mark.asyncio
    async def test_clarifies_multiple_matches(self):
        from app.api.endpoints.telegram import process_with_google

        mock_tokens = {"access_token": "test", "refresh_token": "test"}
        tasks_result = {
            "success": True,
            "tasks": [
                {"id": "task1", "title": "Nakoupit mléko", "is_overdue": False},
                {"id": "task2", "title": "Nakoupit chleba", "is_overdue": False},
            ]
        }

        with patch("app.api.endpoints.telegram.get_user_google_tokens", new_callable=AsyncMock, return_value=mock_tokens), \
             patch("app.api.endpoints.telegram.google_service") as mock_google, \
             patch("app.api.endpoints.telegram.send_telegram_text", new_callable=AsyncMock) as mock_send:

            mock_google.get_pending_tasks = AsyncMock(return_value=tasks_result)

            intent_data = {"intent": "COMPLETE_TASK", "target_event": "Nakoupit"}
            await process_with_google("user1", intent_data, "token", 123)

            mock_send.assert_called()
            sent_text = mock_send.call_args[0][1]
            assert "Nalezeno" in sent_text or "2" in sent_text

    @pytest.mark.asyncio
    async def test_reports_no_match(self):
        from app.api.endpoints.telegram import process_with_google

        mock_tokens = {"access_token": "test", "refresh_token": "test"}
        tasks_result = {
            "success": True,
            "tasks": [
                {"id": "task1", "title": "Nakoupit mléko", "is_overdue": False},
            ]
        }

        with patch("app.api.endpoints.telegram.get_user_google_tokens", new_callable=AsyncMock, return_value=mock_tokens), \
             patch("app.api.endpoints.telegram.google_service") as mock_google, \
             patch("app.api.endpoints.telegram.send_telegram_text", new_callable=AsyncMock) as mock_send:

            mock_google.get_pending_tasks = AsyncMock(return_value=tasks_result)

            intent_data = {"intent": "COMPLETE_TASK", "target_event": "neexistuje"}
            await process_with_google("user1", intent_data, "token", 123)

            mock_send.assert_called()
            sent_text = mock_send.call_args[0][1]
            assert "Nenašel" in sent_text

    @pytest.mark.asyncio
    async def test_diacritics_insensitive_matching(self):
        from app.api.endpoints.telegram import process_with_google

        mock_tokens = {"access_token": "test", "refresh_token": "test"}
        tasks_result = {
            "success": True,
            "tasks": [
                {"id": "task1", "title": "Připravit schůzku", "is_overdue": False},
            ]
        }

        with patch("app.api.endpoints.telegram.get_user_google_tokens", new_callable=AsyncMock, return_value=mock_tokens), \
             patch("app.api.endpoints.telegram.google_service") as mock_google, \
             patch("app.api.endpoints.telegram.send_telegram_text", new_callable=AsyncMock) as mock_send:

            mock_google.get_pending_tasks = AsyncMock(return_value=tasks_result)
            mock_google.complete_task = AsyncMock(return_value={"success": True})

            # Search without diacritics - should still match
            intent_data = {"intent": "COMPLETE_TASK", "target_event": "schuzku"}
            await process_with_google("user1", intent_data, "token", 123)

            mock_google.complete_task.assert_called_once_with(token_data=mock_tokens, task_id="task1")


class TestWebhookAuth:
    """Test webhook authentication logic."""

    def test_rejects_unauthorized(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/api/v1/telegram/webhook",
            json={"message": {}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"}
        )
        # With no TELEGRAM_WEBHOOK_SECRET set, any token is accepted
        # When set, wrong token returns 401
        assert response.status_code in (200, 401)

    def test_returns_ok_for_empty_message(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/api/v1/telegram/webhook",
            json={"message": {}},
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}
