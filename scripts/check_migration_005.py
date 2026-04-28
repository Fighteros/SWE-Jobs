
import sys
import os

# Add the project root to sys.path to import core modules
sys.path.append(os.getcwd())

from core import db

def check_migration():
    print("🔍 Checking database for Migration 005 (user_alerts)...")
    
    # 1. Check if user_alerts table exists
    try:
        db._fetchall("SELECT id FROM user_alerts LIMIT 1")
        print("✅ user_alerts table exists.")
    except Exception as e:
        if "undefined_table" in str(e).lower() or "does not exist" in str(e).lower():
            print("❌ user_alerts table is MISSING.")
            print("\nSUGGESTION: Please run the migration 'supabase/migrations/005_user_alerts.sql' in your Supabase SQL editor.")
            return
        else:
            print(f"⚠️ Error checking table: {e}")
            return

    # 2. Check alerts count
    try:
        res = db._fetchone("SELECT COUNT(*) as count FROM user_alerts")
        count = res['count']
        print(f"📊 Current alerts in DB: {count}")
        
        if count == 0:
            print("⚠️ The table is empty. This might be why you are not receiving alerts.")
            
            # Check if there are users with old subscriptions that weren't migrated
            try:
                users_with_subs = db._fetchall("SELECT id FROM users WHERE subscriptions IS NOT NULL AND subscriptions <> '{}'::jsonb")
                if users_with_subs:
                    print(f"💡 Found {len(users_with_subs)} users with legacy subscriptions that have NOT been migrated to user_alerts.")
                    print("SUGGESTION: The data migration part of 005_user_alerts.sql might have skipped these users if they already had a position=1 alert, or if it wasn't run.")
            except Exception as e:
                print(f"Error checking legacy subs: {e}")
    except Exception as e:
        print(f"Error counting alerts: {e}")

    # 3. Check for specific user (if telegram_id provided)
    if len(sys.argv) > 1:
        try:
            tid = int(sys.argv[1])
            user = db._fetchone("SELECT id, notify_dm FROM users WHERE telegram_id = %s", (tid,))
            if not user:
                print(f"❌ User with Telegram ID {tid} not found in DB.")
            else:
                uid = user['id']
                print(f"👤 User found: ID={uid}, notify_dm={user['notify_dm']}")
                alerts = db.get_user_alerts(uid)
                print(f"🔔 Alerts for this user: {len(alerts)}")
                for a in alerts:
                    print(f"   #{a['position']}: topics={a['topics']}, dm_enabled={a['dm_enabled']}")
        except ValueError:
            print("Usage: python scripts/check_migration_005.py [telegram_id]")

if __name__ == "__main__":
    check_migration()
