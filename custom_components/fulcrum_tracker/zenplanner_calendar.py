"""ZenPlanner calendar data fetcher."""
from datetime import datetime, timedelta
import logging
from typing import Any, Dict, List

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
        _LOGGER.debug("ZenPlannerCalendar initialized with person_id: %s", person_id)

    def fetch_month(self, start_date: datetime) -> List[Dict[str, Any]]:
        """Fetch a specific month's data."""
        # Fixed URL structure
        url = f"{self.base_url}/calendar/month-calendar.cfm"  # Changed this line
        params = {
            "clientId": self.client_id,
            "personId": self.person_id,
            "startdate": start_date.strftime('%Y-%m-%d'),
            "type": "person"  # Added this parameter
        }
        current_date = datetime.now()
        
        _LOGGER.debug(f"Fetching month: {start_date.strftime('%B %Y')}")
        
        response = self.auth.session.get(url, params=params)
        if not response.ok:
            _LOGGER.error(f"Failed to fetch month: {response.status_code}")
            return []
                
        soup = BeautifulSoup(response.text, 'html.parser')
        days = soup.find_all('div', class_='dayBlock')
        
        month_data = []
        target_month = start_date.month
        
        for day in days:
            if not day.get('date'):
                continue
                
            date_str = day.get('date')
            day_date = datetime.strptime(date_str, '%Y-%m-%d')
            
            if day_date.month != target_month:
                continue
            
            attended = 'attended' in day.get('class', [])
            has_results = 'hasResults' in day.get('class', [])
            is_pr = 'isPR' in day.get('class', [])
            
            if day_date.date() > current_date.date():
                _LOGGER.debug(f"Skipping future date: {date_str}")
                continue
                    
            if attended:
                day_data = {
                    'date': date_str,
                    'attended': attended,
                    'has_results': has_results,
                    'is_pr': is_pr,
                    'details': day.get('tooltiptext', '').strip(),
                    'month_year': day_date.strftime('%B %Y')
                }
                month_data.append(day_data)
                    
        return month_data

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

            # Calculate date range (from Nov 2021 to present)
            start_date = datetime(2021, 11, 1)
            current_date = datetime.now()
            
            # Initialize counters
            total_sessions = 0
            current_month_sessions = 0
            last_session_date = None
            all_sessions = []

            # Fetch data month by month
            current_month = start_date
            while current_month <= current_date:
                _LOGGER.debug(f"Fetching data for {current_month.strftime('%B %Y')}")
                month_data = self.fetch_month(current_month)
                all_sessions.extend(month_data)
                
                # Move to next month
                current_month = (current_month.replace(day=1) + timedelta(days=32)).replace(day=1)

            # Process all sessions
            current_month_str = current_date.strftime('%B %Y')
            for session in all_sessions:
                total_sessions += 1
                
                # Track current month sessions
                if session['month_year'] == current_month_str:
                    current_month_sessions += 1
                
                # Track last session
                session_date = datetime.strptime(session['date'], '%Y-%m-%d')
                if last_session_date is None or session_date > last_session_date:
                    last_session_date = session_date

            result = {
                "total_sessions": total_sessions,
                "monthly_sessions": current_month_sessions,
                "last_session": last_session_date.strftime('%Y-%m-%d') if last_session_date else None,
                "all_sessions": len(all_sessions)
            }
            _LOGGER.debug("Final results: %s", result)
            return result

        except Exception as ex:
            _LOGGER.error("Error fetching attendance data: %s", str(ex))
            return {
                "total_sessions": 0,
                "monthly_sessions": 0,
                "last_session": None,
                "all_sessions": 0
            }