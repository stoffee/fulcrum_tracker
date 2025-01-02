"""Async Google Calendar handler for Fulcrum Tracker integration."""
import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

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
        self.local_tz = ZoneInfo("America/Los_Angeles")
        _LOGGER.debug("Calendar handler initialized")

    def is_travel_event(self, event: dict) -> bool:
        """Check if an event is travel-related."""
        # Get event details
        summary = event.get('summary', '').lower()
        location = event.get('location', '').lower()
        description = event.get('description', '').lower()

        # Check for flight markers
        flight_markers = [
            "flight to", "as ", "dl ", "koa", "pdx", "sea", "lax", "sfo", "bos", 
            "alaska airlines", "delta", "united", "american airlines",
            "airport", "airways", "airlines"
        ]
        for marker in flight_markers:
            if marker in summary.lower() or marker in location.lower():
                return True

        # Check for stay/hotel markers
        stay_markers = [
            "stay at", "hotel", "resort", "airbnb", "vacation", "hampton inn",
            "residence inn", "marriott", "hilton", "hyatt"
        ]
        for marker in stay_markers:
            if marker in summary.lower() or marker in location.lower():
                return True

        # Check for specific travel locations
        travel_locations = [
            "airport", "airways", "airlines", "terminal", "flight", 
            "las vegas", "seattle", "boston", "hawaii", "austin", "dallas"
        ]
        for loc in travel_locations:
            if loc in location.lower() or loc in description.lower():
                return True

        return False

    def filter_travel_dates(self, events: list) -> List[Dict[str, Any]]:
        """Filter events to identify travel dates and training gaps."""
        travel_periods = []
        current_period = None

        for event in sorted(events, key=lambda x: x.get('date', '')):  # Changed from x['start']
            if self.is_travel_event(event):
                # Get dates safely with fallbacks
                start_date = event.get('date', '')  # Changed from event['start']
                end_date = event.get('date', '')    # Default to start date if no end date
                
                if not start_date:  # Skip events without dates
                    continue

                if current_period is None:
                    current_period = {
                        'start': start_date,
                        'end': end_date,
                        'type': 'travel',
                        'events': [event]
                    }
                elif start_date <= current_period['end']:
                    # Extend current period if dates overlap
                    current_period['end'] = max(current_period['end'], end_date)
                    current_period['events'].append(event)
                else:
                    # Start new period
                    travel_periods.append(current_period)
                    current_period = {
                        'start': start_date,
                        'end': end_date,
                        'type': 'travel',
                        'events': [event]
                    }

        # Add final period if exists
        if current_period:
            travel_periods.append(current_period)

        return travel_periods

    def get_non_training_dates(self, events: list) -> List[Dict[str, Any]]:
        """
        Get dates when training should be excluded due to travel or other commitments.
        Returns a list of non-training periods.
        """
        exclusion_periods = []
        
        # First get travel periods
        travel_periods = self.filter_travel_dates(events)
        exclusion_periods.extend(travel_periods)
        
        # Add any additional non-training periods (holidays, etc)
        holidays = [
            # Add specific dates from your holiday list
            '2024-01-01',  # New Year's Day
            '2024-11-28',  # Thanksgiving
            '2024-12-25',  # Christmas
        ]
        
        for holiday in holidays:
            exclusion_periods.append({
                'start': holiday,
                'end': holiday,
                'type': 'holiday'
            })
        
        return sorted(exclusion_periods, key=lambda x: x['start'])

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

    def _normalize_timezone(self, event_time: str) -> datetime:
        """Normalize event time to local timezone."""
        # Parse the timestamp
        dt = datetime.fromisoformat(event_time.replace('Z', '+00:00'))
        
        # Convert to local timezone
        return dt.astimezone(self.local_tz)

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

            # Get non-training dates
            exclusion_periods = self.get_non_training_dates(training_sessions)
            
            # Remove duplicates while preserving order
            unique_sessions = self._deduplicate_sessions(training_sessions)
            
            # Filter out sessions during travel/exclusion periods
            filtered_sessions = []
            for session in unique_sessions:
                session_date = session['date']
                exclude = False
                for period in exclusion_periods:
                    if period['start'] <= session_date <= period['end']:
                        _LOGGER.debug(
                            "Excluding session on %s due to %s period", 
                            session_date, 
                            period['type']
                        )
                        exclude = True
                        break
                if not exclude:
                    filtered_sessions.append(session)
            
            # Update cache
            self._cache = filtered_sessions
            self._cache_time = datetime.now()
            
            _LOGGER.info("Found %d unique training sessions", len(filtered_sessions))
            return filtered_sessions

        except Exception as err:
            _LOGGER.error("Failed to fetch calendar events: %s", str(err))
            raise ValueError(ERROR_CALENDAR_FETCH)

    async def _process_event(self, event: Dict[str, Any], search_term: str) -> Optional[Dict[str, Any]]:
        """Process a single calendar event with better error handling."""
        try:
            # Get start time safely
            start = None
            if 'start' in event:
                start = event['start'].get('dateTime') or event['start'].get('date')
            
            if not start:
                _LOGGER.debug("Skipping event without start time: %s", event.get('summary', 'Unknown'))
                return None

            # Normalize timezone
            try:
                start_dt = self._normalize_timezone(start)
            except (ValueError, TypeError) as e:
                _LOGGER.debug("Failed to normalize timezone for event %s: %s", 
                            event.get('summary', 'Unknown'), str(e))
                return None

            # Extract instructor if available
            instructor = "Unknown"
            if event.get('description'):
                description = event['description']
                if 'Instructor:' in description:
                    instructor = description.split('Instructor:')[1].split('\n')[0].strip()

            return {
                'date': start_dt.strftime('%Y-%m-%d'),
                'time': start_dt.strftime('%H:%M'),
                'subject': event.get('summary', 'Unknown Event'),
                'instructor': instructor,
                'search_term': search_term,
                'description': event.get('description', ''),
                'location': event.get('location', ''),
                'event_id': event.get('id', '')
            }

        except Exception as err:
            _LOGGER.warning("Error processing event %s: %s", 
                        event.get('summary', 'Unknown'), str(err))
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
                        session = await self._process_event(events[0], term)
                        if session and not self.is_travel_event(events[0]):
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