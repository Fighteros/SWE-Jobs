"""
One-off script: send a "How to use this bot" tutorial message to #general.

Usage:
    python scripts/send_tutorial.py
    python scripts/send_tutorial.py --topic backend   # send to a different topic
    python scripts/send_tutorial.py --dry-run          # preview without sending
"""

import argparse
import asyncio
import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram import Bot
from core.config import TELEGRAM_BOT_TOKEN, TELEGRAM_GROUP_ID
from core.channels import get_topic_thread_id

TUTORIAL_MESSAGE = """\
👋 <b>Welcome to the Programming Jobs Bot!</b>

Here's everything you need to get started:

━━━━━━━━━━━━━━━━━━━━

🔔 <b>Get Personalized Alerts</b>
/subscribe — Pick your topics (Backend, Frontend, AI/ML…), seniority level, location, and sources. You'll get DM alerts for matching jobs!

📋 <b>Browse & Search</b>
/search <i>&lt;keywords&gt;</i> — Search jobs (e.g. <code>/search python remote</code>)
/top — See the top jobs this week
/salary — Salary insights across roles

💾 <b>Save & Track</b>
Tap <b>💾 Save</b> on any job post to bookmark it
Tap <b>✅ Applied</b> when you apply
/saved — View your saved jobs
/applied — View your application history

🔥 <b>Stay Motivated</b>
/streak — Track your daily application streak

🚫 <b>Filter Out Noise</b>
/blacklist — Block companies or keywords you don't want to see

📬 <b>Manage Subscriptions</b>
/mysubs — View your current filters
/unsubscribe — Remove all subscriptions

💬 <b>Need Help?</b>
/contact — Send a message to the bot owner
/help — See all commands

━━━━━━━━━━━━━━━━━━━━

💡 <b>Tip:</b> Start with /subscribe to set up your alerts — you'll never miss a matching job again!
"""


async def main(topic: str, dry_run: bool) -> None:
    if dry_run:
        print("=== DRY RUN — Message preview ===\n")
        print(TUTORIAL_MESSAGE)
        print(f"\nWould send to topic: {topic}")
        return

    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)
    if not TELEGRAM_GROUP_ID:
        print("ERROR: TELEGRAM_GROUP_ID not set in .env")
        sys.exit(1)

    thread_id = get_topic_thread_id(topic)
    if thread_id is None:
        print(f"ERROR: Topic '{topic}' has no thread_id configured (check env var)")
        sys.exit(1)

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    async with bot:
        result = await bot.send_message(
            chat_id=TELEGRAM_GROUP_ID,
            message_thread_id=thread_id,
            text=TUTORIAL_MESSAGE,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        print(f"✅ Tutorial sent to #{topic} (message_id: {result.message_id})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send tutorial message to a Telegram topic")
    parser.add_argument("--topic", default="general", help="Topic key (default: general)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending")
    args = parser.parse_args()
    asyncio.run(main(args.topic, args.dry_run))
