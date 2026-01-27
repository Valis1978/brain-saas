"""
Google Workspace Integration Service
Handles OAuth 2.0 flow, Calendar API, and Tasks API
Supports dual calendars: Work (Práce) and Personal (Osobní)
"""

import os
import json
from datetime import datetime, timedelta
from typing import Optional, Tuple
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import httpx

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
        """Create Credentials object from stored token data."""
        return Credentials(
            token=token_data.get('access_token'),
            refresh_token=token_data.get('refresh_token'),
            token_uri='https://oauth2.googleapis.com/token',
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=token_data.get('scopes', SCOPES)
        )
    
    def detect_event_category(self, text: str) -> str:
        """
        Detect whether event is work or personal based on text content.
        Returns 'work' or 'personal'.
        """
        text_lower = text.lower()
        
        work_score = sum(1 for keyword in WORK_KEYWORDS if keyword in text_lower)
        personal_score = sum(1 for keyword in PERSONAL_KEYWORDS if keyword in text_lower)
        
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
                # All-day event
                event = {
                    'summary': title,
                    'description': description or f'Vytvořeno z Brain SaaS',
                    'start': {
                        'date': date,
                    },
                    'end': {
                        'date': date,
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
            default_tasklist = tasklists.get('items', [{}])[0].get('id', '@default')
            
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
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to create task: {str(e)}"
            }

# Singleton instance
google_service = GoogleService()
