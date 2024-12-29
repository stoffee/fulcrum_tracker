import requests
import json
from datetime import datetime
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs

class ZenPlannerExact:
    def __init__(self):
        self.base_url = "https://fulcrum.sites.zenplanner.com"
        self.person_id = "E28E53AA-CE35-4958-9B3F-C46584509E03"
        self.session = requests.Session()
        
        # Match browser headers exactly
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Origin': self.base_url,
            'Referer': f"{self.base_url}/login.cfm"
        })

    def do_login(self, username, password):
        """Perform exact login sequence matching the form"""
        print("\nStarting login sequence...")
        
        # 1. Get login page with exact parameters
        login_url = f"{self.base_url}/login.cfm"
        params = {
            "VIEW": "login",
            "LOGOUT": "false",
            "message": "multiProfile"
        }
        
        print(f"\nGetting login page with params: {params}")
        response = self.session.get(login_url, params=params)
        print(f"Login page status: {response.status_code}")
        
        if response.ok:
            # Parse the page
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find the token
            token_input = soup.find('input', {'name': '__xsToken'})
            if token_input:
                token = token_input.get('value', '')
                print(f"Found token: {token}")
            else:
                print("No token found!")
                token = ''
            
            # 2. Build login data exactly matching form
            login_data = {
                "username": username,
                "password": password,
                "__xsToken": token,
                "NOVALIDATE": "true"
            }
            
            # 3. Submit the form to exact URL
            login_url_full = f"{login_url}?VIEW=login&LOGOUT=false&message=multiProfile"
            print(f"\nSubmitting login to: {login_url_full}")
            
            # Set form-specific headers
            self.session.headers.update({
                'Content-Type': 'application/x-www-form-urlencoded',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache'
            })
            
            login_response = self.session.post(
                login_url_full,
                data=login_data,
                allow_redirects=True
            )
            
            print(f"Login response status: {login_response.status_code}")
            print(f"Final URL: {login_response.url}")
            
            if login_response.ok:
                # Now try to get attendance data
                return self.get_attendance_data()
                
        return False

    def get_attendance_data(self):
        """Get attendance data after login"""
        print("\nFetching attendance data...")
        
        attendance_url = f"{self.base_url}/person-attendance.cfm"
        params = {"personId": self.person_id}
        
        response = self.session.get(attendance_url, params=params)
        print(f"Attendance page status: {response.status_code}")
        
        if response.ok:
            # Look for the attendance table
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # First try to find the graph data
            script_tags = soup.find_all('script')
            for script in script_tags:
                if script.string and 'var chartData' in script.string:
                    print("Found chart data!")
                    # Extract and parse the data
                    match = re.search(r'var\s+chartData\s*=\s*(\[.+?\]);', script.string, re.DOTALL)
                    if match:
                        try:
                            chart_data = json.loads(match.group(1))
                            print(f"Parsed chart data: {len(chart_data)} months")
                            
                            # Save the graph data
                            with open("attendance_graph.json", "w") as f:
                                json.dump(chart_data, f, indent=2)
                                
                        except json.JSONDecodeError as e:
                            print(f"Error parsing chart data: {e}")
            
            # Now get the table data
            table = soup.find('table', {'class': 'table'})
            if table:
                sessions = []
                rows = table.find_all('tr')[1:]  # Skip header
                
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 3:
                        session = {
                            'date': cells[0].get_text(strip=True),
                            'time': cells[1].get_text(strip=True),
                            'event': cells[2].get_text(strip=True)
                        }
                        sessions.append(session)
                
                print(f"\nFound {len(sessions)} sessions")
                
                # Save the full data
                attendance_data = {
                    'total_sessions': len(sessions),
                    'sessions': sessions
                }
                
                with open("attendance_full.json", "w") as f:
                    json.dump(attendance_data, f, indent=2)
                    
                print("\nData saved to attendance_full.json and attendance_graph.json")
                return True
                
            else:
                print("No attendance table found!")
                
        return False

def main():
    print("Starting ZenPlanner attendance capture...")
    zp = ZenPlannerExact()
    
    success = zp.do_login("chris@roadkill.org", "AJenOTISerOG")
    
    if success:
        print("\nProcess completed successfully!")
    else:
        print("\nProcess failed - check output above for details")

if __name__ == "__main__":
    main()
