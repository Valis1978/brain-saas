from fastapi import APIRouter, Request, Header, HTTPException
from sqlalchemy import text
from app.services.auth_service import is_authorized
from app.services.ai_service import ai_service
from app.services.google_service import google_service
from app.db.session import SessionLocal
from app.models.capture import Capture
from app.utils.messages import MSG
from app.utils.summary import build_summary
import httpx
import tempfile
import os
import json
import logging
from datetime import datetime, timedelta

router = APIRouter()
logger = logging.getLogger(__name__)

# Voice response settings
VOICE_RESPONSE_ENABLED = os.getenv("VOICE_RESPONSE_ENABLED", "true").lower() == "true"


async def send_telegram_text(chat_id: str | int, text_content: str, token: str, parse_mode: str = "Markdown"):
    """Send a text message to Telegram with error handling."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text_content[:4000],
                    "parse_mode": parse_mode
                },
                timeout=15.0
            )
            if resp.status_code != 200:
                logger.warning(f"Telegram sendMessage failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")


async def send_voice_response(chat_id: str | int, text_content: str, token: str):
    """
    Send a voice message response to Telegram.
    Falls back to text if TTS fails.
    """
    if not VOICE_RESPONSE_ENABLED:
        return False

    try:
        audio_bytes = await ai_service.text_to_speech(text_content)
        if not audio_bytes:
            return False

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
            tmp.write(audio_bytes)
            tmp_name = tmp.name

        try:
            async with httpx.AsyncClient() as client:
                with open(tmp_name, "rb") as audio_file:
                    files = {"voice": ("response.mp3", audio_file, "audio/mpeg")}
                    data = {"chat_id": chat_id}
                    await client.post(
                        f"https://api.telegram.org/bot{token}/sendVoice",
                        data=data,
                        files=files,
                        timeout=30.0
                    )
            return True
        finally:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)

    except Exception as e:
        logger.error(f"Voice response error: {e}")
        return False


def save_capture(user_id: str, user_name: str | None, content_type: str, raw_content: str, intent_data: dict):
    """Save a capture to the database with proper session management."""
    db = SessionLocal()
    try:
        new_capture = Capture(
            user_id=str(user_id),
            user_name=user_name,
            content_type=content_type,
            raw_content=raw_content,
            intent_data=intent_data,
            status="PROCESSED"
        )
        db.add(new_capture)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to save capture: {e}")
    finally:
        db.close()


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
    time_val = intent_data.get("time")
    description = intent_data.get("description")
    category = intent_data.get("category")
    query_type = intent_data.get("query_type", "today")
    target_event = intent_data.get("target_event")
    new_date = intent_data.get("new_date")
    new_time = intent_data.get("new_time")
    target_calendar = intent_data.get("target_calendar")

    result = None

    try:
        # ==================== CREATE INTENTS ====================
        if intent == "EVENT" and date:
            result = await google_service.create_calendar_event(
                token_data=tokens,
                title=title,
                date=date,
                time=time_val,
                description=description,
                user_id=user_id,
                category=category
            )

            if result.get("success"):
                emoji = result.get("calendar_emoji", "📅")
                category_label = MSG.CATEGORY_WORK if result.get("category") == "work" else MSG.CATEGORY_PERSONAL
                await send_telegram_text(
                    chat_id,
                    MSG.EVENT_CREATED.format(emoji=emoji, category=category_label, title=title, link=result.get('html_link', '')),
                    token
                )

        elif intent == "TODO":
            result = await google_service.create_task(
                token_data=tokens,
                title=title,
                notes=description,
                due_date=date
            )

            if result.get("success"):
                await send_telegram_text(chat_id, MSG.TASK_CREATED.format(title=title), token)

        elif intent == "NOTE":
            try:
                async with httpx.AsyncClient() as client:
                    fusion_app_url = os.getenv("FUSION_APP_URL", "https://testapp.mujagent.cz")
                    response = await client.post(
                        f"{fusion_app_url}/api/brain/notes",
                        json={
                            "title": title,
                            "content": description,
                            "user_id": user_id
                        },
                        timeout=10.0
                    )

                    if response.status_code == 200:
                        await send_telegram_text(chat_id, MSG.NOTE_SAVED.format(title=title), token)
                    else:
                        logger.warning(f"Failed to save note: {response.status_code} - {response.text}")
                        await send_telegram_text(chat_id, MSG.NOTE_SAVED_LOCAL.format(title=title), token)
            except Exception as note_error:
                logger.error(f"Error saving note: {note_error}")
                await send_telegram_text(chat_id, MSG.NOTE_FALLBACK.format(title=title), token)

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
                    label = {
                        "today": MSG.CALENDAR_TODAY,
                        "tomorrow": MSG.CALENDAR_TOMORROW,
                        "week": MSG.CALENDAR_WEEK
                    }.get(query_type, MSG.CALENDAR_EVENTS)

                    event_list = []
                    for e in events:
                        time_str = ""
                        if "T" in e["start"]:
                            time_str = e["start"].split("T")[1][:5] + " - "
                        event_list.append(f"{e['emoji']} {time_str}**{e['title']}**")

                    msg = f"{label}:\n\n" + "\n".join(event_list)
                else:
                    msg = MSG.NO_EVENTS

                await send_telegram_text(chat_id, msg, token)

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

                    header = MSG.TASKS_HEADER.format(count=len(tasks))
                    if overdue > 0:
                        header += MSG.TASKS_OVERDUE.format(count=overdue)
                    header += "):\n\n"

                    msg = header + "\n".join(task_list)
                else:
                    msg = MSG.NO_TASKS

                await send_telegram_text(chat_id, msg, token)

        # ==================== UPDATE/DELETE INTENTS ====================
        elif intent == "UPDATE_EVENT" and target_event:
            search_result = await google_service.search_event(
                token_data=tokens,
                user_id=user_id,
                search_query=target_event
            )

            if search_result.get("success") and search_result.get("events"):
                events = search_result["events"]

                if len(events) == 1:
                    event = events[0]

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
                            msg = MSG.EVENT_MOVED_CALENDAR.format(emoji=emoji, title=event['title'], calendar=target_name)
                            await send_telegram_text(chat_id, msg, token)
                        else:
                            error_msg = move_result.get("error", "Neznámá chyba")
                            await send_telegram_text(chat_id, f"❌ {error_msg}", token, parse_mode=None)
                    else:
                        # Calculate new_date if "tomorrow" was mentioned
                        effective_new_date = new_date
                        if not effective_new_date and "zítra" in str(intent_data).lower():
                            effective_new_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

                        update_result = await google_service.update_event(
                            token_data=tokens,
                            user_id=user_id,
                            event_id=event["id"],
                            calendar_id=event["calendar_id"],
                            new_date=effective_new_date,
                            new_time=new_time
                        )

                        if update_result.get("success"):
                            msg = MSG.EVENT_UPDATED.format(title=event['title'])
                            if effective_new_date:
                                msg += MSG.EVENT_NEW_DATE.format(date=effective_new_date)
                            if new_time:
                                msg += MSG.EVENT_NEW_TIME.format(time=new_time)
                            await send_telegram_text(chat_id, msg, token)
                else:
                    event_list = "\n".join([f"• {e['title']} ({e['start'][:10]})" for e in events[:5]])
                    msg = MSG.MULTIPLE_EVENTS_FOUND.format(count=len(events), list=event_list)
                    await send_telegram_text(chat_id, msg, token, parse_mode=None)
            else:
                await send_telegram_text(
                    chat_id,
                    MSG.EVENT_NOT_FOUND.format(query=target_event),
                    token, parse_mode=None
                )

        elif intent == "DELETE_EVENT" and target_event:
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
                        msg = MSG.EVENT_DELETED.format(title=delete_result['deleted_title'])
                        await send_telegram_text(chat_id, msg, token)
                else:
                    event_list = "\n".join([f"• {e['title']} ({e['start'][:10]})" for e in events[:5]])
                    msg = MSG.MULTIPLE_EVENTS_DELETE.format(count=len(events), list=event_list)
                    await send_telegram_text(chat_id, msg, token, parse_mode=None)
            else:
                await send_telegram_text(
                    chat_id,
                    MSG.EVENT_NOT_FOUND.format(query=target_event),
                    token, parse_mode=None
                )

        elif intent == "COMPLETE_TASK" and target_event:
            # Search for the task by name in pending tasks
            tasks_result = await google_service.get_pending_tasks(token_data=tokens)

            if tasks_result.get("success"):
                tasks = tasks_result.get("tasks", [])
                from app.services.google_service import normalize_text
                search_normalized = normalize_text(target_event)
                matching = [t for t in tasks if search_normalized in normalize_text(t.get("title", ""))]

                if len(matching) == 1:
                    complete_result = await google_service.complete_task(
                        token_data=tokens,
                        task_id=matching[0]["id"]
                    )
                    if complete_result.get("success"):
                        await send_telegram_text(
                            chat_id,
                            f"✅ Úkol **{matching[0]['title']}** splněn!",
                            token
                        )
                    else:
                        await send_telegram_text(chat_id, "❌ Nepodařilo se dokončit úkol.", token, parse_mode=None)
                elif len(matching) > 1:
                    task_list = "\n".join([f"• {t['title']}" for t in matching[:5]])
                    await send_telegram_text(
                        chat_id,
                        f"🔍 Nalezeno {len(matching)} úkolů:\n{task_list}\n\nUpřesni prosím který myslíš.",
                        token, parse_mode=None
                    )
                else:
                    await send_telegram_text(
                        chat_id,
                        f"❌ Nenašel jsem úkol obsahující '{target_event}'",
                        token, parse_mode=None
                    )

        # SUMMARY - combine calendar and tasks
        elif intent == "SUMMARY":
            events_result = await google_service.get_events(
                token_data=tokens,
                user_id=user_id,
                query_type="today"
            )
            tasks_result = await google_service.get_pending_tasks(token_data=tokens)

            events = events_result.get("events", [])
            tasks = tasks_result.get("tasks", [])
            msg_parts, voice_parts = build_summary(events, tasks)

            await send_telegram_text(chat_id, "\n".join(msg_parts), token)
            await send_voice_response(chat_id, " ".join(voice_parts), token)

    except Exception as e:
        logger.error(f"Error processing with Google: {e}", exc_info=True)

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
        logger.info(f"Unauthorized access attempt from user_id: {user_id}")
        return {"ok": True}

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    user_name = message.get("from", {}).get("first_name")

    # 3. Handle Voice Message
    if "voice" in message:
        logger.info(f"Received voice message from {user_id}")
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
                logger.info(f"Transcription: {transcription}")

                intent_data = await ai_service.extract_intent(transcription)
                logger.info(f"Intent: {intent_data}")

                save_capture(str(user_id), user_name, "voice", transcription, intent_data)

                await send_telegram_text(
                    chat_id,
                    MSG.VOICE_TRANSCRIBED.format(text=transcription, intent=intent_data.get('intent', 'UNKNOWN')),
                    token, parse_mode=None
                )

                await process_with_google(str(user_id), intent_data, token, chat_id)

            finally:
                if os.path.exists(tmp_name):
                    os.remove(tmp_name)

    # 4. Handle Text Message
    elif "text" in message:
        text_content = message.get("text")
        logger.info(f"Received text message from {user_id}: {text_content}")

        # Simple command handling (bypass AI)
        if text_content.strip().lower() in ["/pulse", "/status", "/ping"]:
            await send_telegram_text(
                chat_id,
                "✅ Python Backend: Online\n🧠 AI Service: Ready\n🚀 Fusion App: Active",
                token, parse_mode=None
            )
            return {"ok": True}

        intent_data = await ai_service.extract_intent(text_content)

        # Handle CHAT intent (conversational reply, no DB save)
        if intent_data.get("intent") == "CHAT":
            response_text = intent_data.get("response_text") or "🤖 Rozumím, ale nemám odpověď."
            await send_telegram_text(chat_id, response_text, token, parse_mode=None)
            return {"ok": True}

        save_capture(str(user_id), user_name, "text", text_content, intent_data)

        await send_telegram_text(
            chat_id,
            MSG.TEXT_SAVED.format(title=intent_data.get('title', 'Poznámka')),
            token, parse_mode=None
        )

        await process_with_google(str(user_id), intent_data, token, chat_id)

    return {"ok": True}
