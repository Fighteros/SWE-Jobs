"""
Personalized DM alerts for subscribed users.

This module provides two paths:
  1. deliver_subscriber_dm_records(bot, records)
     Production path: send claimed subscriber_dm delivery records from the
     durable queue, respecting per-user rate limits and updating the queue
     state for each record independently.
  2. notify_subscribers(bot, jobs)
     Backwards-compatible direct-send path used by tests and one-off scripts.
     It does not create delivery records.

The matching helpers live in core.subscription_matching so they can be reused
when enqueueing delivery records at fetch time.
"""

import asyncio
import logging
from typing import Optional

from telegram import Bot
from telegram.error import TelegramError, RetryAfter, TimedOut, NetworkError

from core import db_async as adb
from core.delivery_queue import (
    DELIVERY_TYPE_SUBSCRIBER_DM,
    mark_delivery_failed,
    mark_delivery_sent,
    mark_delivery_skipped,
    release_delivery_to_pending,
)
from core.models import Job
from core.subscription_matching import job_blocked_by_blacklist, job_matches_alert
from bot.sender import format_job_message
from bot.keyboards import job_buttons
from core.config import (
    DM_MAX_PER_USER_PER_WINDOW,
    DM_RATE_WINDOW_SECONDS,
)

log = logging.getLogger(__name__)

# Re-export matching helpers for existing callers/tests.
_job_matches_alert = job_matches_alert
_job_blocked_by_blacklist = job_blocked_by_blacklist


# =============================================================================
# Telegram-error classification
# =============================================================================

def _is_permanent_dm_error(error: str) -> bool:
    """Return True for recipient-side or policy errors that will not heal by retrying."""
    err = error.lower()
    return any(phrase in err for phrase in (
        "bot was blocked",
        "user not found",
        "chat not found",
        "forbidden",
        "bot can't initiate conversation",
        "have no rights to send a message",
        "bot is not a member",
        "kicked",
        "deactivated",
        "invalid user",
    ))


def _is_retryable_error(error: str) -> bool:
    """Return True for transient Telegram/network failures that merit a retry."""
    err = error.lower()
    return any(phrase in err for phrase in (
        "retry after",
        "timed out",
        "network error",
        "bad gateway",
        "gateway timeout",
        "too many requests",
        "connection",
        "read timeout",
        "write timeout",
    ))


# =============================================================================
# Record-based production delivery
# =============================================================================

def _matching_alert(job: Job, alerts: list[dict]) -> Optional[dict]:
    """Return the first enabled alert that matches the job."""
    for alert in alerts:
        if not alert.get("dm_enabled", True):
            continue
        if job_matches_alert(job, alert):
            return alert
    return None


async def deliver_subscriber_dm_records(bot: Bot, records: list[dict]) -> dict:
    """
    Send a batch of claimed subscriber_dm delivery records.

    Per-user rate limiting is applied using a sliding window: once a user has
    received DM_MAX_PER_USER_PER_WINDOW messages within DM_RATE_WINDOW_SECONDS,
    all remaining records for that user in this batch are released back to
    pending for future cycles.

    Each record's outcome is persisted independently:
      - success          -> mark_delivery_sent
      - rate-limit defer -> release_delivery_to_pending
      - retryable error  -> mark_delivery_failed(retryable=True)
      - permanent error  -> disable user's notify_dm and mark dead_letter

    Returns a stats dict.
    """
    stats = {
        "sent": 0,
        "failed": 0,
        "deferred": 0,
        "disabled_users": 0,
    }

    if not records:
        return stats

    # Pre-load jobs and users so we can format messages and check alerts.
    job_ids = {r["job_id"] for r in records}
    user_ids = {r["recipient_key"] for r in records}

    jobs_by_id: dict[int, Job] = {}
    for job_id in job_ids:
        row = await adb._fetchone("SELECT * FROM jobs WHERE id = %s", (job_id,))
        if row:
            jobs_by_id[job_id] = Job.from_db_row(row)

    users_by_telegram_id: dict[str, dict] = {}
    if user_ids:
        placeholders = ", ".join("%s" for _ in user_ids)
        rows = await adb._fetchall(
            f"SELECT * FROM users WHERE telegram_id IN ({placeholders})",
            tuple(int(uid) for uid in user_ids),
        )
        for row in rows:
            users_by_telegram_id[str(row["telegram_id"])] = row

    # Track per-user sent counts in this window.
    user_sent_counts: dict[str, int] = {}
    rate_limited_users: set[str] = set()

    async def _count_sent_in_window(telegram_id: str) -> int:
        row = await adb._fetchone(
            """
            SELECT COUNT(*) as count
            FROM job_deliveries
            WHERE delivery_type = %s
              AND recipient_key = %s
              AND status = %s
              AND sent_at > now() - make_interval(secs := %s)
            """,
            (DELIVERY_TYPE_SUBSCRIBER_DM, telegram_id, "sent", DM_RATE_WINDOW_SECONDS),
        )
        return row["count"] if row else 0

    for record in records:
        delivery_id = record["id"]
        job_id = record["job_id"]
        telegram_id = record["recipient_key"]

        if telegram_id in rate_limited_users:
            await asyncio.to_thread(release_delivery_to_pending, delivery_id)
            stats["deferred"] += 1
            continue

        job = jobs_by_id.get(job_id)
        user = users_by_telegram_id.get(telegram_id)

        if not job or not user:
            await asyncio.to_thread(
                mark_delivery_failed,
                delivery_id,
                "missing job or user",
                False,
            )
            stats["failed"] += 1
            continue

        # Initialize per-user window count on first use.
        if telegram_id not in user_sent_counts:
            user_sent_counts[telegram_id] = await _count_sent_in_window(telegram_id)

        if user_sent_counts[telegram_id] >= DM_MAX_PER_USER_PER_WINDOW:
            rate_limited_users.add(telegram_id)
            await asyncio.to_thread(release_delivery_to_pending, delivery_id)
            stats["deferred"] += 1
            continue

        try:
            alerts = await adb.get_user_alerts(user["id"])
            blacklist = await adb.get_blacklist(user["id"])
            matched = _matching_alert(job, alerts)

            if matched is None or job_blocked_by_blacklist(job, blacklist):
                # Subscriber or alert state changed since enqueue; skip permanently.
                await asyncio.to_thread(
                    mark_delivery_skipped, delivery_id, "alert_or_blacklist_changed"
                )
                continue

            msg = format_job_message(job)
            result = await bot.send_message(
                chat_id=int(telegram_id),
                text=f"🔔 New matching job (Alert #{matched['position']}):\n\n{msg}",
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=job_buttons(job_id),
            )
            message_id = getattr(result, "message_id", None)
            await asyncio.to_thread(mark_delivery_sent, delivery_id, message_id)
            user_sent_counts[telegram_id] += 1
            stats["sent"] += 1

        except (RetryAfter, TimedOut, NetworkError) as e:
            await asyncio.to_thread(mark_delivery_failed, delivery_id, str(e), True)
            stats["failed"] += 1
        except TelegramError as e:
            err = str(e)
            if _is_permanent_dm_error(err):
                await adb._execute(
                    "UPDATE users SET notify_dm = FALSE WHERE telegram_id = %s",
                    (int(telegram_id),),
                )
                await asyncio.to_thread(mark_delivery_failed, delivery_id, err, False)
                log.info(f"Disabled DMs for user {telegram_id}: {e}")
                stats["disabled_users"] += 1
            else:
                await asyncio.to_thread(
                    mark_delivery_failed, delivery_id, err, _is_retryable_error(err)
                )
            stats["failed"] += 1
        except Exception as e:
            await asyncio.to_thread(mark_delivery_failed, delivery_id, str(e), True)
            stats["failed"] += 1

    log.info(
        f"📬 DM delivery batch: {stats['sent']} sent, {stats['failed']} failed, "
        f"{stats['deferred']} deferred"
    )
    return stats


# =============================================================================
# Backwards-compatible direct-send batch helper
# =============================================================================

async def notify_subscribers(bot: Bot, jobs: list[tuple[Job, int]]) -> int:
    """
    Send DM alerts to subscribed users for matching jobs.

    This is the pre-queue direct-send implementation kept for tests and manual
    runs. It does not create delivery records. The production server uses
    deliver_subscriber_dm_records via the independent delivery scheduler.

    Per-user behavior:
      - Skips users with notify_dm = FALSE (global kill switch).
      - Iterates the user's alerts in position order; first matching alert
        with dm_enabled=True wins (one DM per (user, job) pair).
      - Applies the user-level blacklist after a match.
      - Rate limits at DM_MAX_PER_USER_PER_WINDOW DMs per user per window.
    """
    try:
        users = await adb._fetchall(
            "SELECT * FROM users WHERE notify_dm = TRUE"
        )
    except Exception as e:
        log.error(f"Failed to fetch subscribers: {e}")
        return 0

    total_sent = 0

    for user_row in users:
        telegram_id = user_row["telegram_id"]
        user_id = user_row["id"]

        try:
            alerts = await adb.get_user_alerts(user_id)
            if not alerts:
                continue
            blacklist = await adb.get_blacklist(user_id)
            dm_count = 0

            for job, db_id in jobs:
                if dm_count >= DM_MAX_PER_USER_PER_WINDOW:
                    log.info(f"Rate limit hit for user {telegram_id}")
                    break

                matched = _matching_alert(job, alerts)
                if matched is None:
                    continue
                if job_blocked_by_blacklist(job, blacklist):
                    continue

                try:
                    msg = format_job_message(job)
                    await bot.send_message(
                        chat_id=telegram_id,
                        text=f"🔔 New matching job (Alert #{matched['position']}):\n\n{msg}",
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                        reply_markup=job_buttons(db_id),
                    )
                    dm_count += 1
                    total_sent += 1
                except TelegramError as e:
                    err = str(e).lower()
                    if _is_permanent_dm_error(err):
                        await adb._execute(
                            "UPDATE users SET notify_dm = FALSE WHERE telegram_id = %s",
                            (telegram_id,),
                        )
                        log.info(f"Disabled DMs for user {telegram_id}: {e}")
                        break
                    else:
                        log.warning(f"DM failed for {telegram_id}: {e}")
        except Exception as e:
            log.error(f"Failed to process alerts for user {telegram_id}: {e}")
            continue

    log.info(f"📬 Sent {total_sent} DM alerts across {len(users)} subscribers")
    return total_sent


async def _count_sent_dms_in_window(telegram_id) -> int:
    """Count DMs already sent to a user within the rate window."""
    row = await adb._fetchone(
        """
        SELECT COUNT(*) as count
        FROM job_deliveries
        WHERE delivery_type = %s
          AND recipient_key = %s
          AND status = %s
          AND sent_at > now() - make_interval(secs := %s)
        """,
        (DELIVERY_TYPE_SUBSCRIBER_DM, str(telegram_id), "sent", DM_RATE_WINDOW_SECONDS),
    )
    return row["count"] if row else 0
