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
            _LOGGER.debug("Checking Matrix workouts for: %s", tomorrow.strftime('%Y-%m-%d'))
            
            # Check user schedule first
            user_session = await self.google_calendar.get_next_session()
            _LOGGER.debug("User session found: %s", user_session)
            
            if not user_session:
                _LOGGER.debug("No user session scheduled")
                return None
                
            if user_session['date'] != tomorrow.strftime('%Y-%m-%d'):
                _LOGGER.debug("Next session (%s) is not tomorrow", user_session['date'])
                return None
                
            # Only search for Matrix-style workout entries (e.g., "HIIT + Core | SGT...")
            matrix_events = await self.google_calendar.get_calendar_events(
                calendar_id=self.calendar_id,
                start_date=tomorrow,
                end_date=tomorrow + timedelta(days=1)
            )
            
            # Filter for Matrix-style events
            matrix_events = [
                event for event in matrix_events 
                if '|' in event.get('summary', '') and 'MEPs' in event.get('summary', '')
            ]
            
            _LOGGER.debug("Matrix events found: %s", matrix_events)
            
            if not matrix_events:
                #_LOGGER.debug("No Matrix events found for tomorrow")
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
            _LOGGER.debug("🎯 Fetching Matrix events for: %s", target_date.strftime('%Y-%m-%d'))
            
            # Fetch ALL events for the target date
            events = await self.google_calendar.get_calendar_events(
                calendar_id=self.calendar_id,
                start_date=target_date,
                end_date=target_date + timedelta(days=1),
                search_terms=None  # No search terms - get all events
            )
            
            # Filter for Matrix workout format
            matrix_events = []
            for event in events:
                summary = event.get('summary', '')
                if '|' in summary and 'MEPs' in summary:
                    _LOGGER.debug("✅ Found Matrix workout: %s", summary)
                    matrix_events.append(event)
                
            _LOGGER.info("📊 Found %d Matrix workouts for %s", 
                        len(matrix_events), target_date.strftime('%Y-%m-%d'))
            return matrix_events
            
        except Exception as err:
            _LOGGER.error("💥 Error fetching Matrix events: %s", str(err))
            return []
            
    def _parse_workout(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Parse workout details from Matrix calendar event."""
        try:
            summary = event.get('summary', '')
            _LOGGER.debug("🏋️ Parsing Matrix workout: %s", summary)

            # Return early if no summary or invalid format
            if not summary or '|' not in summary:
                _LOGGER.warning("⚠️ Invalid workout format: %s", summary)
                return None

            # Split and clean parts
            parts = [part.strip() for part in summary.split('|')]
            if len(parts) != 3:
                _LOGGER.warning("⚠️ Wrong number of workout parts: %d", len(parts))
                return None

            # Parse individual components
            workout_data = {
                'type': parts[0],                                    # e.g. "HIIT + Core"
                'lifts': parts[1].replace('SGT -', '').strip(),     # e.g. "Lift of Choice"
                'meps': parts[2].replace('MEPs -', '').strip(),     # e.g. "140-150"
                'raw_summary': summary,
                'created_by': event.get('creator', {}).get('email', 'Unknown'),
                'last_updated': event.get('updated', None)
            }

            _LOGGER.debug("✅ Parsed workout data: %s", workout_data)
            return workout_data

        except Exception as err:
            _LOGGER.error("💥 Error parsing workout: %s", str(err))
            return None