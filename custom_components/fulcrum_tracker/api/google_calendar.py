"""Google Calendar handler for Fulcrum Tracker integration."""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ..const import (
    CALENDAR_SEARCH_TERMS,
    DEFAULT_START_DATE,
    DEFAULT_CACHE_TTL,
    ERROR_CALENDAR_AUTH,
    ERROR_CALENDAR_FETCH,
)

_LOGGER = logging.getLogger(__name__)

class GoogleCalendarHandler:
    """Handle Google Calendar operations."""

    SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

    def __init__(self, service_account_path: str, calendar_id: str) -> None:
        """Initialize the calendar handler."""
        self.service_account_path = service_account_path
        self.calendar_id = calendar_id
        self.service = None
        self._cache = {}
        self._cache_time = None
        _LOGGER.debug("Calendar handler initialized")

    def authenticate(self) -> bool:
        """Authenticate with Google Calendar API."""
        try:
            credentials = service_account.Credentials.from_service_account_file(
                self.service_account_path, scopes=self.SCOPES
            )
            
            self.service = build('calendar', 'v3', credentials=credentials)
            _LOGGER.debug("Successfully authenticated with Google Calendar")
            return True
            
        except Exception as err:
            _LOGGER.error("Failed to authenticate: %s", str(err))
            raise ValueError(ERROR_CALENDAR_AUTH)

    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid."""
        if not self._cache or not self._cache_time:
            return False
        
        age = datetime.now() - self._cache_time
        return age.total_seconds() < DEFAULT_CACHE_TTL

    async def get_calendar_events(self) -> List[Dict[str, Any]]:
        """Fetch and process calendar events."""
        # Check cache first
        if self._is_cache_valid():
            _LOGGER.debug("Returning cached calendar data")
            return self._cache

        if not self.service:
            self.authenticate()

        try:
            training_sessions = []
            start_time = datetime.strptime(DEFAULT_START_DATE, "%Y-%m-%d").isoformat() + 'Z'
            end_time = datetime.now().isoformat() + 'Z'

            for term in CALENDAR_SEARCH_TERMS:
                _LOGGER.debug("Searching for term: %s", term)
                
                events_result = self.service.events().list(
                    calendarId=self.calendar_id,
                    timeMin=start_time,
                    timeMax=end_time,
                    q=term,
                    singleEvents=True,
                    orderBy='startTime',
                    maxResults=2500
                ).execute()
                
                events = events_result.get('items', [])
                _LOGGER.debug("Found %d events for term '%s'", len(events), term)
                
                for event in events:
                    session = self._process_event(event, term)
                    if session:
                        training_sessions.append(session)

            # Remove duplicates while preserving order
            unique_sessions = self._deduplicate_sessions(training_sessions)
            
            # Update cache
            self._cache = unique_sessions
            self._cache_time = datetime.now()
            
            _LOGGER.info("Found %d unique training sessions", len(unique_sessions))
            return unique_sessions

        except HttpError as err:
            _LOGGER.error("Failed to fetch calendar events: %s", str(err))
            raise ValueError(ERROR_CALENDAR_FETCH)

    def _process_event(self, event: Dict[str, Any], search_term: str) -> Optional[Dict[str, Any]]:
        """Process a single calendar event."""
        try:
            start = event['start'].get('dateTime', event['start'].get('date'))
            if not start:
                return None

            # Convert to datetime with timezone handling
            start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            
            # Extract instructor if available
            instructor = "Unknown"
            if 'description' in event:
                description = event['description']
                if 'Instructor:' in description:
                    instructor = description.split('Instructor:')[1].split('\n')[0].strip()

            return {
                'date': start_dt.strftime('%Y-%m-%d'),
                'time': start_dt.strftime('%H:%M'),
                'subject': event['summary'],
                'instructor': instructor,
                'search_term': search_term,
                'description': event.get('description', ''),
                'location': event.get('location', ''),
                'event_id': event['id']
            }

        except (KeyError, ValueError) as err:
            _LOGGER.warning("Error processing event: %s", str(err))
            return None

    @staticmethod
    def _deduplicate_sessions(sessions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate sessions while preserving order."""
        unique_sessions = []
        seen = set()
        
        for session in sorted(sessions, key=lambda x: (x['date'], x['time'])):
            key = f"{session['date']}_{session['time']}"
            if key not in seen:
                unique_sessions.append(session)
                seen.add(key)
                
        return unique_sessions

    async def get_next_session(self) -> Optional[Dict[str, Any]]:
        """Get the next upcoming training session."""
        if not self.service:
            self.authenticate()

        try:
            now = datetime.utcnow().isoformat() + 'Z'
            future = (datetime.utcnow() + timedelta(days=30)).isoformat() + 'Z'

            for term in CALENDAR_SEARCH_TERMS:
                events_result = self.service.events().list(
                    calendarId=self.calendar_id,
                    timeMin=now,
                    timeMax=future,
                    q=term,
                    singleEvents=True,
                    orderBy='startTime',
                    maxResults=1
                ).execute()
                
                events = events_result.get('items', [])
                if events:
                    return self._process_event(events[0], term)

            return None

        except HttpError as err:
            _LOGGER.error("Failed to fetch next session: %s", str(err))
            return None