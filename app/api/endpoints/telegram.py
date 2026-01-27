from fastapi import APIRouter, Request, Header, HTTPException
from sqlalchemy import text
from app.services.auth_service import is_authorized
from app.services.ai_service import ai_service
from app.services.google_service import google_service
from app.db.session import SessionLocal
from app.models.capture import Capture
import httpx
import tempfile
import os
import json

router = APIRouter()


async def get_user_google_tokens(user_id: str) -> dict | None:
    """Get Google tokens for a user if they exist."""
    db = SessionLocal()
    try:
        result = db.execute(
            text("SELECT access_token, refresh_token, expires_at FROM google_tokens WHERE user_id = :user_id"),
            {"user_id": user_id}
        ).fetchone()
        
        if result:
            return {
                "access_token": result.access_token,
                "refresh_token": result.refresh_token,
                "expires_at": result.expires_at.isoformat() if result.expires_at else None
            }
        return None
    finally:
        db.close()


async def process_with_google(user_id: str, intent_data: dict, token: str, chat_id: str | int):
    """Process intent with Google Calendar/Tasks if user is connected."""
    tokens = await get_user_google_tokens(user_id)
    
    if not tokens:
        return None  # User not connected to Google
    
    intent = intent_data.get("intent")
    title = intent_data.get("title", "Bez názvu")
    date = intent_data.get("date")
    time = intent_data.get("time")
    description = intent_data.get("description")
    
    result = None
    
    try:
        if intent == "EVENT" and date:
            result = await google_service.create_calendar_event(
                token_data=tokens,
                title=title,
                date=date,
                time=time,
                description=description
            )
            
            if result.get("success"):
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": f"📅 Událost přidána do Google Kalendáře!\n\n**{title}**\n🔗 {result.get('html_link', '')}"[:4000],
                            "parse_mode": "Markdown"
                        }
                    )
        
        elif intent == "TODO":
            result = await google_service.create_task(
                token_data=tokens,
                title=title,
                notes=description,
                due_date=date
            )
            
            if result.get("success"):
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": f"✅ Úkol přidán do Google Tasks!\n\n**{title}**",
                            "parse_mode": "Markdown"
                        }
                    )
    except Exception as e:
        print(f"Error processing with Google: {e}")
    
    return result


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(None)
):
    # 1. Verify Secret Token
    expected_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if expected_secret and x_telegram_bot_api_secret_token != expected_secret:
        raise HTTPException(status_code=401, detail="Unauthorized")

    update = await request.json()
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    
    if not chat_id or not user_id:
        return {"ok": True}

    # 2. Authorization (Family Mode)
    if not is_authorized(str(user_id)):
        print(f"Unauthorized access attempt from user_id: {user_id}")
        return {"ok": True}

    token = os.getenv("TELEGRAM_BOT_TOKEN")

    # 3. Handle Voice Message
    if "voice" in message:
        print(f"Received voice message from {user_id}")
        file_id = message["voice"]["file_id"]
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}")
            file_data = resp.json()
            if not file_data.get("ok"):
                return {"ok": True}
            
            file_path = file_data["result"]["file_path"]
            file_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
                audio_resp = await client.get(file_url)
                tmp.write(audio_resp.content)
                tmp_name = tmp.name

            try:
                transcription = await ai_service.transcribe_voice(tmp_name)
                print(f"Transcription: {transcription}")
                
                intent_data = await ai_service.extract_intent(transcription)
                print(f"Intent: {intent_data}")
                
                # Save to Database
                db = SessionLocal()
                new_capture = Capture(
                    user_id=str(user_id),
                    user_name=message.get("from", {}).get("first_name"),
                    content_type="voice",
                    raw_content=transcription,
                    intent_data=intent_data,
                    status="PROCESSED"
                )
                db.add(new_capture)
                db.commit()
                db.close()
                
                # Send basic confirmation
                await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": f"🎤 Přepsáno: {transcription}\n\n🤖 Zpracováno jako: {intent_data.get('intent', 'UNKNOWN')}"}
                )
                
                # Process with Google (if connected)
                await process_with_google(str(user_id), intent_data, token, chat_id)
                
            finally:
                if os.path.exists(tmp_name):
                    os.remove(tmp_name)

    # 4. Handle Text Message
    elif "text" in message:
        text_content = message.get("text")
        print(f"Received text message from {user_id}: {text_content}")
        
        intent_data = await ai_service.extract_intent(text_content)
        
        # Save to Database
        db = SessionLocal()
        new_capture = Capture(
            user_id=str(user_id),
            user_name=message.get("from", {}).get("first_name"),
            content_type="text",
            raw_content=text_content,
            intent_data=intent_data,
            status="PROCESSED"
        )
        db.add(new_capture)
        db.commit()
        db.close()

        # Send basic confirmation
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": f"✅ Zapsáno: {intent_data.get('title', 'Poznámka')}"}
            )
            
        # Process with Google (if connected)
        await process_with_google(str(user_id), intent_data, token, chat_id)

    return {"ok": True}
