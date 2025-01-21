"""Async Google Calendar handler for Fulcrum Tracker integration."""
import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
from urllib.parse import quote

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
    TRAINER_NAME_MAPPINGS,
)

_LOGGER = logging.getLogger(__name__)

class AsyncGoogleCalendarHandler:
    """Async handler for Google Calendar operations."""

    def __init__(self, service_account_path: str, default_calendar_id: str) -> None:
        """Initialize the calendar handler."""
        self.service_account_path = service_account_path
        self.default_calendar_id = default_calendar_id
        self.calendar_id = default_calendar_id
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
        end_date: Optional[datetime] = None,
        search_terms: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Fetch and process calendar events."""
        if await self._is_cache_valid() and not calendar_id:
            _LOGGER.debug("Returning cached calendar data")
            return self._cache

        # Handle calendar ID encoding once
        calendar_id = calendar_id or self.default_calendar_id
        encoded_calendar_id = quote(calendar_id, safe='')
        _LOGGER.debug("Fetching events for calendar: %s (encoded: %s)", calendar_id, encoded_calendar_id)

        start_time = start_date or datetime.strptime(DEFAULT_START_DATE, "%Y-%m-%d")
        end_time = end_date or datetime.now()

        start_time_str = start_time.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        end_time_str = end_time.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        
        if not self.session:
            self.session = aiohttp.ClientSession()

        try:
            token = await self._get_access_token()
            headers = {"Authorization": f"Bearer {token}"}
            training_sessions = []

            # Base URL constructed once
            url = f"https://www.googleapis.com/calendar/v3/calendars/{encoded_calendar_id}/events"

            # Use provided search terms or fall back to historical terms
            terms_to_search = search_terms or HISTORICAL_CALENDAR_SEARCH_TERMS
            _LOGGER.debug("Using search terms: %s", terms_to_search)

            for term in terms_to_search:
                _LOGGER.debug("Searching calendar %s for term: %s", calendar_id, term)

                params = {
                    "timeMin": start_time_str,
                    "timeMax": end_time_str,
                    "q": term,
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": "2500"
                }

                try:
                    #_LOGGER.debug("Making request to URL: %s with params: %s", url, params)
                    async with self.session.get(
                        url,
                        params=params,
                        headers=headers
                    ) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            _LOGGER.error(
                                "Calendar API request failed for %s with status %s: %s", 
                                calendar_id, response.status, error_text
                            )
                            _LOGGER.debug(
                                "Request details - URL: %s", 
                                str(response.real_url)
                            )
                            continue
                        
                        data = await response.json()
                        events = data.get("items", [])
                        _LOGGER.debug(
                            "Found %d events for term '%s' in calendar %s", 
                            len(events), term, calendar_id
                        )
                        
                        for event in events:
                            session = await self._process_event(event, term)
                            if session:
                                training_sessions.append(session)

                except Exception as term_err:
                    _LOGGER.error(
                        "Error processing term %s: %s", 
                        term, str(term_err)
                    )
                    continue

            unique_sessions = self._deduplicate_sessions(training_sessions)
            
            # Only cache default calendar data
            if not calendar_id or calendar_id == self.default_calendar_id:
                self._cache = unique_sessions
                self._cache_time = datetime.now()
            
            return unique_sessions

        except Exception as err:
            _LOGGER.error(
                "Failed to fetch calendar events for %s: %s", 
                calendar_id, str(err), exc_info=True
            )
            raise ValueError(ERROR_CALENDAR_FETCH)

    async def _load_credentials(self) -> Dict[str, Any]:
        """Load credentials from service account file."""
        try:
            async with async_open(self.service_account_path, 'r') as f:
                return json.loads(await f.read())
        except Exception as err:
            _LOGGER.error("Failed to load credentials: %s", str(err))
            raise ValueError(ERROR_CALENDAR_AUTH)

    async def _get_access_token(self) -> str:
        """Get or refresh the access token."""
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

    def _normalize_instructor_name(self, description: str) -> str:
        """Normalize instructor name from event description."""
        if not description:
            #_LOGGER.debug("Empty description - returning Unknown")
            return "Unknown"
            
        description = description.lower().strip()
        #_LOGGER.debug("Processing description: %s", description[:100])
        
        # First try exact matches in name mappings
        for full_name, normalized_name in TRAINER_NAME_MAPPINGS.items():
            if full_name in description:
                #_LOGGER.debug("Found exact match: %s -> %s", full_name, normalized_name)
                return normalized_name
                
        # Try to extract name after common patterns
        instructor_patterns = ['instructor:', 'instructor', 'trainer:', 'trainer']
        for pattern in instructor_patterns:
            if pattern in description:
                found_text = description.split(pattern)[1].split('\n')[0].strip()
                # Clean up the found text
                found_text = found_text.split('(')[0].strip()  # Remove anything in parentheses
                found_text = found_text.split('@')[0].strip()  # Remove anything after @

                _LOGGER.debug("Found instructor text: '%s' using pattern: '%s'", found_text, pattern)
                
                # Try matching the cleaned name against mappings
                for full_name, normalized_name in TRAINER_NAME_MAPPINGS.items():
                    if full_name in found_text:
                        _LOGGER.debug("Found instructor text: '%s' using pattern: '%s'", found_text, pattern)
                        return normalized_name
                        
                # If no mapping found, try matching first name against TRAINERS list
                first_name = found_text.split()[0].capitalize()
                if first_name in TRAINERS:
                    _LOGGER.debug("Matched first name: %s", first_name)
                    return first_name
                    
        # If we got here and still haven't found a match, try one last scan for trainer names
        for trainer in TRAINERS:
            if trainer.lower() in description:
                _LOGGER.debug("Found trainer name in description: %s", trainer)
                return trainer
                
        _LOGGER.warning("Could not extract trainer name from: %s", description[:100])
        return "Unknown"

    async def _process_event(self, event: Dict[str, Any], search_term: str) -> Optional[Dict[str, Any]]:
        """Process a single calendar event."""
        try:
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

            instructor = self._normalize_instructor_name(event.get('description', ''))

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
        """Get the next scheduled session."""
        if not self.session:
            self.session = aiohttp.ClientSession()
        try:
            now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            future = (datetime.now(timezone.utc) + timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
            token = await self._get_access_token()
            headers = {"Authorization": f"Bearer {token}"}

            # Encode calendar ID
            encoded_calendar_id = quote(self.default_calendar_id, safe='')
            url = f"https://www.googleapis.com/calendar/v3/calendars/{encoded_calendar_id}/events"

            for term in CALENDAR_SEARCH_TERMS:
                params = {
                    "timeMin": now,
                    "timeMax": future,
                    "q": term,
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": "1"
                }

                _LOGGER.debug("Making next session request to URL: %s with params: %s", url, params)
                
                async with self.session.get(
                    url,
                    params=params,
                    headers=headers
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        _LOGGER.error(
                            "Calendar API request failed for %s with status %s: %s", 
                            self.default_calendar_id, response.status, error_text
                        )
                        _LOGGER.debug(
                            "Request details - URL: %s", 
                            str(response.real_url)
                        )
                        continue
                            
                    data = await response.json()
                    events = data.get("items", [])
                    if events:
                        session = await self._process_event(events[0], term)
                        if session:
                            _LOGGER.debug(
                                "Next session found: %s with %s", 
                                session.get('date'), session.get('instructor')
                            )
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