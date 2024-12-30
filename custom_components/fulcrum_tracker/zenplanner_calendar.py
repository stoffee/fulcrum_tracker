"""ZenPlanner calendar data fetcher."""
from datetime import datetime, timedelta
import logging
from typing import Any, Dict
from bs4 import BeautifulSoup

_LOGGER = logging.getLogger(__name__)

class ZenPlannerCalendar:
    """Class to handle ZenPlanner calendar operations."""

    def __init__(self, auth, person_id: str, client_id: str) -> None:
        """Initialize the calendar handler."""
        self.auth = auth
        self.person_id = person_id
        self.client_id = client_id
        self.base_url = "https://fulcrum.sites.zenplanner.com"
        self.session_patterns = [
            "Small Group Personal Training Hawthorne",
            "Small Group Training",
            "Small Group",
            "Fulcrum",
            "exercise",
            "fix back",
            "fucking back exercise",
            "Do the back muscles",
            "Tabor Stair Climb"
        ]
        _LOGGER.debug("ZenPlannerCalendar initialized with person_id: %s", person_id)

    def get_attendance_data(self) -> Dict[str, Any]:
        """Fetch attendance data from ZenPlanner."""
        try:
            _LOGGER.debug("Starting attendance data fetch")
            
            # Check login status
            is_logged_in = self.auth.is_logged_in()
            _LOGGER.debug("Current login status: %s", is_logged_in)
            
            if not is_logged_in:
                _LOGGER.debug("Not logged in, attempting login")
                if not self.auth.login():
                    raise Exception("Failed to login")
                _LOGGER.debug("Login successful")

            # Fetch attendance page
            attendance_url = f"{self.base_url}/person-attendance.cfm"
            params = {
                "personId": self.person_id,
                "view": "list"
            }
            _LOGGER.debug("Fetching attendance data from URL: %s with params: %s", attendance_url, params)
            
            response = self.auth.session.get(attendance_url, params=params)
            _LOGGER.debug("Response status code: %s", response.status_code)
            
            if not response.ok:
                raise Exception(f"Failed to fetch attendance data: {response.status_code}")

            # Parse the attendance page
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find the attendance table - using the correct classes
            attendance_table = soup.find('table', {'class': ['table', 'table-bordered', 'table-striped', 'LinkedRows']})
            if not attendance_table:
                _LOGGER.error("Could not find attendance table in HTML response")
                _LOGGER.debug("Available tables: %s", [table.get('class', ['no-class']) for table in soup.find_all('table')])
                raise Exception("Could not find attendance table")

            # Count sessions
            total_sessions = 0
            current_month_sessions = 0
            current_month = datetime.now().strftime('%Y-%m')
            last_session_date = None

            # Process each row in the table
            _LOGGER.debug("Starting to process table rows")
            rows = attendance_table.find_all('tr')
            _LOGGER.debug("Found %d rows in attendance table", len(rows))
            
            for row in rows[1:]:  # Skip header row
                cols = row.find_all('td')
                if len(cols) >= 3:
                    date_str = cols[0].text.strip()
                    class_name = cols[2].text.strip()
                    _LOGGER.debug("Processing row - Date: %s, Class: %s", date_str, class_name)

                    try:
                        session_date = datetime.strptime(date_str, '%m/%d/%Y')
                        
                        # Check if this is a training session
                        is_training = any(pattern.lower() in class_name.lower() for pattern in self.session_patterns)
                        if is_training:
                            total_sessions += 1
                            _LOGGER.debug("Found training session: %s", class_name)
                            
                            # Track last session
                            if last_session_date is None or session_date > last_session_date:
                                last_session_date = session_date
                            
                            # Count current month sessions
                            if session_date.strftime('%Y-%m') == current_month:
                                current_month_sessions += 1
                    
                    except ValueError as e:
                        _LOGGER.warning("Could not parse date: %s - %s", date_str, e)
                        continue

            result = {
                "total_sessions": total_sessions,
                "monthly_sessions": current_month_sessions,
                "last_session": last_session_date.strftime('%Y-%m-%d') if last_session_date else None
            }
            _LOGGER.debug("Final results: %s", result)
            return result

        except Exception as ex:
            _LOGGER.error("Error fetching attendance data: %s", str(ex))
            return {
                "total_sessions": 0,
                "monthly_sessions": 0,
                "last_session": None
            }