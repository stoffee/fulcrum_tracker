from zenplanner_auth import ZenPlannerAuth
from config import ZENPLANNER_EMAIL, ZENPLANNER_PASSWORD
import logging

def test_login():
    print("\n🚀 Starting ZenPlanner login test...\n")
    
    # Create auth instance
    zp = ZenPlannerAuth(ZENPLANNER_EMAIL, ZENPLANNER_PASSWORD)
    
    # Try to login
    print("📝 Attempting login...")
    if zp.login():
        print("\n✅ Login successful!")
        
        # Verify we're still logged in
        print("\n🔍 Verifying session...")
        if zp.is_logged_in():
            print("✅ Session verification successful!")
        else:
            print("❌ Session verification failed!")
    else:
        print("\n❌ Login failed!")
        print("\nCheck the logs above for detailed error information!")
        print("\nCommon issues:")
        print("1. Incorrect email/password")
        print("2. Network connectivity problems")
        print("3. ZenPlanner website changes")

if __name__ == "__main__":
    test_login()
