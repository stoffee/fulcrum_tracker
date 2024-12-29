"""ZenPlanner calendar data fetcher."""
from datetime import datetime, timedelta
import logging
from typing import Any, Dict

_LOGGER = logging.getLogger(__name__)

class ZenPlannerCalendar:
    """Class to handle ZenPlanner calendar operations."""

    def __init__(self, auth, person_id: str, client_id: str) -> None:
        """Initialize the calendar handler."""
        self.auth = auth
        self.person_id = person_id
        self.client_id = client_id
        self.base_url = "https://fulcrum.sites.zenplanner.com"

    def get_attendance_data(self) -> Dict[str, Any]:
        """Fetch attendance data from ZenPlanner."""
        try:
            # Ensure we're logged in
            if not self.auth.is_logged_in():
                if not self.auth.login():
                    raise Exception("Failed to login")

            # Get current month's data
            current_date = datetime.now()
            start_date = current_date.replace(day=1)
            end_date = (current_date.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)

            # Fetch attendance page
            attendance_url = f"{self.base_url}/person-attendance.cfm"
            params = {
                "personId": self.person_id,
                "clientId": self.client_id,
                "startDate": start_date.strftime("%Y-%m-%d"),
                "endDate": end_date.strftime("%Y-%m-%d"),
            }
            
            response = self.auth.session.get(attendance_url, params=params)
            if not response.ok:
                raise Exception(f"Failed to fetch attendance data: {response.status_code}")

            # For now, return some dummy data
            # TODO: Implement actual parsing of the attendance page
            return {
                "total_sessions": 0,
                "monthly_sessions": 0,
                "last_session": current_date.strftime("%Y-%m-%d"),
                "trainer_stats": {},
            }

        except Exception as ex:
            _LOGGER.error("Error fetching attendance data: %s", str(ex))
            return {
                "total_sessions": 0,
                "monthly_sessions": 0,
                "last_session": None,
                "trainer_stats": {},
            }