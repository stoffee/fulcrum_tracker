"""ZenPlanner PR (Personal Record) data handler."""
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..const import (
    API_BASE_URL,
    API_ENDPOINTS,
    DEFAULT_USER_ID,
    EXERCISE_TYPES,
    EXERCISE_MAPPINGS,
)

_LOGGER = logging.getLogger(__name__)

class PRHandler:
    """Handler for ZenPlanner PR data."""

    def __init__(self, auth, user_id: Optional[str] = None) -> None:
        """Initialize PR handler."""
        self.auth = auth
        self.user_id = user_id or DEFAULT_USER_ID
        self.base_url = f"{API_BASE_URL}{API_ENDPOINTS['pr_page']}"
        self._cached_prs = {}
        self._exercise_cache = {}
        _LOGGER.debug("PR handler initialized for user %s", self.user_id)

    def _match_exercise_type(self, exercise_name: str) -> Optional[str]:
        """Match an exercise name to a standardized type."""
        exercise_name = exercise_name.lower()
        for exercise_type, patterns in EXERCISE_MAPPINGS.items():
            if any(pattern in exercise_name for pattern in patterns):
                return exercise_type
        return None

    async def fetch_prs(self) -> Dict[str, Dict[str, Any]]:
        """Fetch all PR data organized by exercise type."""
        try:
            is_logged_in = await self.auth.is_logged_in()
            if not is_logged_in:
                _LOGGER.debug("Not logged in, attempting login")
                login_success = await self.auth.login()
                if not login_success:
                    raise ValueError("Failed to authenticate")

            session = await self.auth.requests_session
            try:
                async with session.get(self.base_url) as response:
                    if not response.ok:
                        raise ConnectionError(f"Failed to fetch PR page: {response.status}")
                    content = await response.text()
            except Exception as session_err:
                _LOGGER.error("Session error: %s", str(session_err))
                # Try to recover by forcing a new session
                await self.auth.close()
                session = await self.auth.requests_session
                async with session.get(self.base_url) as response:
                    if not response.ok:
                        raise ConnectionError(f"Failed to fetch PR page after retry: {response.status}")
                    content = await response.text()

            data_match = re.search(
                r'personResults\.resultSet\s*=\s*\[(.*?)\];', 
                content, 
                re.DOTALL
            )
            
            if not data_match:
                raise ValueError("No PR data found in page")

            data = data_match.group(1)
            prs_by_type = {exercise_type: {} for exercise_type in EXERCISE_TYPES}
            
            for entry in re.finditer(
                rf'{{[^}}]*personid\s*:\s*["\']?{self.user_id}[^}}]+}}', 
                data
            ):
                entry_data = self._parse_pr_entry(entry.group(0))
                if not entry_data:
                    continue
                    
                exercise_type = self._match_exercise_type(entry_data['name'])
                if exercise_type:
                    prs_by_type[exercise_type] = {
                        'value': entry_data['pr'],
                        'date': entry_data.get('date'),
                        'last_result': entry_data.get('last'),
                        'days_since': entry_data.get('days'),
                        'attempts': entry_data.get('tries')
                    }

            self._cached_prs = prs_by_type
            return prs_by_type

        except Exception as err:
            _LOGGER.error("Error fetching PRs: %s", str(err))
            return {exercise_type: {} for exercise_type in EXERCISE_TYPES}

    def _parse_pr_entry(self, entry_text: str) -> Optional[Dict[str, Any]]:
        """Parse a single PR entry."""
        try:
            fields = {
                'name': self._extract_field(entry_text, 'skillname'),
                'pr': self._extract_field(entry_text, 'pr'),
                'last': self._extract_field(entry_text, 'lastresult'),
                'days': self._extract_field(entry_text, 'dayssince'),
                'tries': self._extract_field(entry_text, 'tries'),
                'date': self._extract_field(entry_text, 'lastdate')
            }
            
            if not fields['name'] or not fields['pr']:
                return None

            return fields

        except Exception as err:
            _LOGGER.error("Error parsing PR entry: %s", str(err))
            return None

    @staticmethod
    def _extract_field(text: str, field: str) -> Optional[str]:
        """Extract a field value from PR entry text."""
        match = re.search(rf'{field}:\s*["\']([^"\']+)["\']', text)
        return match.group(1) if match else None

    async def get_formatted_prs(self) -> Dict[str, Any]:
        """Get formatted PR data for Home Assistant."""
        try:
            prs = await self.fetch_prs()
            
            if not prs:
                return self._empty_pr_data()

            # Format recent PRs (last 7 days)
            recent_prs = []
            recent_count = 0
            
            for exercise_type, pr_data in prs.items():
                if pr_data and pr_data.get('days_since') and int(pr_data['days_since']) <= 7:
                    recent_count += 1
                    recent_prs.append({
                        'type': exercise_type,
                        'value': pr_data['value'],
                        'days_ago': pr_data['days_since']
                    })

            return {
                "prs_by_type": prs,
                "recent_prs": self._format_recent_prs(recent_prs),
                "total_prs": len([pr for pr in prs.values() if pr]),
                "recent_pr_count": recent_count
            }

        except Exception as err:
            _LOGGER.error("Error formatting PRs: %s", str(err))
            return self._empty_pr_data()

    @staticmethod
    def _format_recent_prs(prs: List[Dict[str, Any]]) -> str:
        """Format recent PRs with enthusiasm."""
        if not prs:
            return "No new PRs yet... but there's still time! 💪"
            
        return ", ".join(
            f"{pr['type']}: {pr['value']} 🎯" 
            for pr in prs
        )

    @staticmethod
    def _empty_pr_data() -> Dict[str, Any]:
        """Return empty PR data structure."""
        return {
            "prs_by_type": {exercise_type: {} for exercise_type in EXERCISE_TYPES},
            "recent_prs": "No PR data available",
            "total_prs": 0,
            "recent_pr_count": 0
        }