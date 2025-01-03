"""ZenPlanner calendar data handler."""
import logging
from datetime import datetime, timedelta
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
        self.session = auth.requests_session
        self.base_url = f"{API_BASE_URL}{API_ENDPOINTS['workouts']}"
        _LOGGER.debug("Calendar handler initialized")

    def fetch_month(self, start_date: datetime) -> List[Dict[str, Any]]:
        """Fetch a specific month's data."""
        _LOGGER.debug(f"Fetching month: {start_date.strftime('%B %Y')}")
        
        url = f"{self.base_url}?&startdate={start_date.strftime('%Y-%m-%d')}"
        current_date = datetime.now()
        
        response = self.session.get(url)
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
                    'month_year': day_date.strftime(MONTH_FORMAT)
                }
                month_data.append(day_data)
                    
        return month_data

    def _get_next_month_date(self, current_date: datetime) -> datetime:
        """Get next month's date from calendar navigation."""
        response = self.session.get(
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
        
        # Fallback to manual increment
        if current_date.month == 12:
            return datetime(current_date.year + 1, 1, 1)
        return current_date.replace(month=current_date.month + 1)

    def get_attendance_data(self) -> Dict[str, Any]:
        """Get formatted attendance data for Home Assistant."""
        try:
            _LOGGER.debug("Starting attendance data fetch")
            
            # Verify/refresh authentication
            if not self.auth.is_logged_in():
                _LOGGER.debug("Session expired, re-authenticating")
                if not self.auth.login():
                    raise ValueError("Failed to authenticate")
            
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
            _LOGGER.debug(f"Fetching data for {current_month.strftime('%B %Y')}")
            
            while current_month <= current_date:
                month_data = self.fetch_month(current_month)
                all_sessions.extend(month_data)
                
                # Move to next month
                current_month = self._get_next_month_date(current_month)
                time.sleep(DEFAULT_SLEEP_TIME)

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

            return {
                "total_sessions": total_sessions,
                "monthly_sessions": current_month_sessions,
                "last_session": last_session_date.strftime('%Y-%m-%d') if last_session_date else None,
                "all_sessions": all_sessions
            }

        except Exception as err:
            _LOGGER.error("Error fetching attendance data: %s", str(err))
            return self._empty_attendance_data()

    async def get_recent_attendance(self, start_date: datetime) -> Dict[str, Any]:
        """Get recent attendance data."""
        try:
            _LOGGER.debug("Starting recent attendance fetch from %s", start_date)
            
            # Verify/refresh authentication
            if not self.auth.is_logged_in():
                _LOGGER.debug("Session expired, re-authenticating")
                if not self.auth.login():
                    raise ValueError("Failed to authenticate")
            
            # Get just the last few days of data
            current_date = datetime.now()
            start_month = datetime(start_date.year, start_date.month, 1)
            
            all_sessions = []
            current_month = start_month
            
            while current_month <= current_date:
                month_data = self.fetch_month(current_month)
                # Filter for only recent sessions
                recent_sessions = [
                    session for session in month_data 
                    if datetime.strptime(session['date'], '%Y-%m-%d') >= start_date
                ]
                all_sessions.extend(recent_sessions)
                
                if current_month.month == current_date.month:
                    break
                    
                # Move to next month
                if current_month.month == 12:
                    current_month = datetime(current_month.year + 1, 1, 1)
                else:
                    current_month = current_month.replace(month=current_month.month + 1)

            # Calculate stats for recent data
            total_sessions = len(all_sessions)
            current_month_str = current_date.strftime('%B %Y')
            current_month_sessions = sum(
                1 for s in all_sessions 
                if s['month_year'] == current_month_str
            )

            if total_sessions > 0:
                _LOGGER.info("Found %d recent sessions!", total_sessions)

            return {
                "total_sessions": total_sessions,
                "monthly_sessions": current_month_sessions,
                "last_session": max((s['date'] for s in all_sessions), default=None),
                "all_sessions": all_sessions
            }

        except Exception as err:
            _LOGGER.error("Error fetching recent attendance data: %s", str(err))
            return self._empty_attendance_data()

    @staticmethod
    def _empty_attendance_data() -> Dict[str, Any]:
        """Return empty attendance data structure."""
        return {
            "total_sessions": 0,
            "monthly_sessions": 0,
            "last_session": None,
            "all_sessions": []
        }