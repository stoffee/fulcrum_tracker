"""ZenPlanner authentication handler with enhanced error handling and retry logic."""
import asyncio
import logging
from typing import Optional
from enum import Enum
import aiohttp
from bs4 import BeautifulSoup

from ..const import (
    API_BASE_URL,
    API_ENDPOINTS,
    ERROR_AUTH,
    ERROR_CONNECTION
)

_LOGGER = logging.getLogger(__name__)

class AuthError(Exception):
    """Base exception for authentication errors."""
    pass

class NetworkError(AuthError):
    """Network-related authentication error."""
    pass

class InvalidCredentialsError(AuthError):
    """Invalid username/password error."""
    pass

class ServerError(AuthError):
    """ZenPlanner server error."""
    pass

class RateLimitError(AuthError):
    """Too many requests error."""
    pass

class SessionExpiredError(AuthError):
    """Session has expired error."""
    pass

class AuthStatus(Enum):
    """Authentication status enum for better state tracking."""
    NOT_AUTHENTICATED = "not_authenticated"
    AUTHENTICATING = "authenticating"
    AUTHENTICATED = "authenticated"
    EXPIRED = "expired"
    FAILED = "failed"

class ZenPlannerAuth:
    """Handle ZenPlanner authentication with enhanced error handling."""

    def __init__(self, email: str, password: str) -> None:
        """Initialize auth handler."""
        self.base_url = API_BASE_URL
        self.email = email
        self.password = password
        self._session: Optional[aiohttp.ClientSession] = None
        self._is_initialized = False
        self._auth_status = AuthStatus.NOT_AUTHENTICATED
        self._retry_count = 0
        self._max_retries = 3
        self._retry_delay = 1  # Base delay in seconds
        self._last_auth_attempt = None
        self._rate_limit_until = None

    @property
    def auth_status(self) -> AuthStatus:
        """Get current authentication status."""
        return self._auth_status

    @property
    async def requests_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            await self._initialize_session()
        return self._session

    async def _initialize_session(self) -> None:
        """Initialize session with default headers."""
        if not self._is_initialized:
            session = await self.requests_session
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Origin': self.base_url,
                'Referer': f"{self.base_url}{API_ENDPOINTS['login']}"
            })
            self._is_initialized = True

    async def login(self) -> bool:
        """Attempt to log into ZenPlanner with enhanced error handling and retry logic."""
        if await self._check_rate_limit():
            raise RateLimitError("Rate limit exceeded. Please wait before retrying.")

        for attempt in range(self._max_retries + 1):
            try:
                self._auth_status = AuthStatus.AUTHENTICATING
                _LOGGER.debug("🔐 Starting login attempt %d/%d", attempt + 1, self._max_retries + 1)
                
                # 1. Get login page and extract token
                token = await self._get_login_token()
                
                # 2. Submit login credentials
                success = await self._submit_login_credentials(token)
                
                if success:
                    self._auth_status = AuthStatus.AUTHENTICATED
                    self._retry_count = 0
                    _LOGGER.info("✅ Authentication successful")
                    return True
                else:
                    self._auth_status = AuthStatus.FAILED
                    raise InvalidCredentialsError("Login failed - invalid credentials")
                    
            except (NetworkError, aiohttp.ClientError, asyncio.TimeoutError) as err:
                if attempt < self._max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    _LOGGER.warning(
                        "🔄 Network error on attempt %d/%d, retrying in %ds: %s", 
                        attempt + 1, self._max_retries + 1, delay, str(err)
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    self._auth_status = AuthStatus.FAILED
                    _LOGGER.error("❌ All login attempts failed due to network issues")
                    raise NetworkError(f"Network error after {self._max_retries} retries: {str(err)}")
                    
            except InvalidCredentialsError:
                self._auth_status = AuthStatus.FAILED
                _LOGGER.error("❌ Invalid credentials provided")
                raise
                
            except ServerError as err:
                if attempt < self._max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    _LOGGER.warning(
                        "🔄 Server error on attempt %d/%d, retrying in %ds: %s", 
                        attempt + 1, self._max_retries + 1, delay, str(err)
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    self._auth_status = AuthStatus.FAILED
                    _LOGGER.error("❌ Server error after %d attempts", self._max_retries)
                    raise
                    
            except Exception as err:
                self._auth_status = AuthStatus.FAILED
                _LOGGER.error("❌ Unexpected error during login: %s", str(err))
                raise AuthError(f"Unexpected authentication error: {str(err)}")
        
        self._auth_status = AuthStatus.FAILED
        return False

    async def _get_login_token(self) -> str:
        """Get login token from the login page with enhanced error handling."""
        login_url = f"{self.base_url}{API_ENDPOINTS['login']}"
        params = {
            "VIEW": "login",
            "LOGOUT": "false",
            "message": "multiProfile"
        }
        
        try:
            session = await self.requests_session
            async with session.get(
                login_url, 
                params=params, 
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                
                if response.status == 429:
                    raise RateLimitError("Rate limited by server")
                elif response.status >= 500:
                    raise ServerError(f"Server error: {response.status}")
                elif response.status >= 400:
                    raise NetworkError(f"Client error: {response.status}")
                elif response.status != 200:
                    raise NetworkError(f"Unexpected status: {response.status}")
                    
                content = await response.text()
                
        except asyncio.TimeoutError:
            raise NetworkError("Timeout while fetching login page")
        except aiohttp.ClientError as err:
            raise NetworkError(f"Network error fetching login page: {str(err)}")
        
        # Parse token with better error handling
        try:
            soup = BeautifulSoup(content, 'html.parser')
            token_input = soup.find('input', {'name': '__xsToken'})
            
            if not token_input:
                raise ServerError("No security token found in login page")
                
            token = token_input.get('value', '')
            if not token:
                raise ServerError("Empty security token received")
                
            _LOGGER.debug("🔑 Security token extracted successfully")
            return token
            
        except Exception as err:
            raise ServerError(f"Failed to parse login page: {str(err)}")

    async def _submit_login_credentials(self, token: str) -> bool:
        """Submit login credentials with enhanced error handling."""
        login_url = f"{self.base_url}{API_ENDPOINTS['login']}"
        login_data = {
            "username": self.email,
            "password": self.password,
            "__xsToken": token,
            "NOVALIDATE": "true"
        }
        
        # Add form headers
        session = await self.requests_session
        session.headers.update({
            'Content-Type': 'application/x-www-form-urlencoded',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        })
        
        login_url_full = f"{login_url}?VIEW=login&LOGOUT=false&message=multiProfile"
        
        try:
            async with session.post(
                login_url_full, 
                data=login_data,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as login_response:
                
                if login_response.status == 429:
                    raise RateLimitError("Rate limited during login")
                elif login_response.status >= 500:
                    raise ServerError(f"Server error during login: {login_response.status}")
                elif login_response.status >= 400:
                    raise NetworkError(f"Client error during login: {login_response.status}")
                
                # Check for successful login by URL redirect
                if 'person.cfm' in str(login_response.url):
                    _LOGGER.debug("✅ Login successful - redirected to person.cfm")
                    return True
                else:
                    # Check response content for more specific error
                    response_text = await login_response.text()
                    if 'invalid' in response_text.lower() or 'error' in response_text.lower():
                        raise InvalidCredentialsError("Invalid username or password")
                    else:
                        _LOGGER.debug("🔍 Login response: %s", response_text[:200])
                        raise ServerError("Unexpected login response")
                        
        except asyncio.TimeoutError:
            raise NetworkError("Timeout during login submission")
        except aiohttp.ClientError as err:
            raise NetworkError(f"Network error during login: {str(err)}")

    async def is_logged_in(self) -> bool:
        """Check if session is still valid with enhanced error handling."""
        if self._auth_status != AuthStatus.AUTHENTICATED:
            return False
            
        try:
            session = await self.requests_session
            async with session.get(
                f"{self.base_url}/person.cfm",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                
                if response.status == 401 or 'login.cfm' in str(response.url):
                    self._auth_status = AuthStatus.EXPIRED
                    _LOGGER.debug("🔄 Session expired - login required")
                    return False
                elif response.status == 429:
                    _LOGGER.warning("⚠️ Rate limited during session check")
                    # Don't change auth status for rate limits
                    return True
                elif response.ok:
                    _LOGGER.debug("✅ Session is valid")
                    return True
                else:
                    _LOGGER.warning("⚠️ Unexpected status during session check: %s", response.status)
                    return False
                    
        except asyncio.TimeoutError:
            _LOGGER.warning("⚠️ Timeout during session check")
            return False
        except Exception as err:
            _LOGGER.warning("⚠️ Error checking session: %s", str(err))
            return False

    async def ensure_authenticated(self) -> bool:
        """Ensure we're authenticated, re-authenticate if needed."""
        if await self.is_logged_in():
            return True
            
        _LOGGER.info("🔄 Session expired or invalid, re-authenticating...")
        try:
            return await self.login()
        except Exception as err:
            _LOGGER.error("❌ Re-authentication failed: %s", str(err))
            return False

    async def _check_rate_limit(self) -> bool:
        """Check if we're currently rate limited."""
        import time
        if self._rate_limit_until and time.time() < self._rate_limit_until:
            return True
        return False

    def _calculate_retry_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay."""
        # Exponential backoff: 1s, 2s, 4s, 8s...
        return self._retry_delay * (2 ** attempt)

    async def close(self) -> None:
        """Close the session with enhanced cleanup."""
        self._auth_status = AuthStatus.NOT_AUTHENTICATED
        
        if self._session and not self._session.closed:
            try:
                await self._session.close()
                _LOGGER.debug("🔒 Session closed successfully")
            except Exception as err:
                _LOGGER.warning("⚠️ Error closing session: %s", str(err))
            finally:
                self._session = None
                self._is_initialized = False

    def reset_retry_counter(self) -> None:
        """Reset retry counter after successful operation."""
        self._retry_count = 0

    @property
    def needs_authentication(self) -> bool:
        """Check if authentication is needed."""
        return self._auth_status in [
            AuthStatus.NOT_AUTHENTICATED, 
            AuthStatus.EXPIRED, 
            AuthStatus.FAILED
        ]