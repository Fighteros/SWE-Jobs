
import sys
import os

# Add the project root to sys.path to import core modules
sys.path.append(os.getcwd())

from core import db

def check_db():
    print("Checking database...")
    try:
        # Check if users table exists
        users = db._fetchall("SELECT COUNT(*) FROM users")
        print(f"Users count: {users[0]['count']}")
        
        # Check if user_alerts table exists
        try:
            alerts = db._fetchall("SELECT COUNT(*) FROM user_alerts")
            print(f"User alerts count: {alerts[0]['count']}")
            
            # Sample alerts
            all_alerts = db._fetchall("SELECT * FROM user_alerts LIMIT 5")
            print(f"Sample alerts: {all_alerts}")
        except Exception as e:
            print(f"Error accessing user_alerts: {e}")
            
    except Exception as e:
        print(f"Error connecting to DB: {e}")

if __name__ == "__main__":
    check_db()
