"""
Personalized DM alerts for subscribed users.
Called after new jobs are sent to the group, sends matching jobs to subscribers via DM.
"""

import logging
from telegram import Bot
from telegram.error import TelegramError

from core import db
from core.models import Job
from bot.sender import format_job_message
from bot.keyboards import job_buttons

log = logging.getLogger(__name__)

# Rate limit: max DMs per user per hour
MAX_DMS_PER_USER_PER_HOUR = 20


def _job_matches_subscription(job: Job, subs: dict) -> bool:
    """Check if a job matches a user's subscription filters."""
    if not subs:
        return False

    # Check topics
    sub_topics = set(subs.get("topics", []))
    if sub_topics and not sub_topics.intersection(set(job.topics)):
        return False

    # Check seniority
    sub_seniority = subs.get("seniority", [])
    if sub_seniority and job.seniority not in sub_seniority:
        return False

    # Check keywords
    sub_keywords = subs.get("keywords", [])
    if sub_keywords:
        title_lower = job.title.lower()
        if not any(kw.lower() in title_lower for kw in sub_keywords):
            return False

    # Check min salary
    min_salary = subs.get("min_salary")
    if min_salary and job.salary_max and job.salary_max < min_salary:
        return False

    return True


async def notify_subscribers(bot: Bot, jobs: list[tuple[Job, int]]) -> int:
    """
    Send DM alerts to subscribed users for matching jobs.

    Args:
        bot: Telegram Bot instance
        jobs: List of (Job, db_id) tuples

    Returns: Total DMs sent
    """
    # Get all users with subscriptions and notify_dm=True
    try:
        users = db._fetchall(
            "SELECT * FROM users WHERE notify_dm = TRUE AND subscriptions != '{}'"
        )
    except Exception as e:
        log.error(f"Failed to fetch subscribers: {e}")
        return 0

    total_sent = 0

    for user_row in users:
        subs = user_row.get("subscriptions", {})
        telegram_id = user_row["telegram_id"]
        dm_count = 0

        for job, db_id in jobs:
            if dm_count >= MAX_DMS_PER_USER_PER_HOUR:
                log.info(f"Rate limit hit for user {telegram_id}")
                break

            if not _job_matches_subscription(job, subs):
                continue

            try:
                msg = format_job_message(job)
                await bot.send_message(
                    chat_id=telegram_id,
                    text=f"🔔 New matching job:\n\n{msg}",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=job_buttons(db_id),
                )
                dm_count += 1
                total_sent += 1
            except TelegramError as e:
                if "bot was blocked" in str(e).lower() or "user not found" in str(e).lower():
                    # User blocked the bot or deleted account — disable notifications
                    db._execute(
                        "UPDATE users SET notify_dm = FALSE WHERE telegram_id = %s",
                        (telegram_id,),
                    )
                    log.info(f"Disabled DMs for user {telegram_id}: {e}")
                    break
                else:
                    log.warning(f"DM failed for {telegram_id}: {e}")

    log.info(f"📬 Sent {total_sent} DM alerts to {len(users)} subscribers")
    return total_sent
