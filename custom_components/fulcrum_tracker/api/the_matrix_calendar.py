"""Matrix workout calendar handler for Fulcrum Tracker."""
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from .google_calendar import AsyncGoogleCalendarHandler

_LOGGER = logging.getLogger(__name__)

class MatrixCalendarHandler:
    """Handle Matrix workout calendar data."""

    def __init__(self, google_calendar: AsyncGoogleCalendarHandler) -> None:
        self.calendar_id = "eoe8p4iqvtneb7iffpdps3ddpc@group.calendar.google.com"
        self.google_calendar = google_calendar
        _LOGGER.debug("Matrix Calendar Handler initialized with ID: %s", self.calendar_id)

    async def get_tomorrow_workout(self) -> Optional[Dict[str, Any]]:
        """Get tomorrow's workout details if user is scheduled."""
        try:
            tomorrow = datetime.now() + timedelta(days=1)
            _LOGGER.debug("Checking workouts for: %s", tomorrow.strftime('%Y-%m-%d'))
            
            # Check user schedule
            user_session = await self.google_calendar.get_next_session()
            _LOGGER.debug("User session found: %s", user_session)
            
            if not user_session:
                _LOGGER.debug("No user session scheduled")
                return None
                
            if user_session['date'] != tomorrow.strftime('%Y-%m-%d'):
                _LOGGER.debug("Next session (%s) is not tomorrow", user_session['date'])
                return None
                
            # Get Matrix calendar entry
            matrix_events = await self._get_matrix_events(tomorrow)
            _LOGGER.debug("Matrix events found: %s", matrix_events)
            
            if not matrix_events:
                _LOGGER.debug("No Matrix events found for tomorrow")
                return None
                
            workout = self._parse_workout(matrix_events[0])
            _LOGGER.debug("Parsed workout: %s", workout)
            return workout
            
        except Exception as err:
            _LOGGER.error("Error fetching Matrix workout: %s", str(err), exc_info=True)
            return None
            
    async def _get_matrix_events(self, target_date: datetime) -> list:
        """Fetch Matrix calendar events."""
        try:
            _LOGGER.debug("Fetching Matrix events for: %s", target_date.strftime('%Y-%m-%d'))
            events = await self.google_calendar.get_calendar_events(
                calendar_id=self.calendar_id,
                start_date=target_date,
                end_date=target_date + timedelta(days=1)
            )
            _LOGGER.debug("Found %d Matrix events", len(events))
            return events
        except Exception as err:
            _LOGGER.error("Error fetching Matrix events: %s", str(err), exc_info=True)
            return []
            
    def _parse_workout(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Parse workout details from calendar event."""
        _LOGGER.debug("Parsing workout from event: %s", event.get('summary', ''))
        
        if not event.get('subject'):
            _LOGGER.debug("No subject found in event")
            return None
            
        parts = event['subject'].split('|')
        workout_data = {
            'type': parts[0].strip() if len(parts) > 0 else None,
            'lifts': parts[1].strip() if len(parts) > 1 else None,
            'meps': parts[2].strip() if len(parts) > 2 else None,
            'raw_summary': event['summary']
        }
        
        _LOGGER.debug("Parsed workout data: %s", workout_data)
        return workout_data