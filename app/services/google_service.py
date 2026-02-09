"""
Google Workspace Integration Service
Handles OAuth 2.0 flow, Calendar API, and Tasks API
Supports dual calendars: Work (Práce) and Personal (Osobní)
"""

import os
import json
import unicodedata
from datetime import datetime, timedelta
from typing import Optional, Tuple
from zoneinfo import ZoneInfo
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import httpx

PRAGUE_TZ = ZoneInfo("Europe/Prague")


def normalize_text(text: str) -> str:
    """Remove diacritics and convert to lowercase for fuzzy matching."""
    # Normalize to NFD (decomposed form), remove combining marks, then lowercase
    normalized = unicodedata.normalize('NFD', text)
    without_diacritics = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
    return without_diacritics.lower()


# Google OAuth Scopes
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/tasks',
]

# Calendar configuration
CALENDAR_NAMES = {
    "work": "🧠 Vlastikův druhý mozek - Práce",
    "personal": "🏠 Vlastikův druhý mozek - Osobní"
}

# Keywords for detecting event type (work vs personal)
WORK_KEYWORDS = [
    "schůzka", "meeting", "klient", "projekt", "práce", "deadline", 
    "prezentace", "call", "conference", "office", "firma", "business",
    "report", "team", "sprint", "review", "standup", "sync",
    "email", "mail", "úkol", "task", "budget", "smlouva", "contract"
]

PERSONAL_KEYWORDS = [
    "rodina", "manželka", "děti", "narozeniny", "výročí", "doktor",
    "lékař", "nákup", "domácnost", "večeře", "oběd", "víkend",
    "dovolená", "sport", "fitness", "kamarád", "přátelé", "party",
    "oslava", "pes", "kočka", "domov", "byt", "dům", "auto",
    "hobby", "volno", "relax", "film", "koncert", "divadlo"
]


class GoogleService:
    """Service for Google Workspace integration with dual calendar support."""
    
    def __init__(self):
        self.client_id = os.getenv('GOOGLE_CLIENT_ID')
        self.client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
        self.redirect_uri = os.getenv('GOOGLE_REDIRECT_URI', 'https://freshbrain.mujagent.cz/api/v1/google/callback')
        self._calendar_ids_cache = {}  # Cache calendar IDs per user
        
    def get_authorization_url(self, user_id: str) -> str:
        """Generate OAuth authorization URL for a user."""
        if not self.client_id or not self.client_secret:
            raise ValueError("Google OAuth credentials not configured")
            
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [self.redirect_uri]
                }
            },
            scopes=SCOPES,
            redirect_uri=self.redirect_uri
        )
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent',
            state=user_id  # Pass user_id in state for callback
        )
        
        return authorization_url
    
    def exchange_code_for_tokens(self, code: str) -> dict:
        """Exchange authorization code for tokens."""
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [self.redirect_uri]
                }
            },
            scopes=SCOPES,
            redirect_uri=self.redirect_uri
        )
        
        flow.fetch_token(code=code)
        credentials = flow.credentials
        
        return {
            "access_token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "expires_at": credentials.expiry.isoformat() if credentials.expiry else None,
            "token_uri": credentials.token_uri,
            "scopes": list(credentials.scopes) if credentials.scopes else SCOPES
        }
    
    def get_credentials_from_tokens(self, token_data: dict) -> Credentials:
        """Create Credentials object from stored token data with proper expiry."""
        expiry = None
        expires_at = token_data.get('expires_at')
        if expires_at:
            try:
                expiry = datetime.fromisoformat(expires_at.replace('Z', '+00:00')).replace(tzinfo=None)
            except (ValueError, AttributeError):
                pass

        return Credentials(
            token=token_data.get('access_token'),
            refresh_token=token_data.get('refresh_token'),
            token_uri='https://oauth2.googleapis.com/token',
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=token_data.get('scopes', SCOPES),
            expiry=expiry
        )
    
    def detect_event_category(self, text: str) -> str:
        """
        Detect whether event is work or personal based on text content.
        Uses diacritics-free matching so "schuzka" matches "schůzka".
        Returns 'work' or 'personal'.
        """
        text_normalized = normalize_text(text)

        work_score = sum(1 for keyword in WORK_KEYWORDS if normalize_text(keyword) in text_normalized)
        personal_score = sum(1 for keyword in PERSONAL_KEYWORDS if normalize_text(keyword) in text_normalized)

        # Default to work if unclear (most calendar events are work-related)
        if personal_score > work_score:
            return "personal"
        return "work"
    
    def get_or_create_calendars(self, token_data: dict, user_id: str) -> dict:
        """
        Get or create the Brain SaaS calendars for a user.
        Returns dict with 'work' and 'personal' calendar IDs.
        """
        # Check cache first
        if user_id in self._calendar_ids_cache:
            return self._calendar_ids_cache[user_id]
        
        try:
            credentials = self.get_credentials_from_tokens(token_data)
            service = build('calendar', 'v3', credentials=credentials)
            
            # Get list of existing calendars
            calendar_list = service.calendarList().list().execute()
            existing_calendars = {cal.get('summary'): cal.get('id') 
                                  for cal in calendar_list.get('items', [])}
            
            calendar_ids = {}
            
            for cal_type, cal_name in CALENDAR_NAMES.items():
                if cal_name in existing_calendars:
                    # Calendar exists, use it
                    calendar_ids[cal_type] = existing_calendars[cal_name]
                    print(f"Found existing calendar: {cal_name}")
                else:
                    # Create new calendar
                    new_calendar = {
                        'summary': cal_name,
                        'description': f'Brain SaaS - {"Pracovní" if cal_type == "work" else "Osobní"} kalendář',
                        'timeZone': 'Europe/Prague'
                    }
                    created = service.calendars().insert(body=new_calendar).execute()
                    calendar_ids[cal_type] = created.get('id')
                    print(f"Created new calendar: {cal_name} -> {created.get('id')}")
            
            # Cache the calendar IDs
            self._calendar_ids_cache[user_id] = calendar_ids
            return calendar_ids
            
        except HttpError as e:
            print(f"Error managing calendars: {e}")
            # Fallback to primary calendar
            return {"work": "primary", "personal": "primary"}
        except Exception as e:
            print(f"Error: {e}")
            return {"work": "primary", "personal": "primary"}

    async def create_calendar_event(
        self,
        token_data: dict,
        title: str,
        date: str,
        time: Optional[str] = None,
        description: Optional[str] = None,
        duration_minutes: int = 30,
        user_id: Optional[str] = None,
        category: Optional[str] = None  # 'work', 'personal', or None for auto-detect
    ) -> dict:
        """
        Create a Google Calendar event in the appropriate calendar.
        Auto-detects work vs personal if category not specified.
        """
        try:
            credentials = self.get_credentials_from_tokens(token_data)
            service = build('calendar', 'v3', credentials=credentials)
            
            # Determine which calendar to use
            if user_id:
                calendars = self.get_or_create_calendars(token_data, user_id)
                # Auto-detect category if not specified
                if not category:
                    # Combine title and description for better detection
                    detection_text = f"{title} {description or ''}"
                    category = self.detect_event_category(detection_text)
                calendar_id = calendars.get(category, "primary")
                calendar_emoji = "🧠" if category == "work" else "🏠"
            else:
                calendar_id = "primary"
                category = "work"
                calendar_emoji = "📅"
            
            # Parse date and time
            event_date = datetime.strptime(date, '%Y-%m-%d')
            
            if time:
                # Event with specific time
                hour, minute = map(int, time.split(':'))
                start_datetime = event_date.replace(hour=hour, minute=minute)
                end_datetime = start_datetime + timedelta(minutes=duration_minutes)
                
                event = {
                    'summary': title,
                    'description': description or f'Vytvořeno z Brain SaaS',
                    'start': {
                        'dateTime': start_datetime.isoformat(),
                        'timeZone': 'Europe/Prague',
                    },
                    'end': {
                        'dateTime': end_datetime.isoformat(),
                        'timeZone': 'Europe/Prague',
                    },
                }
            else:
                # All-day event - Google API uses exclusive end date
                end_date = (event_date + timedelta(days=1)).strftime('%Y-%m-%d')
                event = {
                    'summary': title,
                    'description': description or 'Vytvořeno z Brain SaaS',
                    'start': {
                        'date': date,
                    },
                    'end': {
                        'date': end_date,
                    },
                }
            
            created_event = service.events().insert(calendarId=calendar_id, body=event).execute()
            
            return {
                "success": True,
                "event_id": created_event.get('id'),
                "html_link": created_event.get('htmlLink'),
                "summary": created_event.get('summary'),
                "category": category,
                "calendar_emoji": calendar_emoji,
                "calendar_name": CALENDAR_NAMES.get(category, "Primary")
            }
            
        except HttpError as e:
            return {
                "success": False,
                "error": f"Google Calendar API error: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to create calendar event: {str(e)}"
            }
    
    async def create_task(
        self,
        token_data: dict,
        title: str,
        notes: Optional[str] = None,
        due_date: Optional[str] = None
    ) -> dict:
        """Create a Google Task."""
        try:
            credentials = self.get_credentials_from_tokens(token_data)
            service = build('tasks', 'v1', credentials=credentials)
            
            task = {
                'title': title,
            }
            
            if notes:
                task['notes'] = notes
                
            if due_date:
                # Google Tasks uses RFC 3339 format
                task['due'] = f"{due_date}T00:00:00.000Z"
            
            # Get default task list
            tasklists = service.tasklists().list().execute()
            items = tasklists.get('items', [])
            default_tasklist = items[0].get('id', '@default') if items else '@default'

            created_task = service.tasks().insert(tasklist=default_tasklist, body=task).execute()
            
            return {
                "success": True,
                "task_id": created_task.get('id'),
                "title": created_task.get('title'),
                "status": created_task.get('status')
            }
            
        except HttpError as e:
            return {
                "success": False,
                "error": f"Google Tasks API error: {str(e)}"
            }

    # ==================== QUERY METHODS ====================
    
    async def get_events(
        self,
        token_data: dict,
        user_id: str,
        query_type: str = "today",  # today, tomorrow, week
        specific_date: Optional[str] = None
    ) -> dict:
        """Get calendar events for a specified time range."""
        try:
            credentials = self.get_credentials_from_tokens(token_data)
            service = build('calendar', 'v3', credentials=credentials)
            
            # Get calendar IDs
            calendars = self.get_or_create_calendars(token_data, user_id)
            
            # Calculate date range using proper timezone
            now = datetime.now(PRAGUE_TZ)
            if query_type == "today":
                start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                end = now.replace(hour=23, minute=59, second=59)
            elif query_type == "tomorrow":
                tomorrow = now + timedelta(days=1)
                start = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
                end = tomorrow.replace(hour=23, minute=59, second=59)
            elif query_type == "week":
                start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                end = start + timedelta(days=7)
            elif query_type == "specific" and specific_date:
                start = datetime.strptime(specific_date, '%Y-%m-%d').replace(tzinfo=PRAGUE_TZ)
                end = start.replace(hour=23, minute=59, second=59)
            else:
                start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                end = now.replace(hour=23, minute=59, second=59)

            all_events = []

            for cal_type, cal_id in calendars.items():
                events_result = service.events().list(
                    calendarId=cal_id,
                    timeMin=start.isoformat(),
                    timeMax=end.isoformat(),
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()
                
                for event in events_result.get('items', []):
                    start_dt = event.get('start', {}).get('dateTime', event.get('start', {}).get('date', ''))
                    all_events.append({
                        'id': event.get('id'),
                        'title': event.get('summary', 'Bez názvu'),
                        'start': start_dt,
                        'calendar': cal_type,
                        'emoji': '🧠' if cal_type == 'work' else '🏠'
                    })
            
            # Sort by start time
            all_events.sort(key=lambda x: x['start'])
            
            return {
                "success": True,
                "events": all_events,
                "count": len(all_events),
                "query_type": query_type
            }
            
        except Exception as e:
            return {"success": False, "error": str(e), "events": []}
    
    async def get_pending_tasks(self, token_data: dict) -> dict:
        """Get all pending (uncompleted) tasks, optionally filtering overdue."""
        try:
            credentials = self.get_credentials_from_tokens(token_data)
            service = build('tasks', 'v1', credentials=credentials)
            
            # Get default task list
            tasklists = service.tasklists().list().execute()
            items = tasklists.get('items', [])
            default_tasklist = items[0].get('id', '@default') if items else '@default'

            # Get all tasks
            tasks_result = service.tasks().list(
                tasklist=default_tasklist,
                showCompleted=False
            ).execute()
            
            tasks = []
            now = datetime.now()
            
            for task in tasks_result.get('items', []):
                due = task.get('due')
                is_overdue = False
                due_formatted = None
                
                if due:
                    due_date = datetime.fromisoformat(due.replace('Z', '+00:00'))
                    is_overdue = due_date.date() < now.date()
                    due_formatted = due_date.strftime('%d.%m.%Y')
                
                tasks.append({
                    'id': task.get('id'),
                    'title': task.get('title', 'Bez názvu'),
                    'due': due_formatted,
                    'is_overdue': is_overdue,
                    'notes': task.get('notes')
                })
            
            # Overdue tasks first
            tasks.sort(key=lambda x: (not x['is_overdue'], x.get('due') or '9999'))
            
            overdue_count = sum(1 for t in tasks if t['is_overdue'])
            
            return {
                "success": True,
                "tasks": tasks,
                "count": len(tasks),
                "overdue_count": overdue_count
            }
            
        except Exception as e:
            return {"success": False, "error": str(e), "tasks": []}
    
    # ==================== SEARCH METHODS ====================
    
    async def search_event(
        self,
        token_data: dict,
        user_id: str,
        search_query: str
    ) -> dict:
        """Search for an event by name/query."""
        try:
            credentials = self.get_credentials_from_tokens(token_data)
            service = build('calendar', 'v3', credentials=credentials)
            
            calendars = self.get_or_create_calendars(token_data, user_id)
            
            # Search in upcoming 30 days
            now = datetime.now(PRAGUE_TZ)
            end = now + timedelta(days=30)

            matching_events = []
            search_normalized = normalize_text(search_query)

            for cal_type, cal_id in calendars.items():
                events_result = service.events().list(
                    calendarId=cal_id,
                    timeMin=now.isoformat(),
                    timeMax=end.isoformat(),
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()
                
                for event in events_result.get('items', []):
                    summary = event.get('summary', '')
                    summary_normalized = normalize_text(summary)
                    # Fuzzy match: "janik" matches "Janík", "schuzka" matches "schůzka"
                    if search_normalized in summary_normalized:
                        start_dt = event.get('start', {}).get('dateTime', event.get('start', {}).get('date', ''))
                        matching_events.append({
                            'id': event.get('id'),
                            'title': event.get('summary'),
                            'start': start_dt,
                            'calendar_id': cal_id,
                            'calendar_type': cal_type
                        })
            
            return {
                "success": True,
                "events": matching_events,
                "count": len(matching_events)
            }
            
        except Exception as e:
            return {"success": False, "error": str(e), "events": []}
    
    # ==================== UPDATE/DELETE METHODS ====================
    
    async def update_event(
        self,
        token_data: dict,
        user_id: str,
        event_id: str,
        calendar_id: str,
        new_date: Optional[str] = None,
        new_time: Optional[str] = None
    ) -> dict:
        """Update an existing calendar event."""
        try:
            credentials = self.get_credentials_from_tokens(token_data)
            service = build('calendar', 'v3', credentials=credentials)
            
            # Get existing event
            event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
            
            # Get current start
            current_start = event.get('start', {})
            is_all_day = 'date' in current_start
            
            if is_all_day:
                current_date = current_start.get('date')
                # Update date
                if new_date:
                    event['start']['date'] = new_date
                    event['end']['date'] = new_date
            else:
                current_dt = datetime.fromisoformat(current_start.get('dateTime').replace('Z', '+00:00'))
                
                if new_date:
                    new_dt = datetime.strptime(new_date, '%Y-%m-%d')
                    current_dt = current_dt.replace(year=new_dt.year, month=new_dt.month, day=new_dt.day)
                
                if new_time:
                    hour, minute = map(int, new_time.split(':'))
                    current_dt = current_dt.replace(hour=hour, minute=minute)
                
                # Update start and end
                duration = datetime.fromisoformat(event['end']['dateTime'].replace('Z', '+00:00')) - \
                          datetime.fromisoformat(event['start']['dateTime'].replace('Z', '+00:00'))
                
                event['start']['dateTime'] = current_dt.isoformat()
                event['end']['dateTime'] = (current_dt + duration).isoformat()
            
            updated_event = service.events().update(
                calendarId=calendar_id,
                eventId=event_id,
                body=event
            ).execute()
            
            return {
                "success": True,
                "event_id": updated_event.get('id'),
                "title": updated_event.get('summary'),
                "html_link": updated_event.get('htmlLink')
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def delete_event(
        self,
        token_data: dict,
        event_id: str,
        calendar_id: str
    ) -> dict:
        """Delete a calendar event."""
        try:
            credentials = self.get_credentials_from_tokens(token_data)
            service = build('calendar', 'v3', credentials=credentials)
            
            # Get event info before deleting
            event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
            title = event.get('summary', 'Událost')
            start = event.get('start', {}).get('dateTime', event.get('start', {}).get('date', ''))
            
            service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
            
            return {
                "success": True,
                "deleted_title": title,
                "deleted_start": start
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def complete_task(
        self,
        token_data: dict,
        task_id: str
    ) -> dict:
        """Mark a task as completed."""
        try:
            credentials = self.get_credentials_from_tokens(token_data)
            service = build('tasks', 'v1', credentials=credentials)
            
            # Get default task list
            tasklists = service.tasklists().list().execute()
            items = tasklists.get('items', [])
            default_tasklist = items[0].get('id', '@default') if items else '@default'

            # Update task status
            task = service.tasks().get(tasklist=default_tasklist, task=task_id).execute()
            task['status'] = 'completed'
            
            updated_task = service.tasks().update(
                tasklist=default_tasklist,
                task=task_id,
                body=task
            ).execute()
            
            return {
                "success": True,
                "task_id": updated_task.get('id'),
                "title": updated_task.get('title'),
                "status": "completed"
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def move_event_to_calendar(
        self,
        token_data: dict,
        user_id: str,
        event_id: str,
        source_calendar_id: str,
        target_calendar_type: str  # 'work' or 'personal'
    ) -> dict:
        """
        Move an event from one calendar to another (e.g., from Personal to Work).
        This creates a copy in the target calendar and deletes from source.
        """
        try:
            credentials = self.get_credentials_from_tokens(token_data)
            service = build('calendar', 'v3', credentials=credentials)
            
            # Get calendar IDs
            calendar_ids = self.get_or_create_calendars(token_data, user_id)
            target_calendar_id = calendar_ids.get(target_calendar_type)
            
            if not target_calendar_id:
                return {"success": False, "error": f"Kalendář '{target_calendar_type}' nenalezen"}
            
            # Check if already in target calendar
            if source_calendar_id == target_calendar_id:
                return {
                    "success": False, 
                    "error": f"Událost už je v kalendáři {'Práce' if target_calendar_type == 'work' else 'Osobní'}"
                }
            
            # Get the event from source calendar
            event = service.events().get(calendarId=source_calendar_id, eventId=event_id).execute()
            title = event.get('summary', 'Událost')
            
            # Remove ID and other metadata that shouldn't be copied
            event.pop('id', None)
            event.pop('iCalUID', None)
            event.pop('etag', None)
            event.pop('htmlLink', None)
            event.pop('created', None)
            event.pop('updated', None)
            event.pop('creator', None)
            event.pop('organizer', None)
            
            # Create event in target calendar
            new_event = service.events().insert(calendarId=target_calendar_id, body=event).execute()
            
            # Delete from source calendar
            service.events().delete(calendarId=source_calendar_id, eventId=event_id).execute()
            
            target_name = CALENDAR_NAMES.get(target_calendar_type, target_calendar_type)
            
            return {
                "success": True,
                "event_id": new_event.get('id'),
                "title": title,
                "target_calendar": target_calendar_type,
                "target_calendar_name": target_name,
                "html_link": new_event.get('htmlLink')
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}

# Singleton instance
google_service = GoogleService()

