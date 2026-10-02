"""
Job message formatting and group-topic delivery.

This module now works with durable delivery records in the job_deliveries
queue. Each record represents one (job, topic) send attempt; records are
claimed independently, sent independently, and retried independently.
"""

import asyncio
import logging

from telegram import Bot
from telegram.error import TelegramError, RetryAfter, TimedOut, NetworkError

from core import db_async as adb
from core.config import TELEGRAM_BOT_TOKEN, TELEGRAM_GROUP_ID, TELEGRAM_SEND_DELAY
from core.models import Job
from core.channels import CHANNELS, get_topic_thread_id, SOURCE_ICON
from core.delivery_queue import (
    DELIVERY_TYPE_GROUP_TOPIC,
    claim_pending_deliveries,
    enqueue_job_deliveries,
    mark_delivery_failed,
    mark_delivery_sent,
    mark_delivery_skipped,
    update_job_aggregate_message_id,
)
from bot.keyboards import job_buttons

log = logging.getLogger(__name__)

# Retry config for transient Telegram errors
_MAX_RETRIES = 3
_RETRY_BACKOFF = 2.0  # seconds, doubled each retry


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def format_job_message(job: Job) -> str:
    """Format a job as an HTML Telegram message."""
    from core.egytech import market_salary_for_job

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

    market = market_salary_for_job(job)
    if market:
        lines.append(f"💰 Market: {_escape_html(market)}")

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
    if job.is_easy_apply:
        lines.append("⚡ Easy Apply on LinkedIn")

    if job.posted_display:
        lines.append(f"🕐 Posted {job.posted_display}")

    lines.append("")
    apply_label = "⚡ Easy Apply on LinkedIn" if job.is_easy_apply else "Apply Now"
    lines.append(f'🔗 <a href="{job.url}">{apply_label}</a>')
    source_icon = SOURCE_ICON.get(job.source, "📡")
    lines.append(f"{source_icon} Source: {source}")

    return "\n".join(lines)


async def _send_with_retry(bot: Bot, **kwargs) -> object:
    """Send a Telegram message with retry on transient errors."""
    delay = _RETRY_BACKOFF
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return await bot.send_message(**kwargs)
        except RetryAfter as e:
            # Telegram explicitly told us to wait
            wait = e.retry_after + 1
            log.warning(f"  ⏳ Rate limited, waiting {wait}s (attempt {attempt}/{_MAX_RETRIES})")
            await asyncio.sleep(wait)
        except (TimedOut, NetworkError) as e:
            if attempt == _MAX_RETRIES:
                raise
            log.warning(f"  ⏳ Transient error, retrying in {delay}s (attempt {attempt}/{_MAX_RETRIES}): {e}")
            await asyncio.sleep(delay)
            delay *= 2
    return None  # unreachable, last attempt raises


def _is_retryable_error(error: str) -> bool:
    err = error.lower()
    return any(phrase in err for phrase in (
        "retry after", "timed out", "network error", "bad gateway",
        "gateway timeout", "too many requests", "connection",
    ))


async def deliver_group_topic_records(bot: Bot, records: list[dict]) -> dict:
    """
    Send a batch of claimed group_topic delivery records.

    Each record is one (job, topic) attempt. Results are persisted
    independently; successful topics are not retried, failed topics are.

    Returns a stats dict with sent/failed/skipped counts.
    """
    stats = {"sent": 0, "failed": 0, "skipped": 0}

    if not records:
        return stats

    # Pre-load jobs to avoid N+1 lookups.
    job_ids = {r["job_id"] for r in records}
    jobs_by_id: dict[int, Job] = {}
    for job_id in job_ids:
        from core import db_async as adb
        row = await adb._fetchone("SELECT * FROM jobs WHERE id = %s", (job_id,))
        if row:
            jobs_by_id[job_id] = Job.from_db_row(row)

    for i, record in enumerate(records):
        delivery_id = record["id"]
        job_id = record["job_id"]
        topic_key = record["recipient_key"]
        worker_id = record["worker_id"]

        job = jobs_by_id.get(job_id)
        if not job:
            await asyncio.to_thread(mark_delivery_failed, delivery_id, worker_id, "job not found", False)
            stats["failed"] += 1
            continue

        thread_id = get_topic_thread_id(topic_key)
        if thread_id is None:
            await asyncio.to_thread(
                mark_delivery_skipped, delivery_id, worker_id, "topic_not_configured"
            )
            stats["skipped"] += 1
            continue

        topic_name = CHANNELS.get(topic_key, {}).get("name", topic_key)
        message = format_job_message(job)
        keyboard = job_buttons(job_id)

        try:
            result = await _send_with_retry(
                bot,
                chat_id=TELEGRAM_GROUP_ID,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=True,
                message_thread_id=thread_id,
                reply_markup=keyboard,
            )
            message_id = getattr(result, "message_id", None)
            await asyncio.to_thread(mark_delivery_sent, delivery_id, worker_id, message_id)
            if message_id:
                await asyncio.to_thread(
                    update_job_aggregate_message_id, job_id, topic_key, message_id
                )
            stats["sent"] += 1
            log.info(f"  ✓ Sent to {topic_name}: {job.title}")
        except TelegramError as e:
            err = str(e)
            await asyncio.to_thread(
                mark_delivery_failed, delivery_id, worker_id, err, _is_retryable_error(err)
            )
            stats["failed"] += 1
            log.error(f"  ✗ Failed {topic_name}: {job.title} — {e}")
        except Exception as e:
            await asyncio.to_thread(mark_delivery_failed, delivery_id, worker_id, str(e), True)
            stats["failed"] += 1
            log.error(f"  ✗ Unexpected error sending to {topic_name}: {job.title} — {e}")

        if i < len(records) - 1:
            await asyncio.sleep(0.5)

    if sum(stats.values()):
        log.info(f"📊 Group-topic batch: {stats}")

    return stats


# =============================================================================
# Backwards-compatible helpers
# =============================================================================

async def send_job_to_topics(bot: Bot, job: Job, job_db_id: int) -> dict:
    """
    Send a job to all matching Telegram topics with inline buttons.

    Returns: {topic_key: {"chat_id": ..., "message_id": ...}} for sent messages.
    Kept for callers that build deliveries inline; prefer deliver_group_topic_records.
    """
    if not job.topics:
        log.warning(f"  ⚠ No topics assigned: {job.title}")
        return {}

    await asyncio.to_thread(enqueue_job_deliveries, [(job, job_db_id)], is_seed=False)

    # Claim and deliver the records we just created.
    records = await asyncio.to_thread(
        claim_pending_deliveries,
        len(job.topics),
        delivery_type=DELIVERY_TYPE_GROUP_TOPIC,
    )
    await deliver_group_topic_records(bot, records)

    row = await adb._fetchone(
        "SELECT telegram_message_ids FROM jobs WHERE id = %s", (job_db_id,)
    )
    return row["telegram_message_ids"] if row else {}


async def send_jobs(bot: Bot, jobs: list[tuple[Job, int]]) -> int:
    """
    Send multiple jobs to their matching topics.

    Backwards-compatible helper: creates delivery records and immediately
    attempts to deliver them. Returns the number of jobs that had at least one
    topic sent.
    """
    if not jobs or not bot:
        return 0

    await asyncio.to_thread(enqueue_job_deliveries, jobs, is_seed=False)

    total_sent = 0
    for job, db_id in jobs:
        sent_map = await send_job_to_topics(bot, job, db_id)
        if sent_map:
            total_sent += 1
        await asyncio.sleep(TELEGRAM_SEND_DELAY)

    return total_sent


async def _async_sleep(seconds: float) -> None:
    """Async sleep wrapper."""
    await asyncio.sleep(seconds)
