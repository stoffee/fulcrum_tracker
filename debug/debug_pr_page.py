from zenplanner_auth import ZenPlannerAuth
from config import ZENPLANNER_EMAIL, ZENPLANNER_PASSWORD
import json
from datetime import datetime
import time

def dump_pr_page():
    """
    Fetch and dump the PR page content for debugging.
    Saves both raw HTML and a prettier formatted version for analysis.
    """
    print("\n🔍 Starting PR page debug dump...")

    # Initialize auth
    auth = ZenPlannerAuth(ZENPLANNER_EMAIL, ZENPLANNER_PASSWORD)
    
    if not auth.login():
        print("\n❌ Login failed!")
        return

    # Get the PR page
    url = "https://fulcrum.sites.zenplanner.com/workout-pr-page.cfm"
    print(f"\n📑 Fetching PR page: {url}")
    
    try:
        response = auth.requests_session.get(url)
        
        if not response.ok:
            print(f"❌ Failed to fetch PR page: {response.status_code}")
            return

        # Save raw HTML
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        raw_filename = f'pr_page_raw_{timestamp}.html'
        
        with open(raw_filename, 'w', encoding='utf-8') as f:
            f.write(response.text)
            
        print(f"\n💾 Saved raw HTML to: {raw_filename}")
        
        # Also save headers and response info for debugging
        debug_info = {
            'url': url,
            'status_code': response.status_code,
            'headers': dict(response.headers),
            'cookies': dict(response.cookies),
            'encoding': response.encoding,
            'timestamp': datetime.now().isoformat()
        }
        
        debug_filename = f'pr_page_debug_{timestamp}.json'
        with open(debug_filename, 'w') as f:
            json.dump(debug_info, f, indent=2)
            
        print(f"📊 Saved debug info to: {debug_filename}")
        
        # Print the first 500 characters to give a quick peek
        print("\n👀 First 500 characters of response:")
        print("-" * 80)
        print(response.text[:500])
        print("-" * 80)
        
        return raw_filename, debug_filename
        
    except Exception as e:
        print(f"\n❌ Error fetching PR page: {str(e)}")
        return None

if __name__ == "__main__":
    results = dump_pr_page()
    if results:
        raw_file, debug_file = results
        print(f"\n✨ All done! Check {raw_file} and {debug_file} for the complete data!")
    else:
        print("\n😢 Failed to fetch PR data")
