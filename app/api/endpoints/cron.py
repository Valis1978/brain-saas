"""
Cron trigger endpoints for manual testing and external schedulers.
"""
from fastapi import APIRouter, Query
from app.services.notification_service import NotificationService

router = APIRouter()


@router.post("/trigger")
async def trigger_notification(
    type: str = Query(..., description="Notification type: 'morning' or 'reminders'")
):
    """
    Manually trigger notifications for testing.
    
    - `morning`: Send morning summary to all users
    - `reminders`: Check and send event reminders
    """
    if type == "morning":
        await NotificationService.send_morning_summaries()
        return {"status": "ok", "type": "morning_summary", "message": "Morning summaries sent"}
    
    elif type == "reminders":
        await NotificationService.check_and_send_reminders()
        return {"status": "ok", "type": "reminders", "message": "Reminder check completed"}
    
    else:
        return {"status": "error", "message": f"Unknown type: {type}. Use 'morning' or 'reminders'"}


@router.get("/status")
async def scheduler_status():
    """Get scheduler status and next run times."""
    from app.services.scheduler_service import scheduler
    
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "next_run": str(job.next_run_time) if job.next_run_time else None
        })
    
    return {
        "running": scheduler.running,
        "jobs": jobs
    }
