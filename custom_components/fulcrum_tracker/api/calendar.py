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
        self.session = auth.requests_session
        self.base_url = f"{API_BASE_URL}{API_ENDPOINTS['workouts']}"
        _LOGGER.debug("Calendar handler initialized")

    async def get_day_attendance(self, date: datetime) -> Dict[str, Any]:
        """Fetch attendance data for a specific day."""
        _LOGGER.debug("Fetching attendance for: %s", date.strftime(DATE_FORMAT))
        
        try:
            # Format URL with the specific date
            url = f"{self.base_url}?&startdate={date.strftime(DATE_FORMAT)}"
            
            response = self.session.get(url)
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
            
            while fetch_date.date() <= current_date.date():
                month_data = await self.fetch_month(fetch_date)
                
                if month_data:
                    all_data.extend(month_data)
                
                # Move to next month using calendar navigation or fallback
                try:
                    fetch_date = await self._get_next_month_date(fetch_date)
                except ValueError:
                    # Fallback to manual increment
                    if fetch_date.month == 12:
                        fetch_date = datetime(fetch_date.year + 1, 1, 1)
                    else:
                        fetch_date = fetch_date.replace(month=fetch_date.month + 1)
                
                time.sleep(DEFAULT_SLEEP_TIME)  # Be nice to their servers
            
            return self._process_history_data(all_data)

        except Exception as err:
            _LOGGER.error("Error fetching history: %s", str(err))
            return self._empty_attendance_data()

    async def fetch_month(self, start_date: datetime) -> List[Dict[str, Any]]:
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

    async def _get_next_month_date(self, current_date: datetime) -> datetime:
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
        
        raise ValueError("No next month link found")

    def _process_history_data(self, history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Process raw history data into structured format."""
        if not history:
            return self._empty_attendance_data()

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
            "monthly_sessions": current_month_sessions,
            "last_session": history[-1]['date'] if history else None,
            "all_sessions": history
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

            return {
                "total_sessions": total_sessions,
                "monthly_sessions": current_month_sessions,
                "last_session": last_session_date.strftime('%Y-%m-%d') if last_session_date else None,
                "all_sessions": all_sessions
            }

        except Exception as err:
            _LOGGER.error("Error fetching attendance data: %s", str(err))
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