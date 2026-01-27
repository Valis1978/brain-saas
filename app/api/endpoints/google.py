"""
Google OAuth API Endpoints
Handles authentication flow and token management
"""

import os
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import text
from app.services.google_service import google_service
from app.db.session import SessionLocal

router = APIRouter(prefix="/api/v1/google", tags=["google"])


@router.get("/auth")
async def initiate_google_auth(user_id: str = Query(..., description="Telegram user ID")):
    """Initiate Google OAuth flow for a user."""
    try:
        authorization_url = google_service.get_authorization_url(user_id)
        return RedirectResponse(url=authorization_url)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to initiate OAuth: {str(e)}")


@router.get("/callback")
async def google_oauth_callback(
    code: str = Query(None),
    state: str = Query(None),  # Contains user_id
    error: str = Query(None)
):
    """Handle OAuth callback from Google."""
    
    if error:
        return HTMLResponse(content=f"""
        <html>
            <head><title>Brain SaaS - Chyba</title></head>
            <body style="font-family: system-ui; padding: 40px; text-align: center;">
                <h1>❌ Autorizace selhala</h1>
                <p>Chyba: {error}</p>
                <p>Zkuste to prosím znovu.</p>
            </body>
        </html>
        """, status_code=400)
    
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state parameter")
    
    user_id = state
    
    try:
        # Exchange code for tokens
        tokens = google_service.exchange_code_for_tokens(code)
        
        # Store tokens in database
        db = SessionLocal()
        try:
            # Check if user already has tokens
            existing = db.execute(
                text("SELECT id FROM google_tokens WHERE user_id = :user_id"),
                {"user_id": user_id}
            ).fetchone()
            
            if existing:
                # Update existing tokens
                db.execute(
                    text("""
                        UPDATE google_tokens 
                        SET access_token = :access_token, 
                            refresh_token = :refresh_token,
                            expires_at = :expires_at,
                            updated_at = NOW()
                        WHERE user_id = :user_id
                    """),
                    {
                        "user_id": user_id,
                        "access_token": tokens["access_token"],
                        "refresh_token": tokens["refresh_token"],
                        "expires_at": tokens.get("expires_at")
                    }
                )
            else:
                # Insert new tokens
                db.execute(
                    text("""
                        INSERT INTO google_tokens (user_id, access_token, refresh_token, expires_at)
                        VALUES (:user_id, :access_token, :refresh_token, :expires_at)
                    """),
                    {
                        "user_id": user_id,
                        "access_token": tokens["access_token"],
                        "refresh_token": tokens["refresh_token"],
                        "expires_at": tokens.get("expires_at")
                    }
                )
            
            db.commit()
        finally:
            db.close()
        
        return HTMLResponse(content=f"""
        <html>
            <head>
                <title>Brain SaaS - Úspěch</title>
                <style>
                    body {{
                        font-family: system-ui, -apple-system, sans-serif;
                        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                        color: white;
                        min-height: 100vh;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        margin: 0;
                    }}
                    .card {{
                        background: rgba(255,255,255,0.1);
                        backdrop-filter: blur(10px);
                        border-radius: 24px;
                        padding: 60px;
                        text-align: center;
                        border: 1px solid rgba(255,255,255,0.1);
                    }}
                    .icon {{ font-size: 80px; margin-bottom: 20px; }}
                    h1 {{ margin: 0 0 16px 0; }}
                    p {{ color: rgba(255,255,255,0.7); margin: 0; }}
                </style>
            </head>
            <body>
                <div class="card">
                    <div class="icon">🧠✨</div>
                    <h1>Google účet propojen!</h1>
                    <p>Nyní můžete používat Brain SaaS s Google Calendar a Tasks.</p>
                    <p style="margin-top: 20px; font-size: 14px;">Můžete toto okno zavřít.</p>
                </div>
            </body>
        </html>
        """)
        
    except Exception as e:
        print(f"OAuth callback error: {e}")
        return HTMLResponse(content=f"""
        <html>
            <head><title>Brain SaaS - Chyba</title></head>
            <body style="font-family: system-ui; padding: 40px; text-align: center; background: #1a1a2e; color: white;">
                <h1>❌ Něco se pokazilo</h1>
                <p>{str(e)}</p>
            </body>
        </html>
        """, status_code=500)


@router.get("/status")
async def check_google_status(user_id: str = Query(..., description="Telegram user ID")):
    """Check if a user has connected their Google account."""
    db = SessionLocal()
    try:
        result = db.execute(
            text("SELECT id, expires_at FROM google_tokens WHERE user_id = :user_id"),
            {"user_id": user_id}
        ).fetchone()
        
        if result:
            return {
                "connected": True,
                "expires_at": result.expires_at.isoformat() if result.expires_at else None
            }
        else:
            return {"connected": False}
    finally:
        db.close()


# =============================================================================
# TASKS API ENDPOINTS
# =============================================================================

def get_user_tokens(user_id: str) -> dict:
    """Helper to get user tokens from database."""
    db = SessionLocal()
    try:
        result = db.execute(
            text("SELECT access_token, refresh_token, expires_at FROM google_tokens WHERE user_id = :user_id"),
            {"user_id": user_id}
        ).fetchone()
        
        if not result:
            return None
        
        return {
            "access_token": result.access_token,
            "refresh_token": result.refresh_token,
            "expires_at": result.expires_at.isoformat() if result.expires_at else None
        }
    finally:
        db.close()


@router.get("/tasks")
async def get_tasks(user_id: str = Query(..., description="Telegram user ID")):
    """Get all pending tasks for a user."""
    tokens = get_user_tokens(user_id)
    if not tokens:
        raise HTTPException(status_code=401, detail="User not authenticated with Google")
    
    try:
        result = google_service.get_pending_tasks(tokens)
        return {"tasks": result.get("tasks", []), "success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


from pydantic import BaseModel
from typing import Optional

class CreateTaskRequest(BaseModel):
    title: str
    notes: Optional[str] = None
    due_date: Optional[str] = None  # YYYY-MM-DD

class CreateEventRequest(BaseModel):
    title: str
    date: str  # YYYY-MM-DD
    time: Optional[str] = None  # HH:MM
    description: Optional[str] = None
    category: Optional[str] = None  # 'work', 'personal', or None for auto


@router.post("/tasks")
async def create_task(
    request: CreateTaskRequest,
    user_id: str = Query(..., description="Telegram user ID")
):
    """Create a new task."""
    tokens = get_user_tokens(user_id)
    if not tokens:
        raise HTTPException(status_code=401, detail="User not authenticated with Google")
    
    try:
        result = await google_service.create_task(
            tokens, 
            title=request.title, 
            notes=request.notes, 
            due_date=request.due_date
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/events")
async def create_event(
    request: CreateEventRequest,
    user_id: str = Query(..., description="Telegram user ID")
):
    """Create a new calendar event."""
    tokens = get_user_tokens(user_id)
    if not tokens:
        raise HTTPException(status_code=401, detail="User not authenticated with Google")
    
    try:
        result = await google_service.create_calendar_event(
            token_data=tokens,
            title=request.title,
            date=request.date,
            time=request.time,
            description=request.description,
            user_id=user_id,
            category=request.category
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/{task_id}/complete")
async def complete_task(task_id: str, user_id: str = Query(..., description="Telegram user ID")):
    """Mark a task as completed."""
    tokens = get_user_tokens(user_id)
    if not tokens:
        raise HTTPException(status_code=401, detail="User not authenticated with Google")
    
    try:
        result = google_service.complete_task(tokens, task_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CALENDAR API ENDPOINTS
# =============================================================================

@router.get("/events")
async def get_events(
    user_id: str = Query(..., description="Telegram user ID"),
    query_type: str = Query("week", description="Query type: today, tomorrow, week")
):
    """Get calendar events for a user."""
    tokens = get_user_tokens(user_id)
    if not tokens:
        raise HTTPException(status_code=401, detail="User not authenticated with Google")
    
    try:
        result = google_service.get_events(tokens, user_id, query_type)
        return {"events": result.get("events", []), "success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/events/{event_id}")
async def update_event(
    event_id: str,
    user_id: str = Query(..., description="Telegram user ID"),
    calendar_id: str = Query(..., description="Calendar ID"),
    new_date: str = Query(None, description="New date (YYYY-MM-DD)"),
    new_time: str = Query(None, description="New time (HH:MM)")
):
    """Update a calendar event."""
    tokens = get_user_tokens(user_id)
    if not tokens:
        raise HTTPException(status_code=401, detail="User not authenticated with Google")
    
    try:
        result = google_service.update_event(tokens, user_id, event_id, calendar_id, new_date, new_time)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/events/{event_id}")
async def delete_event(
    event_id: str,
    user_id: str = Query(..., description="Telegram user ID"),
    calendar_id: str = Query(..., description="Calendar ID")
):
    """Delete a calendar event."""
    tokens = get_user_tokens(user_id)
    if not tokens:
        raise HTTPException(status_code=401, detail="User not authenticated with Google")
    
    try:
        result = google_service.delete_event(tokens, event_id, calendar_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/events/{event_id}/move")
async def move_event(
    event_id: str,
    user_id: str = Query(..., description="Telegram user ID"),
    source_calendar_id: str = Query(..., description="Source calendar ID"),
    target_calendar_type: str = Query(..., description="Target calendar type: work or personal")
):
    """Move an event between calendars."""
    tokens = get_user_tokens(user_id)
    if not tokens:
        raise HTTPException(status_code=401, detail="User not authenticated with Google")
    
    try:
        result = google_service.move_event_to_calendar(tokens, user_id, event_id, source_calendar_id, target_calendar_type)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

