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
        """Get tomorrow's workout from the Matrix calendar."""
        try:
            tomorrow = datetime.now() + timedelta(days=1)
            _LOGGER.debug("📅 Fetching Matrix workout for: %s", tomorrow.strftime('%Y-%m-%d'))
            
            # Get all events for tomorrow from Matrix calendar
            events = await self.google_calendar.get_calendar_events(
                calendar_id=self.calendar_id,
                start_date=tomorrow,
                end_date=tomorrow + timedelta(days=1)
            )
            
            # Add debug logging to see what events we got
            _LOGGER.debug("📋 Raw events received: %s", [e.get('summary', '') for e in events])
            
            # Find the Matrix workout (MEPs format)
            matrix_events = [
                event for event in events 
                if event.get('summary', '') and  # Make sure summary exists
                ('|' in event.get('summary', '')) and 
                ('MEP' in event.get('summary', '').upper())  # Case-insensitive MEPs check
            ]
            
            _LOGGER.debug("🎯 Found Matrix events: %s", [e.get('summary', '') for e in matrix_events])
            
            if matrix_events:
                workout = self._parse_workout(matrix_events[0])
                _LOGGER.debug("💪 Found workout: %s", workout)
                return workout
                
            _LOGGER.debug("No Matrix workout found for tomorrow")
            return None
                
        except Exception as err:
            _LOGGER.error("❌ Error fetching Matrix workout: %s", str(err))
            return None
            
    async def _get_matrix_events(self, target_date: datetime) -> list:
        """Fetch Matrix calendar events."""
        try:
            _LOGGER.debug("🎯 Fetching all Matrix events for: %s", target_date.strftime('%Y-%m-%d'))
            
            # Get ALL events for the target date - no search terms!
            events = await self.google_calendar.get_calendar_events(
                calendar_id=self.calendar_id,
                start_date=target_date,
                end_date=target_date + timedelta(days=1)
            )
            
            # Log what we found
            _LOGGER.debug("Found %d total events in Matrix calendar", len(events) if events else 0)
            
            # Filter locally for Matrix workout format
            matrix_events = []
            for event in events:
                summary = event.get('summary', '')
                if '|' in summary and 'MEPs' in summary:
                    _LOGGER.debug("✅ Found valid Matrix workout: %s", summary)
                    matrix_events.append(event)
                
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

            # Split by pipe and clean up whitespace
            parts = [part.strip() for part in summary.split('|')]
            
            # We need at least 2 parts (workout type and SGT portion)
            if len(parts) < 2:
                _LOGGER.warning("⚠️ Insufficient workout parts: %d", len(parts))
                return None

            # Parse components we care about
            workout_data = {
                'type': parts[0],                                    # e.g. "Pull Conditioning"
                'lifts': parts[1].replace('SGT -', '').strip(),     # e.g. "Row/Pull-up + Deadlift"
                'display_format': f"{parts[0]} | {parts[1]}",       # The format you want to display
                'meps': parts[2].replace('MEPs -', '').strip() if len(parts) > 2 else None,
                'raw_summary': summary,
                'created_by': event.get('creator', {}).get('email', 'Unknown'),
                'last_updated': event.get('updated', None)
            }

            _LOGGER.debug("✅ Parsed workout data: %s", workout_data)
            return workout_data

        except Exception as err:
            _LOGGER.error("💥 Error parsing workout: %s", str(err))
            return None