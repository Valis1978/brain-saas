"""
Scheduler service for proactive notifications.

Features:
- Morning summary at 7:00 CET
- Event reminders 15 min before
"""
import os
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Configuration
MORNING_HOUR = int(os.getenv("MORNING_SUMMARY_HOUR", "7"))
REMINDER_MINUTES = int(os.getenv("REMINDER_MINUTES_BEFORE", "15"))
TIMEZONE = "Europe/Prague"

# Global scheduler instance
scheduler = AsyncIOScheduler(timezone=TIMEZONE)


async def send_morning_summary():
    """
    Send daily summary to all authorized users at 7:00.
    Contains today's events and pending tasks.
    """
    from app.services.notification_service import NotificationService
    
    print(f"[Scheduler] Running morning summary at {datetime.now()}")
    
    try:
        await NotificationService.send_morning_summaries()
    except Exception as e:
        print(f"[Scheduler] Morning summary error: {e}")


async def check_upcoming_events():
    """
    Check for events starting in the next 15-20 minutes.
    Run every 5 minutes to catch events.
    """
    from app.services.notification_service import NotificationService
    
    print(f"[Scheduler] Checking upcoming events at {datetime.now()}")
    
    try:
        await NotificationService.check_and_send_reminders()
    except Exception as e:
        print(f"[Scheduler] Event reminder error: {e}")


def start_scheduler():
    """Initialize and start the scheduler."""
    # Morning summary - every day at 7:00
    scheduler.add_job(
        send_morning_summary,
        CronTrigger(hour=MORNING_HOUR, minute=0, timezone=TIMEZONE),
        id="morning_summary",
        replace_existing=True
    )
    
    # Event reminders - check every 5 minutes
    scheduler.add_job(
        check_upcoming_events,
        "interval",
        minutes=5,
        id="event_reminders",
        replace_existing=True
    )
    
    scheduler.start()
    print(f"[Scheduler] Started with morning summary at {MORNING_HOUR}:00 {TIMEZONE}")


def stop_scheduler():
    """Gracefully stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        print("[Scheduler] Stopped")
