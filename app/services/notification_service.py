"""
Notification service for sending proactive Telegram messages.

Handles:
- Morning summaries
- Event reminders
- Notification deduplication
"""
import os
from datetime import datetime, timedelta
from typing import Optional
import httpx
from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.google_service import google_service
from app.services.ai_service import ai_service
from app.utils.messages import MSG

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
VOICE_ENABLED = os.getenv("VOICE_RESPONSE_ENABLED", "true").lower() == "true"


class NotificationService:
    """Service for sending proactive notifications."""
    
    @staticmethod
    async def send_telegram_message(chat_id: str, text: str, voice: bool = False):
        """Send a message to Telegram user."""
        if not TELEGRAM_BOT_TOKEN:
            print("[Notification] Missing TELEGRAM_BOT_TOKEN")
            return False
        
        async with httpx.AsyncClient() as client:
            # Send text message
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text[:4000],
                    "parse_mode": "Markdown"
                }
            )
            
            # Optional voice response
            if voice and VOICE_ENABLED:
                try:
                    audio_bytes = await ai_service.text_to_speech(text)
                    if audio_bytes:
                        import tempfile
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
                        os.remove(tmp_name)
                except Exception as e:
                    print(f"[Notification] Voice failed: {e}")
        
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
        print(f"[Notification] Sending morning summary to {len(users)} users")
        
        for user in users:
            try:
                await NotificationService._send_user_morning_summary(user)
            except Exception as e:
                print(f"[Notification] Error for user {user['user_id']}: {e}")
    
    @staticmethod
    async def _send_user_morning_summary(user: dict):
        """Build and send morning summary for one user."""
        tokens = {
            "access_token": user["access_token"],
            "refresh_token": user["refresh_token"]
        }
        
        # Get today's events
        events_result = await google_service.get_events(
            token_data=tokens,
            user_id=user["user_id"],
            query_type="today"
        )
        
        # Get pending tasks
        tasks_result = await google_service.get_pending_tasks(token_data=tokens)
        
        # Build message
        msg_parts = [MSG.SUMMARY_HEADER]
        voice_parts = [MSG.SUMMARY_VOICE_INTRO]
        
        events = events_result.get("events", [])
        if events:
            msg_parts.append(MSG.SUMMARY_EVENTS)
            voice_parts.append(MSG.SUMMARY_VOICE_EVENTS)
            for e in events:
                time_str = e["start"].split("T")[1][:5] if "T" in e["start"] else MSG.ALL_DAY
                msg_parts.append(f"  {e['emoji']} {time_str} - {e['title']}")
                voice_parts.append(f"{time_str} {e['title']}")
        else:
            msg_parts.append(MSG.NO_EVENTS_TODAY)
            voice_parts.append(MSG.SUMMARY_VOICE_NO_EVENTS)
        
        tasks = tasks_result.get("tasks", [])
        if tasks:
            msg_parts.append(MSG.SUMMARY_TASKS)
            voice_parts.append(MSG.SUMMARY_VOICE_TASKS)
            for t in tasks[:5]:
                prefix = "⚠️" if t["is_overdue"] else "☐"
                msg_parts.append(f"  {prefix} {t['title']}")
                voice_parts.append(t['title'])
        else:
            msg_parts.append(MSG.NO_TASKS_TODAY)
            voice_parts.append(MSG.SUMMARY_VOICE_NO_TASKS)
        
        # Send notification
        await NotificationService.send_telegram_message(
            chat_id=user["telegram_chat_id"],
            text="\n".join(msg_parts),
            voice=True
        )
        
        print(f"[Notification] Morning summary sent to {user['telegram_chat_id']}")
    
    @staticmethod
    async def check_and_send_reminders():
        """Check for events starting soon and send reminders."""
        users = await NotificationService.get_authorized_users()
        
        for user in users:
            try:
                await NotificationService._check_user_reminders(user)
            except Exception as e:
                print(f"[Notification] Reminder error for {user['user_id']}: {e}")
    
    @staticmethod
    async def _check_user_reminders(user: dict):
        """Check upcoming events for one user and send reminders."""
        tokens = {
            "access_token": user["access_token"],
            "refresh_token": user["refresh_token"]
        }
        
        # Get today's events
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
            
            # Parse event time
            try:
                event_time = datetime.fromisoformat(event["start"].replace("Z", "+00:00"))
                event_time = event_time.replace(tzinfo=None)  # Simplify
            except:
                continue
            
            # Check if event is 10-20 min away (to catch it in our 5-min interval)
            minutes_until = (event_time - now).total_seconds() / 60
            
            if 10 <= minutes_until <= 20:
                # Check if already notified (simple in-memory for now)
                if not await NotificationService._already_notified(user["user_id"], event["id"]):
                    await NotificationService._send_reminder(user, event)
                    await NotificationService._mark_notified(user["user_id"], event["id"])
    
    # Simple in-memory notification tracking (should be DB in production)
    _notified_events: set = set()
    
    @staticmethod
    async def _already_notified(user_id: str, event_id: str) -> bool:
        key = f"{user_id}:{event_id}"
        return key in NotificationService._notified_events
    
    @staticmethod
    async def _mark_notified(user_id: str, event_id: str):
        key = f"{user_id}:{event_id}"
        NotificationService._notified_events.add(key)
    
    @staticmethod
    async def _send_reminder(user: dict, event: dict):
        """Send event reminder notification."""
        time_str = event["start"].split("T")[1][:5] if "T" in event["start"] else ""
        
        msg = f"⏰ **Za 15 minut:** {event['emoji']} {event['title']}"
        if time_str:
            msg += f"\n🕐 {time_str}"
        
        await NotificationService.send_telegram_message(
            chat_id=user["telegram_chat_id"],
            text=msg,
            voice=False
        )
        
        print(f"[Notification] Reminder sent: {event['title']} to {user['telegram_chat_id']}")
