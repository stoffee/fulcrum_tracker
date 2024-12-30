"""ZenPlanner calendar and attendance data handler."""
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

    def fetch_month(self, start_date: datetime) -> List[Dict[str, Any]]:
        """Fetch and process a specific month's training data."""
        url = f"{self.base_url}?&startdate={start_date.strftime(DATE_FORMAT)}"
        current_date = datetime.now()
        
        _LOGGER.debug("Fetching month: %s", start_date.strftime(MONTH_FORMAT))
        _LOGGER.debug("URL: %s", url)
        
        try:
            response = self.auth.requests_session.get(url)
            if not response.ok:
                _LOGGER.error("Failed to fetch month: %s", response.status_code)
                return []
                
            soup = BeautifulSoup(response.text, 'html.parser')
            days = soup.find_all('div', class_='dayBlock')
            
            month_data = []
            target_month = start_date.month
            
            for day in days:
                if not day.get('date'):
                    continue
                    
                date_str = day.get('date')
                day_date = datetime.strptime(date_str, DATE_FORMAT)
                
                # Skip if not in target month
                if day_date.month != target_month:
                    continue
                
                # Skip future dates
                if day_date.date() > current_date.date():
                    _LOGGER.debug("Skipping future date: %s", date_str)
                    continue
                
                # Process attended sessions
                attended = 'attended' in day.get('class', '')
                if attended:
                    day_data = {
                        'date': date_str,
                        'attended': attended,
                        'has_results': 'hasResults' in day.get('class', ''),
                        'is_pr': 'isPR' in day.get('class', ''),
                        'details': day.get('tooltiptext', '').strip(),
                        'month_year': day_date.strftime(MONTH_FORMAT)
                    }
                    month_data.append(day_data)
                    
            return month_data

        except Exception as err:
            _LOGGER.error("Error processing month %s: %s", 
                         start_date.strftime(MONTH_FORMAT), str(err))
            return []

    def fetch_all_history(self, start_date: Optional[datetime] = None) -> Dict[str, Any]:
        """Fetch complete training history from start date to present."""
        if start_date is None:
            start_date = datetime.strptime(DEFAULT_START_DATE, DATE_FORMAT)
        
        _LOGGER.info("Starting historical fetch from %s", 
                    start_date.strftime(MONTH_FORMAT))
        
        try:
            all_data = []
            current_date = datetime.now()
            fetch_date = start_date.replace(day=1)
            
            # Calculate total months for progress tracking
            total_months = ((current_date.year - start_date.year) * 12 + 
                          current_date.month - start_date.month)
            months_processed = 0
            
            while fetch_date.date() <= current_date.date():
                _LOGGER.debug("Processing month %d of %d", 
                            months_processed + 1, total_months)
                
                month_data = self.fetch_month(fetch_date)
                if month_data:
                    _LOGGER.debug("Found %d sessions", len(month_data))
                    all_data.extend(month_data)
                else:
                    _LOGGER.debug("No sessions found for %s", 
                                fetch_date.strftime(MONTH_FORMAT))
                
                # Try to get next month from navigation
                try:
                    fetch_date = self._get_next_month_date(fetch_date)
                except Exception as err:
                    _LOGGER.warning("Navigation error, using manual increment: %s", 
                                  str(err))
                    if fetch_date.month == 12:
                        fetch_date = datetime(fetch_date.year + 1, 1, 1)
                    else:
                        fetch_date = fetch_date.replace(month=fetch_date.month + 1)
                
                months_processed += 1
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