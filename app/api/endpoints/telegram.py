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
    category = intent_data.get("category")  # AI-detected category (work/personal)
    query_type = intent_data.get("query_type", "today")
    target_event = intent_data.get("target_event")
    new_date = intent_data.get("new_date")
    new_time = intent_data.get("new_time")
    target_calendar = intent_data.get("target_calendar")  # For moving between calendars
    
    result = None
    
    try:
        # ==================== CREATE INTENTS ====================
        if intent == "EVENT" and date:
            result = await google_service.create_calendar_event(
                token_data=tokens,
                title=title,
                date=date,
                time=time,
                description=description,
                user_id=user_id,
                category=category
            )
            
            if result.get("success"):
                emoji = result.get("calendar_emoji", "📅")
                category_label = "Práce" if result.get("category") == "work" else "Osobní"
                
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": f"{emoji} Přidáno do kalendáře **{category_label}**!\n\n**{title}**\n🔗 {result.get('html_link', '')}"[:4000],
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
        
        # ==================== QUERY INTENTS ====================
        elif intent == "QUERY_CALENDAR":
            result = await google_service.get_events(
                token_data=tokens,
                user_id=user_id,
                query_type=query_type,
                specific_date=date
            )
            
            if result.get("success"):
                events = result.get("events", [])
                if events:
                    # Format events nicely
                    label = {
                        "today": "📅 Dnešek",
                        "tomorrow": "📅 Zítřek", 
                        "week": "📅 Tento týden"
                    }.get(query_type, "📅 Události")
                    
                    event_list = []
                    for e in events:
                        time_str = ""
                        if "T" in e["start"]:
                            time_str = e["start"].split("T")[1][:5] + " - "
                        event_list.append(f"{e['emoji']} {time_str}**{e['title']}**")
                    
                    msg = f"{label}:\n\n" + "\n".join(event_list)
                else:
                    msg = "📅 Nemáš žádné nadcházející události."
                
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": chat_id, "text": msg[:4000], "parse_mode": "Markdown"}
                    )
        
        elif intent == "QUERY_TASKS":
            result = await google_service.get_pending_tasks(token_data=tokens)
            
            if result.get("success"):
                tasks = result.get("tasks", [])
                overdue = result.get("overdue_count", 0)
                
                if tasks:
                    task_list = []
                    for t in tasks:
                        prefix = "⚠️" if t["is_overdue"] else "☐"
                        due_str = f" (do {t['due']})" if t["due"] else ""
                        task_list.append(f"{prefix} **{t['title']}**{due_str}")
                    
                    header = f"📋 Úkoly ({len(tasks)}"
                    if overdue > 0:
                        header += f", ⚠️ {overdue} prošlých"
                    header += "):\n\n"
                    
                    msg = header + "\n".join(task_list)
                else:
                    msg = "✅ Nemáš žádné nesplněné úkoly!"
                
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": chat_id, "text": msg[:4000], "parse_mode": "Markdown"}
                    )
        
        # ==================== UPDATE/DELETE INTENTS ====================
        elif intent == "UPDATE_EVENT" and target_event:
            # First search for the event
            search_result = await google_service.search_event(
                token_data=tokens,
                user_id=user_id,
                search_query=target_event
            )
            
            if search_result.get("success") and search_result.get("events"):
                events = search_result["events"]
                
                if len(events) == 1:
                    # Found exactly one, update it
                    event = events[0]
                    
                    # Check if this is a calendar move request
                    if target_calendar:
                        move_result = await google_service.move_event_to_calendar(
                            token_data=tokens,
                            user_id=user_id,
                            event_id=event["id"],
                            source_calendar_id=event["calendar_id"],
                            target_calendar_type=target_calendar
                        )
                        
                        if move_result.get("success"):
                            target_name = move_result.get("target_calendar_name", target_calendar)
                            emoji = "💼" if target_calendar == "work" else "🏠"
                            msg = f"{emoji} Událost **{event['title']}** přesunuta do kalendáře **{target_name}**!"
                            
                            async with httpx.AsyncClient() as client:
                                await client.post(
                                    f"https://api.telegram.org/bot{token}/sendMessage",
                                    json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}
                                )
                        else:
                            error_msg = move_result.get("error", "Neznámá chyba")
                            async with httpx.AsyncClient() as client:
                                await client.post(
                                    f"https://api.telegram.org/bot{token}/sendMessage",
                                    json={"chat_id": chat_id, "text": f"❌ {error_msg}"}
                                )
                    else:
                        # This is a date/time update
                        # Calculate new_date if "tomorrow" was mentioned
                        from datetime import datetime, timedelta
                        if not new_date and "zítra" in str(intent_data).lower():
                            new_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
                        
                        update_result = await google_service.update_event(
                            token_data=tokens,
                            user_id=user_id,
                            event_id=event["id"],
                            calendar_id=event["calendar_id"],
                            new_date=new_date,
                            new_time=new_time
                        )
                        
                        if update_result.get("success"):
                            msg = f"✅ Událost **{event['title']}** přesunuta!"
                            if new_date:
                                msg += f"\n📅 Nové datum: {new_date}"
                            if new_time:
                                msg += f"\n⏰ Nový čas: {new_time}"
                            
                            async with httpx.AsyncClient() as client:
                                await client.post(
                                    f"https://api.telegram.org/bot{token}/sendMessage",
                                    json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}
                                )
                else:
                    # Multiple events found, ask for clarification
                    event_list = "\n".join([f"• {e['title']} ({e['start'][:10]})" for e in events[:5]])
                    msg = f"🔍 Nalezeno {len(events)} událostí:\n{event_list}\n\nUpřesni prosím kterou myslíš."
                    
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            f"https://api.telegram.org/bot{token}/sendMessage",
                            json={"chat_id": chat_id, "text": msg}
                        )
            else:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": chat_id, "text": f"❌ Nenašel jsem událost obsahující '{target_event}'"}
                    )
        
        elif intent == "DELETE_EVENT" and target_event:
            # Search for the event
            search_result = await google_service.search_event(
                token_data=tokens,
                user_id=user_id,
                search_query=target_event
            )
            
            if search_result.get("success") and search_result.get("events"):
                events = search_result["events"]
                
                if len(events) == 1:
                    event = events[0]
                    delete_result = await google_service.delete_event(
                        token_data=tokens,
                        event_id=event["id"],
                        calendar_id=event["calendar_id"]
                    )
                    
                    if delete_result.get("success"):
                        msg = f"🗑️ Událost **{delete_result['deleted_title']}** zrušena!"
                        async with httpx.AsyncClient() as client:
                            await client.post(
                                f"https://api.telegram.org/bot{token}/sendMessage",
                                json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}
                            )
                else:
                    event_list = "\n".join([f"• {e['title']} ({e['start'][:10]})" for e in events[:5]])
                    msg = f"🔍 Nalezeno {len(events)} událostí:\n{event_list}\n\nUpřesni prosím kterou zrušit."
                    
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            f"https://api.telegram.org/bot{token}/sendMessage",
                            json={"chat_id": chat_id, "text": msg}
                        )
            else:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": chat_id, "text": f"❌ Nenašel jsem událost obsahující '{target_event}'"}
                    )
        
        # SUMMARY - combine calendar and tasks
        elif intent == "SUMMARY":
            # Get today's events
            events_result = await google_service.get_events(
                token_data=tokens,
                user_id=user_id,
                query_type="today"
            )
            
            # Get pending tasks
            tasks_result = await google_service.get_pending_tasks(token_data=tokens)
            
            msg_parts = ["📊 **Přehled dne:**\n"]
            
            events = events_result.get("events", [])
            if events:
                msg_parts.append("📅 **Události:**")
                for e in events:
                    time_str = e["start"].split("T")[1][:5] if "T" in e["start"] else "Celý den"
                    msg_parts.append(f"  {e['emoji']} {time_str} - {e['title']}")
            else:
                msg_parts.append("📅 Žádné události na dnešek")
            
            tasks = tasks_result.get("tasks", [])
            if tasks:
                msg_parts.append("\n📋 **Úkoly:**")
                for t in tasks[:5]:  # Max 5 tasks
                    prefix = "⚠️" if t["is_overdue"] else "☐"
                    msg_parts.append(f"  {prefix} {t['title']}")
            else:
                msg_parts.append("\n✅ Žádné nesplněné úkoly")
            
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": "\n".join(msg_parts)[:4000], "parse_mode": "Markdown"}
                )
                
    except Exception as e:
        print(f"Error processing with Google: {e}")
        import traceback
        traceback.print_exc()
    
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
