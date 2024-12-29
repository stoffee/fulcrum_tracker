from zenplanner_auth import ZenPlannerAuth
from config import ZENPLANNER_EMAIL, ZENPLANNER_PASSWORD
import re
from datetime import datetime

class PRFetcher:
    def __init__(self):
        """Initialize PR fetcher with authentication"""
        self.auth = ZenPlannerAuth(ZENPLANNER_EMAIL, ZENPLANNER_PASSWORD)
        self.user_id = 'E28E53AA-CE35-4958-9B3F-C46584509E03'  # Your user ID
        
    def fetch_prs(self):
        """Fetch PR page and extract data in human readable format"""
        print("\n🔒 Logging in to ZenPlanner...")
        if not self.auth.login():
            print("❌ Login failed!")
            return None

        print("\n📡 Fetching PR page...")
        url = "https://fulcrum.sites.zenplanner.com/workout-pr-page.cfm"
        response = self.auth.requests_session.get(url)
        
        if not response.ok:
            print(f"❌ Failed to fetch PR page: {response.status_code}")
            return None

        content = response.text
        print("✅ Got PR page successfully!")
        print(f"Page size: {len(content)} characters")

        # Find the personResults.resultSet data
        print("\n🔍 Looking for PR data...")
        data_match = re.search(r'personResults\.resultSet\s*=\s*\[(.*?)\];', 
                             content, re.DOTALL)
        
        if not data_match:
            print("❌ Couldn't find PR data in page")
            return None

        data = data_match.group(1)
        print(f"Found PR data section ({len(data)} characters)")

        # Find all PR entries
        print("\n🏋️ Finding your PRs...")
        entries = list(re.finditer(r'{[^}]*personid\s*:\s*["\']?E28E53AA[^}]+}', data))
        print(f"Found {len(entries)} PR entries")

        # Use a dictionary to deduplicate
        pr_dict = {}
        for entry in entries:
            entry_text = entry.group(0)
            
            # Extract fields using regex
            name = re.search(r'skillname:\s*["\']([^"\']+)["\']', entry_text)
            pr = re.search(r'pr:\s*["\']([^"\']+)["\']', entry_text)
            last = re.search(r'lastresult:\s*["\']([^"\']+)["\']', entry_text)
            days = re.search(r'dayssince:\s*["\']([^"\']+)["\']', entry_text)
            tries = re.search(r'tries:\s*["\']([^"\']+)["\']', entry_text)
            
            if name and pr:
                pr_data = {
                    'name': name.group(1),
                    'pr': pr.group(1) if pr else '',
                    'last': last.group(1) if last else '',
                    'days': days.group(1) if days else '',
                    'tries': tries.group(1) if tries else ''
                }
                # Use name as key to deduplicate
                key = f"{name.group(1)}_{pr.group(1)}"
                pr_dict[key] = pr_data

        # Convert back to list and sort
        prs = list(pr_dict.values())
        prs.sort(key=lambda x: x['name'])
        
        print(f"Found {len(prs)} unique PRs")
        return prs

def format_pr(pr):
    """Format a PR for display with some stats"""
    output = []
    output.append(f"🏋️ {pr['name']}")
    output.append(f"   PR: {pr['pr']}")
    
    if pr['last']:
        if pr['last'] == pr['pr']:
            output.append(f"   Last: {pr['last']} 🎯")  # Hit PR
        else:
            output.append(f"   Last: {pr['last']}")
    
    if pr['days']:
        days = int(pr['days'])
        if days < 7:
            output.append(f"   Days since: {days} 🔥")  # Recent activity
        elif days > 90:
            output.append(f"   Days since: {days} 💤")  # Inactive
        else:
            output.append(f"   Days since: {days}")
            
    if pr['tries']:
        tries = int(pr['tries'])
        if tries > 20:
            output.append(f"   Total attempts: {tries} 💪")  # Frequently practiced
        else:
            output.append(f"   Total attempts: {tries}")
            
    return "\n".join(output)

def main():
    print("\n🏋️‍♂️ Starting PR data fetch...")
    
    fetcher = PRFetcher()
    prs = fetcher.fetch_prs()
    
    if prs:
        print("\n💪 Your PRs:")
        print("-" * 80)
        print(f"Total unique PRs found: {len(prs)}")
        print("-" * 80)
        
        for pr in prs:
            print(f"\n{format_pr(pr)}")
            
        # Print some stats
        print("\n📊 Quick Stats:")
        print("-" * 40)
        active_prs = sum(1 for pr in prs if int(pr['days']) < 30)
        inactive_prs = sum(1 for pr in prs if int(pr['days']) > 90)
        recent_prs = sum(1 for pr in prs if pr['last'] == pr['pr'])
        
        print(f"Active exercises (last 30 days): {active_prs}")
        print(f"Need attention (90+ days): {inactive_prs}")
        print(f"Recent PRs: {recent_prs}")
        
    else:
        print("\n😢 Failed to fetch PR data")

if __name__ == "__main__":
    main()