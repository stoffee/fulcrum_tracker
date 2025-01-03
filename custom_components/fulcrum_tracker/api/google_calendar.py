"""Async Google Calendar handler for Fulcrum Tracker integration."""
import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import aiohttp
import jwt
from aiofiles import open as async_open

from ..const import (
    CALENDAR_SEARCH_TERMS,
    DEFAULT_START_DATE,
    DEFAULT_CACHE_TTL,
    ERROR_CALENDAR_AUTH,
    ERROR_CALENDAR_FETCH,
    TRAINERS,
)

_LOGGER = logging.getLogger(__name__)

"""Async Google Calendar handler for Fulcrum Tracker integration."""
class AsyncGoogleCalendarHandler:
    """Async handler for Google Calendar operations."""

    def __init__(self, service_account_path: str, default_calendar_id: str) -> None:
        self.service_account_path = service_account_path
        self.default_calendar_id = default_calendar_id
        self.session: Optional[aiohttp.ClientSession] = None
        self._credentials = None
        self._cache = {}
        self._cache_time = None
        self._token = None
        self._token_expiry = None
        self.local_tz = ZoneInfo("America/Los_Angeles")
        _LOGGER.debug("Calendar handler initialized with default calendar: %s", default_calendar_id)

    async def get_calendar_events(
        self, 
        calendar_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Fetch and process calendar events."""
        if await self._is_cache_valid() and not calendar_id:
            _LOGGER.debug("Returning cached calendar data")
            return self._cache

        calendar_id = calendar_id or self.default_calendar_id
        _LOGGER.debug("Fetching events for calendar: %s", calendar_id)

        start_time = start_date or datetime.strptime(DEFAULT_START_DATE, "%Y-%m-%d")
        end_time = end_date or datetime.now()

        start_time_str = start_time.isoformat() + 'Z'
        end_time_str = end_time.isoformat() + 'Z'
        
        if not self.session:
            self.session = aiohttp.ClientSession()

        try:
            token = await self._get_access_token()
            headers = {"Authorization": f"Bearer {token}"}
            training_sessions = []

            for term in CALENDAR_SEARCH_TERMS:
                _LOGGER.debug("Searching calendar %s for term: %s", calendar_id, term)
                
                params = {
                    "calendarId": calendar_id,
                    "timeMin": start_time_str,
                    "timeMax": end_time_str,
                    "q": term,
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": "2500"
                }

                async with self.session.get(
                    f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
                    params=params,
                    headers=headers
                ) as response:
                    if response.status != 200:
                        _LOGGER.error("Calendar API request failed for %s: %s", 
                                    calendar_id, await response.text())
                        continue
                    
                    data = await response.json()
                    events = data.get("items", [])
                    _LOGGER.debug("Found %d events for term '%s' in calendar %s", 
                               len(events), term, calendar_id)
                    
                    for event in events:
                        session = await self._process_event(event, term)
                        if session:
                            training_sessions.append(session)

            unique_sessions = self._deduplicate_sessions(training_sessions)
            
            # Only cache default calendar data
            if not calendar_id or calendar_id == self.default_calendar_id:
                self._cache = unique_sessions
                self._cache_time = datetime.now()
            
            return unique_sessions

        except Exception as err:
            _LOGGER.error("Failed to fetch calendar events for %s: %s", 
                       calendar_id, str(err), exc_info=True)
            raise ValueError(ERROR_CALENDAR_FETCH)

    async def _load_credentials(self) -> Dict[str, Any]:
        try:
            async with async_open(self.service_account_path, 'r') as f:
                return json.loads(await f.read())
        except Exception as err:
            _LOGGER.error("Failed to load credentials: %s", str(err))
            raise ValueError(ERROR_CALENDAR_AUTH)

    async def _get_access_token(self) -> str:
        now = datetime.utcnow()
        
        if self._token and self._token_expiry and self._token_expiry > now:
            return self._token

        if not self._credentials:
            self._credentials = await self._load_credentials()

        claim = {
            "iss": self._credentials["client_email"],
            "scope": "https://www.googleapis.com/auth/calendar.readonly",
            "aud": "https://oauth2.googleapis.com/token",
            "exp": now + timedelta(hours=1),
            "iat": now,
        }

        signed_jwt = jwt.encode(
            claim,
            self._credentials["private_key"],
            algorithm="RS256"
        )

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
        self._token_expiry = now + timedelta(seconds=data["expires_in"] - 300)
        return self._token

    async def _process_event(self, event: Dict[str, Any], search_term: str) -> Optional[Dict[str, Any]]:
        """Process a single calendar event."""
        try:
            _LOGGER.debug("Processing event: %s", event.get('summary', 'Unknown Event'))
            
            start = None
            if 'start' in event:
                start = event['start'].get('dateTime') or event['start'].get('date')
            
            if not start:
                _LOGGER.debug("No start time found in event")
                return None

            try:
                start_dt = self._normalize_timezone(start)
            except (ValueError, TypeError) as e:
                _LOGGER.debug("Error normalizing timezone: %s", str(e))
                return None

            instructor = "Unknown"
            if event.get('description'):
                description = event['description'].lower()
                _LOGGER.debug("Processing event description: %s", description[:200])  # First 200 chars for brevity
                
                # Try direct trainer name match first
                for trainer in TRAINERS:
                    if trainer.lower() in description:
                        instructor = trainer
                        _LOGGER.debug("Found trainer by direct match: %s", trainer)
                        break
                
                # If no match, try instructor patterns
                if instructor == "Unknown":
                    instructor_patterns = ['instructor:', 'instructor', 'trainer:', 'trainer']
                    for pattern in instructor_patterns:
                        if pattern in description:
                            found_text = description.split(pattern)[1].split('\n')[0].strip()
                            first_name = found_text.split()[0].capitalize()
                            _LOGGER.debug("Found potential instructor name: %s", first_name)
                            if first_name in TRAINERS:
                                instructor = first_name
                                _LOGGER.debug("Validated instructor name: %s", instructor)
                                break

            _LOGGER.debug("Final instructor determination: %s", instructor)

            processed_event = {
                'date': start_dt.strftime('%Y-%m-%d'),
                'time': start_dt.strftime('%H:%M'),
                'subject': event.get('summary', 'Unknown Event'),
                'instructor': instructor,
                'search_term': search_term,
                'description': event.get('description', ''),
                'location': event.get('location', ''),
                'event_id': event.get('id', '')
            }
            _LOGGER.debug("Processed event data: %s", processed_event)
            return processed_event

        except Exception as err:
            _LOGGER.error("Error processing event %s: %s", event.get('summary', 'Unknown'), str(err))
            return None

    def _normalize_timezone(self, event_time: str) -> datetime:
        """Normalize event time to local timezone."""
        dt = datetime.fromisoformat(event_time.replace('Z', '+00:00'))
        return dt.astimezone(self.local_tz)

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
                        _LOGGER.error("Calendar API request failed: %s", await response.text())
                        continue
                    
                    data = await response.json()
                    events = data.get("items", [])
                    _LOGGER.debug("Found %d events for term '%s'", len(events), term)
                    
                    for event in events:
                        session = await self._process_event(event, term)
                        if session:
                            training_sessions.append(session)

            unique_sessions = self._deduplicate_sessions(training_sessions)
            
            self._cache = unique_sessions
            self._cache_time = datetime.now()
            
            _LOGGER.debug("Found %d unique training sessions with instructors: %s", 
                       len(unique_sessions), 
                       {s['instructor'] for s in unique_sessions})
            return unique_sessions

        except Exception as err:
            _LOGGER.error("Failed to fetch calendar events: %s", str(err))
            raise ValueError(ERROR_CALENDAR_FETCH)

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
                        session = await self._process_event(events[0], term)
                        if session:
                            _LOGGER.debug("Next session found: %s with %s", 
                                      session.get('date'), session.get('instructor'))
                            return session

            return None

        except Exception as err:
            _LOGGER.error("Failed to fetch next session: %s", str(err))
            return None

    async def close(self) -> None:
        """Close the session."""
        if self.session:
            await self.session.close()
            self.session = None