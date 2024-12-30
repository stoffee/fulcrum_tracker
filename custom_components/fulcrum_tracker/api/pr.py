"""ZenPlanner PR (Personal Record) data handler."""
import logging
import re
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
        _LOGGER.debug("PR handler initialized for user %s", user_id)

    def fetch_prs(self) -> List[Dict[str, str]]:
        """Fetch and process all PR data."""
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

    def _process_pr_entries(self, entries: List[re.Match]) -> List[Dict[str, str]]:
        """Process raw PR entries into structured data."""
        pr_dict = {}
        
        for entry in entries:
            entry_text = entry.group(0)
            
            # Extract all fields
            fields = {
                'name': self._extract_field(entry_text, 'skillname'),
                'pr': self._extract_field(entry_text, 'pr'),
                'last': self._extract_field(entry_text, 'lastresult'),
                'days': self._extract_field(entry_text, 'dayssince'),
                'tries': self._extract_field(entry_text, 'tries')
            }
            
            # Only process entries with required fields
            if fields['name'] and fields['pr']:
                # Use combination of name and PR as key to deduplicate
                key = f"{fields['name']}_{fields['pr']}"
                pr_dict[key] = fields

        # Convert to list and sort by name
        prs = list(pr_dict.values())
        prs.sort(key=lambda x: x['name'])
        
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
    def _format_recent_prs(recent_prs: List[Dict[str, str]]) -> str:
        """Format recent PRs for display."""
        if not recent_prs:
            return "No recent PRs"
            
        return ", ".join(
            f"{pr['name']}: {pr['value']}" 
            for pr in recent_prs
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