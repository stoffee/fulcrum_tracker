"""Async Google Calendar handler for Fulcrum Tracker integration."""
import logging
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import aiohttp
import jwt  # for service account JWT creation
from aiofiles import open as async_open

from ..const import (
    CALENDAR_SEARCH_TERMS,
    DEFAULT_START_DATE,
    DEFAULT_CACHE_TTL,
    ERROR_CALENDAR_AUTH,
    ERROR_CALENDAR_FETCH,
)

_LOGGER = logging.getLogger(__name__)

class AsyncGoogleCalendarHandler:
    """Async handler for Google Calendar operations."""

    def __init__(self, service_account_path: str, calendar_id: str) -> None:
        """Initialize the calendar handler."""
        self.service_account_path = service_account_path
        self.calendar_id = calendar_id
        self.session: Optional[aiohttp.ClientSession] = None
        self._credentials = None
        self._cache = {}
        self._cache_time = None
        self._token = None
        self._token_expiry = None
        _LOGGER.debug("Calendar handler initialized")

    async def _load_credentials(self) -> Dict[str, Any]:
        """Load service account credentials from file."""
        try:
            async with async_open(self.service_account_path, 'r') as f:
                return json.loads(await f.read())
        except Exception as err:
            _LOGGER.error("Failed to load credentials: %s", str(err))
            raise ValueError(ERROR_CALENDAR_AUTH)

    async def _get_access_token(self) -> str:
        """Get a valid access token."""
        now = datetime.utcnow()
        
        # Check if current token is still valid
        if self._token and self._token_expiry and self._token_expiry > now:
            return self._token

        # Load credentials if needed
        if not self._credentials:
            self._credentials = await self._load_credentials()

        # Create JWT claim
        claim = {
            "iss": self._credentials["client_email"],
            "scope": "https://www.googleapis.com/auth/calendar.readonly",
            "aud": "https://oauth2.googleapis.com/token",
            "exp": now + timedelta(hours=1),
            "iat": now,
        }

        # Sign JWT
        signed_jwt = jwt.encode(
            claim,
            self._credentials["private_key"],
            algorithm="RS256"
        )

        # Exchange JWT for access token
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": signed_jwt,
                }
            ) as response:
                if response.status != 200:
                    raise ValueError(f"Token request failed: {await response.text()}")
                data = await response.json()

        self._token = data["access_token"]
        self._token_expiry = now + timedelta(seconds=data["expires_in"] - 300)  # 5 min buffer
        return self._token

    async def _is_cache_valid(self) -> bool:
        """Check if cache is still valid."""
        if not self._cache or not self._cache_time:
            return False
        
        age = datetime.now() - self._cache_time
        return age.total_seconds() < DEFAULT_CACHE_TTL

    async def get_calendar_events(self) -> List[Dict[str, Any]]:
        """Fetch and process calendar events."""
        if await self._is_cache_valid():
            _LOGGER.debug("Returning cached calendar data")
            return self._cache

        if not self.session:
            self.session = aiohttp.ClientSession()

        try:
            training_sessions = []
            start_time = datetime.strptime(DEFAULT_START_DATE, "%Y-%m-%d").isoformat() + 'Z'
            end_time = datetime.now().isoformat() + 'Z'
            
            # Get fresh access token
            token = await self._get_access_token()
            headers = {"Authorization": f"Bearer {token}"}

            for term in CALENDAR_SEARCH_TERMS:
                _LOGGER.debug("Searching for term: %s", term)
                
                params = {
                    "calendarId": self.calendar_id,
                    "timeMin": start_time,
                    "timeMax": end_time,
                    "q": term,
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": "2500"
                }

                async with self.session.get(
                    f"https://www.googleapis.com/calendar/v3/calendars/{self.calendar_id}/events",
                    params=params,
                    headers=headers
                ) as response:
                    if response.status != 200:
                        raise ValueError(f"Calendar API request failed: {await response.text()}")
                    
                    data = await response.json()
                    events = data.get("items", [])
                    _LOGGER.debug("Found %d events for term '%s'", len(events), term)
                    
                    for event in events:
                        session = await self._process_event(event, term)
                        if session:
                            training_sessions.append(session)

            # Remove duplicates while preserving order
            unique_sessions = self._deduplicate_sessions(training_sessions)
            
            # Update cache
            self._cache = unique_sessions
            self._cache_time = datetime.now()
            
            _LOGGER.info("Found %d unique training sessions", len(unique_sessions))
            return unique_sessions

        except Exception as err:
            _LOGGER.error("Failed to fetch calendar events: %s", str(err))
            raise ValueError(ERROR_CALENDAR_FETCH)

    async def _process_event(self, event: Dict[str, Any], search_term: str) -> Optional[Dict[str, Any]]:
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
        if not self.session:
            self.session = aiohttp.ClientSession()

        try:
            now = datetime.utcnow().isoformat() + 'Z'
            future = (datetime.utcnow() + timedelta(days=30)).isoformat() + 'Z'
            token = await self._get_access_token()
            headers = {"Authorization": f"Bearer {token}"}

            for term in CALENDAR_SEARCH_TERMS:
                params = {
                    "calendarId": self.calendar_id,
                    "timeMin": now,
                    "timeMax": future,
                    "q": term,
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": "1"
                }

                async with self.session.get(
                    f"https://www.googleapis.com/calendar/v3/calendars/{self.calendar_id}/events",
                    params=params,
                    headers=headers
                ) as response:
                    if response.status != 200:
                        continue
                        
                    data = await response.json()
                    events = data.get("items", [])
                    if events:
                        return await self._process_event(events[0], term)

            return None

        except Exception as err:
            _LOGGER.error("Failed to fetch next session: %s", str(err))
            return None

    async def close(self) -> None:
        """Close the session."""
        if self.session:
            await self.session.close()
            self.session = None