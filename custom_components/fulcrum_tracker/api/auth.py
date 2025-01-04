"""ZenPlanner authentication handler."""
import logging
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup

from ..const import (
    API_BASE_URL,
    API_ENDPOINTS,
    ERROR_AUTH,
    ERROR_CONNECTION
)

_LOGGER = logging.getLogger(__name__)

class ZenPlannerAuth:
    """Handle ZenPlanner authentication."""

    def __init__(self, email: str, password: str) -> None:
        """Initialize auth handler."""
        self.base_url = API_BASE_URL
        self.session = aiohttp.ClientSession()
        self.email = email
        self.password = password
        
        # Set up headers
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Origin': self.base_url,
            'Referer': f"{self.base_url}{API_ENDPOINTS['login']}"
        })

    async def login(self) -> bool:
        """Attempt to log into ZenPlanner."""
        try:
            _LOGGER.debug("Starting login sequence")
            
            # 1. Initial login page request
            login_url = f"{self.base_url}{API_ENDPOINTS['login']}"
            params = {
                "VIEW": "login",
                "LOGOUT": "false",
                "message": "multiProfile"
            }
            
            async with self.session.get(login_url, params=params) as response:
                if not response.ok:
                    _LOGGER.error("Failed to get login page: %s", response.status)
                    raise ConnectionError(ERROR_CONNECTION)
                content = await response.text()
            
            # 2. Parse token
            soup = BeautifulSoup(content, 'html.parser')
            token_input = soup.find('input', {'name': '__xsToken'})
            token = token_input.get('value', '') if token_input else ''
            
            # 3. Submit login
            login_data = {
                "username": self.email,
                "password": self.password,
                "__xsToken": token,
                "NOVALIDATE": "true"
            }
            
            # Add form headers
            self.session.headers.update({
                'Content-Type': 'application/x-www-form-urlencoded',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache'
            })
            
            login_url_full = f"{login_url}?VIEW=login&LOGOUT=false&message=multiProfile"
            async with self.session.post(login_url_full, data=login_data) as login_response:
                if 'person.cfm' in str(login_response.url):
                    _LOGGER.debug("Login successful")
                    return True
                
            _LOGGER.error("Login failed - wrong redirect")
            raise ValueError(ERROR_AUTH)

        except Exception as err:
            _LOGGER.error("Login error: %s", str(err))
            return False

    async def is_logged_in(self) -> bool:
        """Check if session is still valid."""
        try:
            async with self.session.get(f"{self.base_url}/person.cfm") as response:
                return response.ok and 'login.cfm' not in str(response.url)
        except Exception as err:
            _LOGGER.error("Session check error: %s", str(err))
            return False

    @property
    def requests_session(self) -> aiohttp.ClientSession:
        """Access the underlying requests session."""
        return self.session