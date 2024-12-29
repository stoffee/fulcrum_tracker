import requests
from bs4 import BeautifulSoup
import json
import logging

class ZenPlannerAuth:
    def __init__(self, email, password):
        self.base_url = "https://fulcrum.sites.zenplanner.com"
        self.session = requests.Session()
        self.email = email
        self.password = password
        
        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(message)s'  # Simplified format for cleaner output
        )
        self.logger = logging.getLogger(__name__)
        
        # Set up exact headers that work
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Origin': self.base_url,
            'Referer': f"{self.base_url}/login.cfm"
        })

    def login(self):
        """Attempt to log into ZenPlanner using exact working parameters"""
        try:
            self.logger.info("\n📝 Starting login sequence...")
            
            # 1. Initial login page request with exact parameters
            login_url = f"{self.base_url}/login.cfm"
            params = {
                "VIEW": "login",
                "LOGOUT": "false",
                "message": "multiProfile"
            }
            
            self.logger.info(f"Getting login page with params: {params}")
            response = self.session.get(login_url, params=params)
            self.logger.debug(f"Login page status: {response.status_code}")
            
            if not response.ok:
                raise Exception(f"Failed to get login page: {response.status_code}")
            
            # 2. Parse the page and get the token
            soup = BeautifulSoup(response.text, 'html.parser')
            token_input = soup.find('input', {'name': '__xsToken'})
            
            token = token_input.get('value', '') if token_input else ''
            if token:
                self.logger.debug(f"Found token: {token[:10]}...")
            else:
                self.logger.debug("No token found (this might be ok for initial redirect)")
            
            # 3. Submit login with exact matching form data
            login_data = {
                "username": self.email,
                "password": self.password,
                "__xsToken": token,
                "NOVALIDATE": "true"
            }
            
            # Add form-specific headers
            self.session.headers.update({
                'Content-Type': 'application/x-www-form-urlencoded',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache'
            })
            
            # Use exact URL with parameters
            login_url_full = f"{login_url}?VIEW=login&LOGOUT=false&message=multiProfile"
            self.logger.info(f"\nSubmitting login to: {login_url_full}")
            
            login_response = self.session.post(
                login_url_full,
                data=login_data,
                allow_redirects=True
            )
            
            self.logger.info(f"Login response status: {login_response.status_code}")
            self.logger.info(f"Final URL: {login_response.url}")
            
            # Check if we landed on the person page (success) or still on login page (failure)
            if 'person.cfm' in login_response.url:
                self.logger.info("\n✅ Login successful! 🎉")
                return True
            else:
                self.logger.error("\n❌ Login failed - redirected to wrong page")
                return False

        except Exception as e:
            self.logger.error(f"\n❌ Error during login: {str(e)}")
            return False

    def is_logged_in(self):
        """Check if we're still logged in"""
        try:
            response = self.session.get(f"{self.base_url}/person.cfm")
            return response.ok and 'login.cfm' not in response.url
        except:
            return False

    @property
    def requests_session(self):
        """Provide access to the underlying requests session"""
        return self.session

if __name__ == "__main__":
    # Example usage
    from old_app.config import ZENPLANNER_EMAIL, ZENPLANNER_PASSWORD
    zp = ZenPlannerAuth(ZENPLANNER_EMAIL, ZENPLANNER_PASSWORD)
    if zp.login():
        print("\n🎯 Ready to fetch some classes! 💪")
    else:
        print("\n😢 Login failed - check the messages above")
