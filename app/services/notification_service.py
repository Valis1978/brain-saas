"""
Notification service for sending proactive Telegram messages.

Handles:
- Morning summaries
- Event reminders
- Notification deduplication
"""
import os
import tempfile
import logging
from datetime import datetime, timedelta
from typing import Optional
import httpx
from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.google_service import google_service
from app.services.ai_service import ai_service
from app.utils.messages import MSG

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
VOICE_ENABLED = os.getenv("VOICE_RESPONSE_ENABLED", "true").lower() == "true"

# Max entries before cleanup to prevent unbounded memory growth
_NOTIFIED_EVENTS_MAX = 1000


class NotificationService:
    """Service for sending proactive notifications."""

    @staticmethod
    async def send_telegram_message(chat_id: str, msg_text: str, voice: bool = False):
        """Send a message to Telegram user."""
        if not TELEGRAM_BOT_TOKEN:
            logger.warning("[Notification] Missing TELEGRAM_BOT_TOKEN")
            return False

        async with httpx.AsyncClient() as client:
            # Send text message
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": msg_text[:4000],
                    "parse_mode": "Markdown"
                }
            )

            # Optional voice response
            if voice and VOICE_ENABLED:
                tmp_name = None
                try:
                    audio_bytes = await ai_service.text_to_speech(msg_text)
                    if audio_bytes:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                            tmp.write(audio_bytes)
                            tmp_name = tmp.name

                        with open(tmp_name, "rb") as audio_file:
                            files = {"voice": ("response.mp3", audio_file, "audio/mpeg")}
                            data = {"chat_id": chat_id}
                            await client.post(
                                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVoice",
                                data=data,
                                files=files,
                                timeout=30.0
                            )
                except Exception as e:
                    logger.error(f"[Notification] Voice failed: {e}")
                finally:
                    if tmp_name and os.path.exists(tmp_name):
                        os.remove(tmp_name)

        return True

    @staticmethod
    async def get_authorized_users() -> list[dict]:
        """Get all users with valid Google tokens (authorized for notifications)."""
        db = SessionLocal()
        try:
            result = db.execute(text("""
                SELECT user_id, telegram_chat_id, access_token, refresh_token
                FROM google_tokens
                WHERE telegram_chat_id IS NOT NULL
            """))
            return [dict(row._mapping) for row in result.fetchall()]
        finally:
            db.close()

    @staticmethod
    async def send_morning_summaries():
        """Send morning summary to all authorized users."""
        users = await NotificationService.get_authorized_users()
        logger.info(f"[Notification] Sending morning summary to {len(users)} users")

        for user in users:
            try:
                await NotificationService._send_user_morning_summary(user)
            except Exception as e:
                logger.error(f"[Notification] Error for user {user['user_id']}: {e}")

    @staticmethod
    async def _send_user_morning_summary(user: dict):
        """Build and send morning summary for one user."""
        from app.api.endpoints.telegram import build_summary

        tokens = {
            "access_token": user["access_token"],
            "refresh_token": user["refresh_token"]
        }

        events_result = await google_service.get_events(
            token_data=tokens,
            user_id=user["user_id"],
            query_type="today"
        )
        tasks_result = await google_service.get_pending_tasks(token_data=tokens)

        events = events_result.get("events", [])
        tasks = tasks_result.get("tasks", [])
        msg_parts, voice_parts = build_summary(events, tasks)

        await NotificationService.send_telegram_message(
            chat_id=user["telegram_chat_id"],
            msg_text="\n".join(msg_parts),
            voice=True
        )

        logger.info(f"[Notification] Morning summary sent to {user['telegram_chat_id']}")

    @staticmethod
    async def check_and_send_reminders():
        """Check for events starting soon and send reminders."""
        users = await NotificationService.get_authorized_users()

        for user in users:
            try:
                await NotificationService._check_user_reminders(user)
            except Exception as e:
                logger.error(f"[Notification] Reminder error for {user['user_id']}: {e}")

    @staticmethod
    async def _check_user_reminders(user: dict):
        """Check upcoming events for one user and send reminders."""
        tokens = {
            "access_token": user["access_token"],
            "refresh_token": user["refresh_token"]
        }

        result = await google_service.get_events(
            token_data=tokens,
            user_id=user["user_id"],
            query_type="today"
        )

        events = result.get("events", [])
        now = datetime.now()

        for event in events:
            if "T" not in event["start"]:
                continue  # Skip all-day events

            try:
                event_time = datetime.fromisoformat(event["start"].replace("Z", "+00:00"))
                event_time = event_time.replace(tzinfo=None)
            except (ValueError, AttributeError):
                continue

            minutes_until = (event_time - now).total_seconds() / 60

            if 10 <= minutes_until <= 20:
                if not await NotificationService._already_notified(user["user_id"], event["id"]):
                    await NotificationService._send_reminder(user, event)
                    await NotificationService._mark_notified(user["user_id"], event["id"])

    # In-memory notification tracking with bounded size
    _notified_events: dict[str, datetime] = {}

    @staticmethod
    async def _already_notified(user_id: str, event_id: str) -> bool:
        key = f"{user_id}:{event_id}"
        return key in NotificationService._notified_events

    @staticmethod
    async def _mark_notified(user_id: str, event_id: str):
        key = f"{user_id}:{event_id}"
        NotificationService._notified_events[key] = datetime.now()

        # Cleanup old entries to prevent memory leak
        if len(NotificationService._notified_events) > _NOTIFIED_EVENTS_MAX:
            cutoff = datetime.now() - timedelta(hours=24)
            NotificationService._notified_events = {
                k: v for k, v in NotificationService._notified_events.items()
                if v > cutoff
            }

    @staticmethod
    async def _send_reminder(user: dict, event: dict):
        """Send event reminder notification."""
        time_str = event["start"].split("T")[1][:5] if "T" in event["start"] else ""

        msg = f"⏰ **Za 15 minut:** {event['emoji']} {event['title']}"
        if time_str:
            msg += f"\n🕐 {time_str}"

        await NotificationService.send_telegram_message(
            chat_id=user["telegram_chat_id"],
            msg_text=msg,
            voice=False
        )

        logger.info(f"[Notification] Reminder sent: {event['title']} to {user['telegram_chat_id']}")
