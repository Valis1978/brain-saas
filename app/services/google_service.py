"""
Google Workspace Integration Service
Handles OAuth 2.0 flow, Calendar API, and Tasks API
"""

import os
import json
from datetime import datetime, timedelta
from typing import Optional
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

class GoogleService:
    """Service for Google Workspace integration."""
    
    def __init__(self):
        self.client_id = os.getenv('GOOGLE_CLIENT_ID')
        self.client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
        self.redirect_uri = os.getenv('GOOGLE_REDIRECT_URI', 'https://freshbrain.mujagent.cz/api/v1/google/callback')
        
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
    
    async def create_calendar_event(
        self,
        token_data: dict,
        title: str,
        date: str,
        time: Optional[str] = None,
        description: Optional[str] = None,
        duration_minutes: int = 30
    ) -> dict:
        """Create a Google Calendar event."""
        try:
            credentials = self.get_credentials_from_tokens(token_data)
            service = build('calendar', 'v3', credentials=credentials)
            
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
            
            created_event = service.events().insert(calendarId='primary', body=event).execute()
            
            return {
                "success": True,
                "event_id": created_event.get('id'),
                "html_link": created_event.get('htmlLink'),
                "summary": created_event.get('summary')
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
