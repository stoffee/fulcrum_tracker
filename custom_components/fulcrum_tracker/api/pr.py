"""ZenPlanner PR (Personal Record) data handler - FIXED VERSION."""
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..const import (
    API_BASE_URL,
    API_ENDPOINTS,
    EXERCISE_TYPES,
    EXERCISE_MAPPINGS,
)

_LOGGER = logging.getLogger(__name__)

class PRHandler:
    """Handler for ZenPlanner PR data."""

    def __init__(self, auth, user_id: Optional[str] = None) -> None:
        """Initialize PR handler."""
        self.auth = auth
        self.user_id = user_id  # Can be None - will auto-detect
        self.base_url = f"{API_BASE_URL}{API_ENDPOINTS['pr_page']}"
        self._cached_prs = {}
        self._exercise_cache = {}
        self._detected_user_id = None
        _LOGGER.debug("PR handler initialized (user_id will be auto-detected)")

    def _auto_detect_user_id(self, page_content: str) -> Optional[str]:
        """Auto-detect user ID from the PR page content."""
        if self._detected_user_id:
            return self._detected_user_id
            
        # Try to find user ID in various places on the page
        patterns = [
            r'personid["\s]*:["\s]*([A-F0-9-]{36})',  # Standard GUID format
            r'userId["\s]*:["\s]*([A-F0-9-]{36})',
            r'currentUser["\s]*:["\s]*([A-F0-9-]{36})',
            r'data-user-id["\s]*=["\s]*([A-F0-9-]{36})',
            r'person[iI]d["\s]*:["\s]*["\']([A-F0-9-]{36})["\']',  # More flexible
        ]
        
        for pattern in patterns:
            match = re.search(pattern, page_content, re.IGNORECASE)
            if match:
                detected_id = match.group(1)
                _LOGGER.debug("Auto-detected user ID: %s", detected_id)
                self._detected_user_id = detected_id
                return detected_id
                
        # If we can't find a specific user ID, we'll try to work with all PR data
        _LOGGER.info("Could not auto-detect user ID - will attempt to use all PR data")
        return None

    def _match_exercise_type(self, exercise_name: str) -> Optional[str]:
        """Match an exercise name to a standardized type."""
        if not exercise_name:
            return None
            
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
                    _LOGGER.error("Failed to authenticate for PR data")
                    return self._empty_prs_dict()

            session = await self.auth.requests_session
            try:
                async with session.get(self.base_url) as response:
                    if not response.ok:
                        _LOGGER.error("Failed to fetch PR page: %s", response.status)
                        return self._empty_prs_dict()
                    content = await response.text()
            except Exception as session_err:
                _LOGGER.error("Session error: %s", str(session_err))
                # Try to recover by forcing a new session
                await self.auth.close()
                session = await self.auth.requests_session
                async with session.get(self.base_url) as response:
                    if not response.ok:
                        _LOGGER.error("Failed to fetch PR page after retry: %s", response.status)
                        return self._empty_prs_dict()
                    content = await response.text()

            # Debug: Log page content snippet to understand structure
            _LOGGER.debug("PR page content preview: %s", content[:500])

            # Auto-detect user ID from page content
            detected_user_id = self._auto_detect_user_id(content)
            effective_user_id = self.user_id or detected_user_id

            # Try multiple patterns to find PR data
            data_patterns = [
                r'personResults\.resultSet\s*=\s*\[(.*?)\];',  # Original pattern
                r'resultSet\s*=\s*\[(.*?)\]',  # Simplified
                r'var\s+results\s*=\s*\[(.*?)\]',  # Alternative variable name
                r'data\s*=\s*\[(.*?)\]',  # Generic data
                r'"results"\s*:\s*\[(.*?)\]',  # JSON format
            ]
            
            data_match = None
            used_pattern = None
            
            for pattern in data_patterns:
                data_match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
                if data_match:
                    used_pattern = pattern
                    _LOGGER.debug("Found PR data using pattern: %s", pattern)
                    break
            
            if not data_match:
                # Log more of the page to help debug
                _LOGGER.warning("No PR data found in page. Searching for alternative indicators...")
                
                # Look for any indicators that this is the right page
                if 'workout' in content.lower() and 'pr' in content.lower():
                    _LOGGER.info("Page contains workout and PR keywords but no data match")
                    # Return empty but valid structure
                    return self._empty_prs_dict()
                else:
                    _LOGGER.error("Page doesn't appear to contain PR data")
                    return self._empty_prs_dict()

            data = data_match.group(1)
            _LOGGER.debug("Extracted PR data snippet: %s", data[:200])
            
            prs_by_type = {exercise_type: {} for exercise_type in EXERCISE_TYPES}
            
            # If we have a specific user ID, filter by it
            if effective_user_id:
                _LOGGER.debug("Filtering PRs for user ID: %s", effective_user_id)
                # More flexible pattern matching
                entry_patterns = [
                    rf'{{[^}}]*personid\s*:\s*["\']?{effective_user_id}[^}}]+}}',
                    rf'{{[^}}]*["\']personid["\'][^}}]*["\']?{effective_user_id}[^}}]+}}',
                ]
            else:
                # Get all PR entries and hope they're for the logged-in user
                _LOGGER.debug("No user ID available - getting all PR entries")
                entry_patterns = [
                    r'{[^}]*personid\s*:\s*["\'][^}]+}',
                    r'{[^}]*["\']personid["\'][^}]+}',
                    r'{[^}]*skillname[^}]+}',  # Look for any entry with skillname
                ]
            
            found_entries = 0
            for pattern in entry_patterns:
                entries = list(re.finditer(pattern, data, re.IGNORECASE))
                if entries:
                    _LOGGER.debug("Found %d entries with pattern: %s", len(entries), pattern)
                    for entry in entries:
                        entry_data = self._parse_pr_entry(entry.group(0))
                        if not entry_data:
                            continue
                            
                        found_entries += 1
                        exercise_type = self._match_exercise_type(entry_data['name'])
                        if exercise_type:
                            prs_by_type[exercise_type] = {
                                'value': entry_data['pr'],
                                'date': entry_data.get('date'),
                                'last_result': entry_data.get('last'),
                                'days_since': entry_data.get('days'),
                                'attempts': entry_data.get('tries')
                            }
                            _LOGGER.debug("Added PR for %s: %s", exercise_type, entry_data['pr'])
                    break  # Use the first pattern that finds entries

            _LOGGER.info("Found %d total PR entries, mapped to %d exercise types", 
                        found_entries, len([p for p in prs_by_type.values() if p]))

            self._cached_prs = prs_by_type
            return prs_by_type

        except Exception as err:
            _LOGGER.error("Error fetching PRs: %s", str(err), exc_info=True)
            return self._empty_prs_dict()

    def _parse_pr_entry(self, entry_text: str) -> Optional[Dict[str, Any]]:
        """Parse a single PR entry with more flexible patterns."""
        try:
            # Try multiple field extraction patterns
            field_patterns = {
                'name': [
                    r'skillname["\s]*:["\s]*["\']([^"\']+)["\']',
                    r'["\']skillname["\'][^:]*:["\s]*["\']([^"\']+)["\']',
                    r'name["\s]*:["\s]*["\']([^"\']+)["\']',
                ],
                'pr': [
                    r'pr["\s]*:["\s]*["\']([^"\']+)["\']',
                    r'["\']pr["\'][^:]*:["\s]*["\']([^"\']+)["\']',
                    r'record["\s]*:["\s]*["\']([^"\']+)["\']',
                ],
                'last': [
                    r'lastresult["\s]*:["\s]*["\']([^"\']+)["\']',
                    r'["\']lastresult["\'][^:]*:["\s]*["\']([^"\']+)["\']',
                    r'last["\s]*:["\s]*["\']([^"\']+)["\']',
                ],
                'days': [
                    r'dayssince["\s]*:["\s]*["\']([^"\']+)["\']',
                    r'["\']dayssince["\'][^:]*:["\s]*["\']([^"\']+)["\']',
                    r'days["\s]*:["\s]*["\']([^"\']+)["\']',
                ],
                'tries': [
                    r'tries["\s]*:["\s]*["\']([^"\']+)["\']',
                    r'["\']tries["\'][^:]*:["\s]*["\']([^"\']+)["\']',
                    r'attempts["\s]*:["\s]*["\']([^"\']+)["\']',
                ],
                'date': [
                    r'lastdate["\s]*:["\s]*["\']([^"\']+)["\']',
                    r'["\']lastdate["\'][^:]*:["\s]*["\']([^"\']+)["\']',
                    r'date["\s]*:["\s]*["\']([^"\']+)["\']',
                ]
            }
            
            fields = {}
            for field_name, patterns in field_patterns.items():
                value = None
                for pattern in patterns:
                    match = re.search(pattern, entry_text, re.IGNORECASE)
                    if match:
                        value = match.group(1)
                        break
                fields[field_name] = value
            
            # Must have at least name and pr
            if not fields['name'] or not fields['pr']:
                return None

            return fields

        except Exception as err:
            _LOGGER.error("Error parsing PR entry: %s", str(err))
            return None

    async def get_formatted_prs(self) -> Dict[str, Any]:
        """Get formatted PR data for Home Assistant."""
        try:
            prs = await self.fetch_prs()
            
            if not prs or not any(prs.values()):
                _LOGGER.info("No PR data available, returning empty structure")
                return self._empty_pr_data()

            # Format recent PRs (last 7 days)
            recent_prs = []
            recent_count = 0
            
            for exercise_type, pr_data in prs.items():
                if pr_data and pr_data.get('days_since'):
                    try:
                        days_since = int(pr_data['days_since'])
                        if days_since <= 7:
                            recent_count += 1
                            recent_prs.append({
                                'type': exercise_type,
                                'value': pr_data['value'],
                                'days_ago': pr_data['days_since']
                            })
                    except (ValueError, TypeError):
                        continue

            return {
                "prs_by_type": prs,
                "recent_prs": self._format_recent_prs(recent_prs),
                "total_prs": len([pr for pr in prs.values() if pr]),
                "recent_pr_count": recent_count,
                "user_id_detected": bool(self._detected_user_id),
                "detection_method": "auto" if self._detected_user_id else "all_data"
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

    def _empty_prs_dict(self) -> Dict[str, Dict[str, Any]]:
        """Return empty PRs dictionary by exercise type."""
        return {exercise_type: {} for exercise_type in EXERCISE_TYPES}

    @staticmethod
    def _empty_pr_data() -> Dict[str, Any]:
        """Return empty PR data structure."""
        return {
            "prs_by_type": {exercise_type: {} for exercise_type in EXERCISE_TYPES},
            "recent_prs": "No PR data available",
            "total_prs": 0,
            "recent_pr_count": 0,
            "user_id_detected": False,
            "detection_method": "none"
        }