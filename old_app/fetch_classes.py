from custom_components.fulcrum_tracker.zenplanner_auth import ZenPlannerAuth
from config import ZENPLANNER_EMAIL, ZENPLANNER_PASSWORD
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import json
import time

class ZenPlannerCalendar:
    def __init__(self, auth):
        self.auth = auth
        self.session = auth.requests_session
        self.base_url = "https://fulcrum.sites.zenplanner.com/workouts.cfm"
        
    def fetch_month(self, start_date):
        """Fetch a specific month's data"""
        url = f"{self.base_url}?&startdate={start_date.strftime('%Y-%m-%d')}"
        current_date = datetime.now()
        
        print(f"\n📅 Fetching month: {start_date.strftime('%B %Y')}")
        print(f"URL: {url}")
        
        response = self.session.get(url)
        
        if not response.ok:
            print(f"❌ Failed to fetch month: {response.status_code}")
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
                print(f"Skipping future date: {date_str}")
                continue
                    
            if attended:
                day_data = {
                    'date': date_str,
                    'attended': attended,
                    'has_results': has_results,
                    'is_pr': is_pr,
                    'details': day.get('tooltiptext', '').strip(),
                    'month_year': day_date.strftime('%B %Y')
                }
                month_data.append(day_data)
                    
        return month_data

    def fetch_all_history(self, start_date):
        """Fetch all history from start date to now"""
        all_data = []
        current_date = datetime.now()
        fetch_date = start_date.replace(day=1)  # Start at beginning of month
        
        print("\n📆 Starting historical fetch...")
        print(f"From: {start_date.strftime('%B %Y')}")
        print(f"To: {current_date.strftime('%B %Y')}")
        
        # Calculate total months for progress tracking
        total_months = ((current_date.year - start_date.year) * 12 + 
                       current_date.month - start_date.month)
        months_processed = 0
        
        while fetch_date.date() <= current_date.date():
            print(f"\n🔄 Fetching {fetch_date.strftime('%B %Y')}... ({months_processed}/{total_months} months)")
            
            # First try with current date
            month_data = self.fetch_month(fetch_date)
            
            if month_data:
                print(f"✅ Found {len(month_data)} sessions")
                all_data.extend(month_data)
            else:
                print(f"ℹ️ No sessions found for {fetch_date.strftime('%B %Y')}")
            
            # Move to next month
            months_processed += 1
            
            # Try getting the next month's date from the navigation link first
            response = self.session.get(f"{self.base_url}?&startdate={fetch_date.strftime('%Y-%m-%d')}")
            soup = BeautifulSoup(response.text, 'html.parser')
            next_link = soup.find('a', class_='next')
            
            if next_link:
                next_date_str = next_link['href'].split('startdate=')[-1]
                try:
                    fetch_date = datetime.strptime(next_date_str, '%Y-%m-%d')
                    print(f"Next month from link: {fetch_date.strftime('%B %Y')}")
                except:
                    # Fallback to manual date increment if link parsing fails
                    if fetch_date.month == 12:
                        fetch_date = datetime(fetch_date.year + 1, 1, 1)
                    else:
                        fetch_date = fetch_date.replace(month=fetch_date.month + 1)
            else:
                # Manual date increment if no next link found
                if fetch_date.month == 12:
                    fetch_date = datetime(fetch_date.year + 1, 1, 1)
                else:
                    fetch_date = fetch_date.replace(month=fetch_date.month + 1)
            
            print(f"  Next fetch date will be: {fetch_date.strftime('%Y-%m-%d')}")
            
            # Be nice to their servers
            time.sleep(2)
            
        return all_data

def main():
    print("\n🚀 Starting calendar history fetch...")
    
    auth = ZenPlannerAuth(ZENPLANNER_EMAIL, ZENPLANNER_PASSWORD)
    if auth.login():
        cal = ZenPlannerCalendar(auth)
        
        # Start from November 2021
        start_date = datetime(2021, 11, 1)
        #start_date = datetime(2024, 1, 1)
        history = cal.fetch_all_history(start_date)
        
        # Sort sessions chronologically
        history.sort(key=lambda x: datetime.strptime(x['date'], '%Y-%m-%d'))
        
        # Save the data
        data = {
            'total_sessions': len(history),
            'sessions': history
        }
        
        with open('training_history.json', 'w') as f:
            json.dump(data, f, indent=2)
            
        print(f"\n✨ Saved {len(history)} sessions to training_history.json!")
        
        # Show some stats
        attended = len([s for s in history if s['attended']])
        results = len([s for s in history if s['has_results']])
        prs = len([s for s in history if s['is_pr']])
        
        print(f"\n📊 Training Stats:")
        print(f"Total Sessions: {attended}")
        print(f"Results Logged: {results} ({results/attended*100:.1f}%)")
        print(f"PRs Set: {prs}")
        
        # Monthly breakdown
        months = {}
        for session in history:
            month = session['month_year']
            months[month] = months.get(month, 0) + 1
            
        print("\n📅 Monthly Attendance:")
        for month, count in sorted(months.items()):
            print(f"{month}: {count} sessions")
        
    else:
        print("\n❌ Login failed - can't fetch history")

if __name__ == "__main__":
    main()