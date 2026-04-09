"""
Job message formatting and sending with inline buttons.
Replaces the old telegram_sender.py.
"""

import logging
from telegram import Bot
from telegram.error import TelegramError

from core.config import TELEGRAM_BOT_TOKEN, TELEGRAM_GROUP_ID, TELEGRAM_SEND_DELAY
from core.models import Job
from core.channels import CHANNELS, get_topic_thread_id
from core import db
from bot.keyboards import job_buttons

log = logging.getLogger(__name__)


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def format_job_message(job: Job) -> str:
    """Format a job as an HTML Telegram message."""
    emoji = job.emoji
    title = _escape_html(job.title)
    company = _escape_html(job.company) if job.company else "Unknown"
    location = _escape_html(job.location) if job.location else "Not specified"
    source = _escape_html(job.display_source)

    lines = [
        f"{emoji} <b>{title}</b>",
        f"🏢 {company}",
        f"📍 {location}",
    ]

    if job.salary_display:
        lines.append(f"💰 {_escape_html(job.salary_display)}")
    if job.seniority and job.seniority != "mid":
        seniority_labels = {
            "intern": "🎓 Intern", "junior": "🌱 Junior",
            "senior": "👨‍💻 Senior", "lead": "⭐ Lead",
            "executive": "🏛️ Executive",
        }
        label = seniority_labels.get(job.seniority, "")
        if label:
            lines.append(label)
    if job.job_type:
        lines.append(f"📋 {_escape_html(job.job_type)}")
    if job.is_remote:
        lines.append("🌍 Remote")

    lines.append("")
    lines.append(f'🔗 <a href="{job.url}">Apply Now</a>')
    lines.append(f"📡 Source: {source}")

    return "\n".join(lines)


async def send_job_to_topics(bot: Bot, job: Job, job_db_id: int) -> dict:
    """
    Send a job to all matching Telegram topics with inline buttons.

    Args:
        bot: Telegram Bot instance
        job: The job to send
        job_db_id: The job's database ID (for button callbacks)

    Returns: {topic_key: {"chat_id": ..., "message_id": ...}} for sent messages
    """
    message = format_job_message(job)
    keyboard = job_buttons(job_db_id)
    sent_messages = {}

    for topic_key in job.topics:
        thread_id = get_topic_thread_id(topic_key)
        if thread_id is None:
            continue

        topic_name = CHANNELS[topic_key]["name"]
        try:
            result = await bot.send_message(
                chat_id=TELEGRAM_GROUP_ID,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=True,
                message_thread_id=thread_id,
                reply_markup=keyboard,
            )
            sent_messages[topic_key] = {
                "chat_id": str(TELEGRAM_GROUP_ID),
                "message_id": result.message_id,
            }
            log.info(f"  ✓ Sent to {topic_name}: {job.title}")
        except TelegramError as e:
            log.error(f"  ✗ Failed {topic_name}: {job.title} — {e}")

        await _async_sleep(0.5)

    return sent_messages


async def send_jobs(bot: Bot, jobs: list[tuple[Job, int]]) -> int:
    """
    Send multiple jobs to their matching topics.

    Args:
        bot: Telegram Bot instance
        jobs: List of (Job, db_id) tuples

    Returns: Total successful send count
    """
    total_sent = 0
    topic_stats = {}

    for i, (job, db_id) in enumerate(jobs):
        sent = await send_job_to_topics(bot, job, db_id)

        # Update DB with message IDs
        if sent:
            db.mark_job_sent(db_id, sent)

        for t_key in sent:
            topic_stats[t_key] = topic_stats.get(t_key, 0) + 1
            total_sent += 1

        if i < len(jobs) - 1:
            await _async_sleep(TELEGRAM_SEND_DELAY)

    if topic_stats:
        log.info("📊 Topic send summary:")
        for t_key, count in sorted(topic_stats.items()):
            t_name = CHANNELS.get(t_key, {}).get("name", t_key)
            log.info(f"  {t_name}: {count} jobs")

    return total_sent


async def _async_sleep(seconds: float) -> None:
    """Async sleep wrapper."""
    import asyncio
    await asyncio.sleep(seconds)
