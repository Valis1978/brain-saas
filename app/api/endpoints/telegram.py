from app.services.auth_service import is_authorized
from app.services.ai_service import ai_service
from app.db.session import SessionLocal
from app.models.capture import Capture
import httpx
import tempfile
import os
import json

router = APIRouter()

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
        # Optionally send a message back saying unauthorized
        print(f"Unauthorized access attempt from user_id: {user_id}")
        return {"ok": True}

    # 3. Handle Voice Message
    if "voice" in message:
        print(f"Received voice message from {user_id}")
        file_id = message["voice"]["file_id"]
        
        # Get file path from Telegram
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}")
            file_data = resp.json()
            if not file_data.get("ok"):
                return {"ok": True}
            
            file_path = file_data["result"]["file_path"]
            file_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
            
            # Download to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
                audio_resp = await client.get(file_url)
                tmp.write(audio_resp.content)
                tmp_name = tmp.name

            # Transcribe
            try:
                transcription = await ai_service.transcribe_voice(tmp_name)
                print(f"Transcription: {transcription}")
                
                # Extract Intent
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
                
                # Send confirmation back to user
                await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": f"🎤 Přepsáno: {transcription}\n\n🤖 Zpracováno jako: {intent_data.get('intent', 'UNKNOWN')}"}
                )
            finally:
                if os.path.exists(tmp_name):
                    os.remove(tmp_name)

    # 4. Handle Text Message
    elif "text" in message:
        text = message.get("text")
        print(f"Received text message from {user_id}: {text}")
        
        # Extract Intent
        intent_data = await ai_service.extract_intent(text)
        
        # Save to Database
        db = SessionLocal()
        new_capture = Capture(
            user_id=str(user_id),
            user_name=message.get("from", {}).get("first_name"),
            content_type="text",
            raw_content=text,
            intent_data=intent_data,
            status="PROCESSED"
        )
        db.add(new_capture)
        db.commit()
        db.close()

        # Send confirmation
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": f"✅ Zapsáno: {intent_data.get('title', 'Poznámka')}"}
            )

    return {"ok": True}
