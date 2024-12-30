"""ZenPlanner PR (Personal Record) data handler."""
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from ..const import (
    API_BASE_URL,
    API_ENDPOINTS,
    DEFAULT_USER_ID
)

_LOGGER = logging.getLogger(__name__)

class PRHandler:
    """Handler for ZenPlanner PR data."""

    def __init__(self, auth, user_id: str = DEFAULT_USER_ID) -> None:
        """Initialize PR handler."""
        self.auth = auth
        self.user_id = user_id
        self.base_url = f"{API_BASE_URL}{API_ENDPOINTS['pr_page']}"
        self._cached_prs = {}  # Store previous PRs for comparison
        _LOGGER.debug("PR handler initialized for user %s", user_id)

    async def fetch_prs(self) -> List[Dict[str, str]]:
        """Fetch all PR data."""
        try:
            _LOGGER.debug("Starting PR fetch")
            
            # Verify/refresh authentication
            if not self.auth.is_logged_in():
                _LOGGER.debug("Session expired, re-authenticating")
                if not self.auth.login():
                    raise ValueError("Failed to authenticate")

            # Fetch PR page
            response = self.auth.requests_session.get(self.base_url)
            if not response.ok:
                raise ConnectionError(f"Failed to fetch PR page: {response.status_code}")

            content = response.text
            _LOGGER.debug("Got PR page (%d characters)", len(content))

            # Extract PR data
            data_match = re.search(
                r'personResults\.resultSet\s*=\s*\[(.*?)\];', 
                content, 
                re.DOTALL
            )
            
            if not data_match:
                raise ValueError("No PR data found in page")

            data = data_match.group(1)
            _LOGGER.debug("Found PR data section (%d characters)", len(data))

            # Process all PR entries
            entries = list(re.finditer(
                rf'{{[^}}]*personid\s*:\s*["\']?{self.user_id}[^}}]+}}', 
                data
            ))
            _LOGGER.debug("Found %d PR entries", len(entries))

            return self._process_pr_entries(entries)

        except Exception as err:
            _LOGGER.error("Error fetching PRs: %s", str(err))
            return []

    async def get_todays_prs(self) -> Dict[str, Any]:
        """Fetch and check just today's PRs."""
        try:
            _LOGGER.debug("🔍 Checking today's PRs...")
            
            # Get current PR data
            current_prs = await self._fetch_raw_prs()
            
            if not current_prs:
                return self._empty_pr_data()

            # Look for new PRs (ones with 0 days since)
            new_prs = []
            for pr in current_prs:
                if pr.get('days') == '0':  # Today's PR!
                    new_prs.append({
                        'name': pr['name'],
                        'value': pr['pr'],
                        'previous': self._get_previous_value(pr['name'])
                    })
                    # Update cache
                    self._cached_prs[pr['name']] = pr['pr']

            if new_prs:
                _LOGGER.info("🎉 Found %d new PR(s) today!", len(new_prs))
                for pr in new_prs:
                    improvement = ""
                    if pr['previous']:
                        improvement = f" (up from {pr['previous']})"
                    _LOGGER.info("💪 New PR for %s: %s%s", 
                               pr['name'], pr['value'], improvement)

            return {
                "recent_prs": self._format_recent_prs(new_prs),
                "total_prs": len(current_prs),
                "recent_pr_count": len(new_prs),
                "pr_details": current_prs
            }

        except Exception as err:
            _LOGGER.error("Error checking today's PRs: %s", str(err))
            return self._empty_pr_data()

    def _get_previous_value(self, exercise_name: str) -> Optional[str]:
        """Get the previous PR value for comparison."""
        return self._cached_prs.get(exercise_name)

    async def _fetch_raw_prs(self) -> List[Dict[str, str]]:
        """Fetch raw PR data from ZenPlanner."""
        try:
            response = self.auth.requests_session.get(self.base_url)
            if not response.ok:
                raise ConnectionError(f"Failed to fetch PR page: {response.status_code}")

            content = response.text
            data_match = re.search(
                r'personResults\.resultSet\s*=\s*\[(.*?)\];', 
                content, 
                re.DOTALL
            )
            
            if not data_match:
                return []

            # Process PR entries
            entries = list(re.finditer(
                rf'{{[^}}]*personid\s*:\s*["\']?{self.user_id}[^}}]+}}', 
                data_match.group(1)
            ))
            
            return self._process_pr_entries(entries)

        except Exception as err:
            _LOGGER.error("Error fetching raw PRs: %s", str(err))
            return []

    def _process_pr_entries(self, entries: List[re.Match]) -> List[Dict[str, str]]:
        """Process raw PR entries with some enthusiasm!"""
        pr_dict = {}
        
        for entry in entries:
            entry_text = entry.group(0)
            
            fields = {
                'name': self._extract_field(entry_text, 'skillname'),
                'pr': self._extract_field(entry_text, 'pr'),
                'last': self._extract_field(entry_text, 'lastresult'),
                'days': self._extract_field(entry_text, 'dayssince'),
                'tries': self._extract_field(entry_text, 'tries')
            }
            
            if fields['name'] and fields['pr']:
                key = f"{fields['name']}_{fields['pr']}"
                pr_dict[key] = fields

        # Sort by name but add some personality
        prs = list(pr_dict.values())
        prs.sort(key=lambda x: x['name'])
        
        if prs:
            _LOGGER.debug("💪 Found %d different exercises with PRs!", len(prs))
        
        return prs

    @staticmethod
    def _extract_field(text: str, field: str) -> Optional[str]:
        """Extract a field value from PR entry text."""
        match = re.search(rf'{field}:\s*["\']([^"\']+)["\']', text)
        return match.group(1) if match else None

    def get_formatted_prs(self) -> Dict[str, any]:
        """Get formatted PR data for Home Assistant."""
        try:
            prs = self.fetch_prs()
            
            if not prs:
                return self._empty_pr_data()

            # Find recent PRs (last 7 days)
            recent_prs = []
            recent_count = 0
            for pr in prs:
                if pr.get('days') and int(pr['days']) <= 7:
                    recent_count += 1
                    recent_prs.append({
                        'name': pr['name'],
                        'value': pr['pr'],
                        'days_ago': pr['days']
                    })

            # Create success response
            return {
                "recent_prs": self._format_recent_prs(recent_prs),
                "total_prs": len(prs),
                "recent_pr_count": recent_count,
                "pr_details": prs
            }

        except Exception as err:
            _LOGGER.error("Error formatting PRs: %s", str(err))
            return self._empty_pr_data()

    @staticmethod
    def _format_recent_prs(prs: List[Dict[str, str]]) -> str:
        """Format PRs with extra enthusiasm!"""
        if not prs:
            return "No new PRs yet today... but there's still time! 💪"
            
        return ", ".join(
            f"{pr['name']}: {pr['value']} 🎯" 
            for pr in prs
        )

    @staticmethod
    def _empty_pr_data() -> Dict[str, any]:
        """Return empty PR data structure."""
        return {
            "recent_prs": "No PR data available",
            "total_prs": 0,
            "recent_pr_count": 0,
            "pr_details": []
        }