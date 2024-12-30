"""ZenPlanner calendar data handler."""
from datetime import datetime, timedelta
import logging
import time
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from ..const import (
    API_BASE_URL,
    API_ENDPOINTS,
    DEFAULT_SLEEP_TIME,
    DEFAULT_START_DATE,
    DATE_FORMAT,
    MONTH_FORMAT,
)

_LOGGER = logging.getLogger(__name__)

class ZenPlannerCalendar:
    """Handler for ZenPlanner calendar and attendance data."""

    def __init__(self, auth) -> None:
        """Initialize calendar handler."""
        self.auth = auth
        self.base_url = f"{API_BASE_URL}{API_ENDPOINTS['workouts']}"
        _LOGGER.debug("Calendar handler initialized")

    async def get_day_attendance(self, date: datetime) -> Dict[str, Any]:
        """Fetch attendance data for a specific day."""
        _LOGGER.debug("Fetching attendance for: %s", date.strftime(DATE_FORMAT))
        
        try:
            # Format URL with the specific date
            url = f"{self.base_url}?&startdate={date.strftime(DATE_FORMAT)}"
            
            response = self.auth.requests_session.get(url)
            if not response.ok:
                _LOGGER.error("Failed to fetch day: %s", response.status_code)
                return {"attended": False, "date": date.strftime(DATE_FORMAT)}
                
            soup = BeautifulSoup(response.text, 'html.parser')
            day_block = soup.find('div', class_='dayBlock', attrs={'date': date.strftime(DATE_FORMAT)})
            
            if not day_block:
                return {"attended": False, "date": date.strftime(DATE_FORMAT)}
            
            # Process the day's data
            day_data = {
                'date': date.strftime(DATE_FORMAT),
                'attended': 'attended' in day_block.get('class', ''),
                'has_results': 'hasResults' in day_block.get('class', ''),
                'is_pr': 'isPR' in day_block.get('class', ''),
                'details': day_block.get('tooltiptext', '').strip(),
                'month_year': date.strftime(MONTH_FORMAT)
            }
            
            if day_data['attended']:
                _LOGGER.info("🏋️ Found attendance for %s!", date.strftime(DATE_FORMAT))
                if day_data['has_results']:
                    _LOGGER.info("📝 Results were logged!")
                if day_data['is_pr']:
                    _LOGGER.info("🎯 PR achieved on this day!")
            
            return day_data

        except Exception as err:
            _LOGGER.error("Error fetching day attendance: %s", str(err))
            return {"attended": False, "date": date.strftime(DATE_FORMAT)}

    # Keep existing methods but update fetch_all_history to use the new day fetch
    async def fetch_all_history(self, start_date: Optional[datetime] = None) -> Dict[str, Any]:
        """Fetch complete training history from start date to present."""
        if start_date is None:
            start_date = datetime.strptime(DEFAULT_START_DATE, DATE_FORMAT)
        
        _LOGGER.info("🎯 Starting historical fetch from %s", 
                    start_date.strftime(MONTH_FORMAT))
        
        try:
            all_data = []
            current_date = datetime.now()
            fetch_date = start_date
            
            # Fetch day by day
            while fetch_date.date() <= current_date.date():
                day_data = await self.get_day_attendance(fetch_date)
                if day_data['attended']:
                    all_data.append(day_data)
                
                fetch_date += timedelta(days=1)
                time.sleep(DEFAULT_SLEEP_TIME)  # Be nice to their servers
            
            return self._process_history_data(all_data)

        except Exception as err:
            _LOGGER.error("Error fetching history: %s", str(err))
            return {
                "total_sessions": 0,
                "sessions": [],
                "current_month_sessions": 0,
                "latest_session": None
            }

    def _get_next_month_date(self, current_date: datetime) -> datetime:
        """Get next month's date from calendar navigation."""
        response = self.auth.requests_session.get(
            f"{self.base_url}?&startdate={current_date.strftime(DATE_FORMAT)}"
        )
        
        soup = BeautifulSoup(response.text, 'html.parser')
        next_link = soup.find('a', class_='next')
        
        if next_link and 'href' in next_link.attrs:
            next_date_str = next_link['href'].split('startdate=')[-1]
            try:
                return datetime.strptime(next_date_str, DATE_FORMAT)
            except ValueError:
                raise ValueError(f"Invalid date format in navigation: {next_date_str}")
        
        raise ValueError("No next month link found")

    def _process_history_data(self, history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Process raw history data into structured format."""
        if not history:
            return {
                "total_sessions": 0,
                "sessions": [],
                "current_month_sessions": 0,
                "latest_session": None
            }

        # Sort chronologically
        history.sort(key=lambda x: datetime.strptime(x['date'], DATE_FORMAT))
        
        # Get current month stats
        current_month = datetime.now().strftime(MONTH_FORMAT)
        current_month_sessions = sum(
            1 for session in history 
            if session['month_year'] == current_month
        )
        
        return {
            "total_sessions": len(history),
            "sessions": history,
            "current_month_sessions": current_month_sessions,
            "latest_session": history[-1]['date'] if history else None
        }

    def get_attendance_data(self) -> Dict[str, Any]:
        """Get formatted attendance data for Home Assistant."""
        try:
            _LOGGER.debug("Starting attendance data fetch")
            
            # Verify/refresh authentication
            if not self.auth.is_logged_in():
                _LOGGER.debug("Session expired, re-authenticating")
                if not self.auth.login():
                    raise ValueError("Failed to authenticate")
            
            # Fetch all history
            history = self.fetch_all_history()
            
            return {
                "total_sessions": history["total_sessions"],
                "monthly_sessions": history["current_month_sessions"],
                "last_session": history["latest_session"],
                "all_sessions": history["sessions"]
            }

        except Exception as err:
            _LOGGER.error("Error fetching attendance data: %s", str(err))
            return {
                "total_sessions": 0,
                "monthly_sessions": 0,
                "last_session": None,
                "all_sessions": []
            }