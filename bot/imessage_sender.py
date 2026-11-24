"""
bot/imessage_sender.py — deliver queued personalized job records over iMessage.

Used instead of bot/notifications.deliver_subscriber_dm_records when
DELIVERY_CHANNEL=imessage. Each subscriber_dm record is one (job, iMessage
user) attempt; the iMessage address lives in users.username (the record's
recipient_key is the user's synthetic negative telegram_id). Sending goes
through the Photon Spectrum sidecar over loopback HTTP (core/imessage.py).

Rate limiting mirrors the Telegram DM path: DM_MAX_PER_USER_PER_WINDOW sends
per user per DM_RATE_WINDOW_SECONDS, using the DB clock; records over the
quota are released back to pending for the next open capacity.
"""

import asyncio
import logging

from core import db_async as adb
from core import db, imessage
from core.delivery_queue import (
    DELIVERY_TYPE_SUBSCRIBER_DM,
    _matching_alert,
    mark_delivery_failed,
    mark_delivery_sent,
    mark_delivery_skipped,
    release_delivery_to_pending,
)
from core.models import Job
from core.subscription_matching import job_blocked_by_blacklist
from bot.sender import format_job_message
from core.config import (
    DM_MAX_PER_USER_PER_WINDOW,
    DM_RATE_WINDOW_SECONDS,
)

log = logging.getLogger(__name__)


def _is_retryable_error(error: str) -> bool:
    err = error.lower()
    return any(phrase in err for phrase in (
        "timed out", "timeout", "connection", "too many requests",
        "bad gateway", "gateway timeout", "unavailable", "500", "502", "503",
    ))


def _still_subscribed(user_id: int, job: Job) -> bool:
    user = db._fetchone("SELECT notify_dm FROM users WHERE id = %s", (user_id,))
    return bool(
        user and user["notify_dm"]
        and _matching_alert(job, db.get_user_alerts(user_id))
        and not job_blocked_by_blacklist(job, db.get_blacklist(user_id))
    )


async def deliver_imessage_records(records: list[dict]) -> dict:
    """
    Send a batch of claimed subscriber_dm delivery records via iMessage.

    Returns a stats dict with sent/failed/deferred counts.
    """
    stats = {"sent": 0, "failed": 0, "deferred": 0, "skipped": 0}

    if not records:
        return stats

    # Pre-load jobs and users to avoid N+1 lookups.
    job_ids = {r["job_id"] for r in records}
    user_keys = {r["recipient_key"] for r in records}

    jobs_by_id: dict[int, Job] = {}
    for job_id in job_ids:
        row = await adb._fetchone("SELECT * FROM jobs WHERE id = %s", (job_id,))
        if row:
            jobs_by_id[job_id] = Job.from_db_row(row)

    users_by_key: dict[str, dict] = {}
    if user_keys:
        placeholders = ", ".join("%s" for _ in user_keys)
        rows = await adb._fetchall(
            f"SELECT * FROM users WHERE telegram_id IN ({placeholders})",
            tuple(int(uid) for uid in user_keys),
        )
        for row in rows:
            users_by_key[str(row["telegram_id"])] = row

    # Per-user sliding-window send counts.
    user_sent_counts: dict[str, int] = {}
    retry_times: dict = {}

    async def _count_sent_in_window(recipient_key: str) -> int:
        row = await adb._fetchone(
            """
            SELECT COUNT(*) as count
            FROM job_deliveries
            WHERE delivery_type = %s
              AND recipient_key = %s
              AND status = %s
              AND sent_at > now() - make_interval(secs := %s)
            """,
            (DELIVERY_TYPE_SUBSCRIBER_DM, recipient_key, "sent", DM_RATE_WINDOW_SECONDS),
        )
        return row["count"] if row else 0

    async def _defer(delivery_id: int, recipient_key: str) -> None:
        if recipient_key not in retry_times:
            # The quota-th newest send must expire before another send is safe.
            row = await adb._fetchone(
                """
                SELECT COALESCE(
                    (array_agg(sent_at ORDER BY sent_at DESC))[%s]
                        + make_interval(secs := %s),
                    now() + make_interval(secs := %s)
                ) AS retry_at
                FROM job_deliveries
                WHERE delivery_type = %s
                  AND recipient_key = %s
                  AND status = %s
                  AND sent_at > now() - make_interval(secs := %s)
                """,
                (DM_MAX_PER_USER_PER_WINDOW, DM_RATE_WINDOW_SECONDS,
                 DM_RATE_WINDOW_SECONDS, DELIVERY_TYPE_SUBSCRIBER_DM,
                 recipient_key, "sent", DM_RATE_WINDOW_SECONDS),
            )
            retry_times[recipient_key] = row["retry_at"]
            log.info(
                "iMessage rate limit reached for recipient %s; deferred until %s",
                recipient_key, row["retry_at"].isoformat(),
            )
        await asyncio.to_thread(
            release_delivery_to_pending, delivery_id, retry_times[recipient_key]
        )
        stats["deferred"] += 1

    for record in records:
        delivery_id = record["id"]
        job_id = record["job_id"]
        recipient_key = record["recipient_key"]

        job = jobs_by_id.get(job_id)
        user = users_by_key.get(recipient_key)

        if not job or not user:
            await asyncio.to_thread(
                mark_delivery_failed, delivery_id, "missing job or user", False
            )
            stats["failed"] += 1
            continue

        telegram_id = int(recipient_key)
        if not imessage.is_imessage_user(telegram_id):
            # A Telegram user should never be delivered via iMessage; in
            # imessage mode only synthetic iMessage users get DM records.
            await asyncio.to_thread(
                mark_delivery_skipped, delivery_id, "telegram_user_in_imessage_mode"
            )
            stats["skipped"] += 1
            continue

        address = user.get("username") or ""
        if not address:
            await asyncio.to_thread(
                mark_delivery_failed, delivery_id, "user has no iMessage address", False
            )
            stats["failed"] += 1
            continue

        if not await asyncio.to_thread(_still_subscribed, user["id"], job):
            await asyncio.to_thread(mark_delivery_skipped, delivery_id, "subscription_no_longer_matches")
            stats["skipped"] += 1
            continue

        if recipient_key not in user_sent_counts:
            user_sent_counts[recipient_key] = await _count_sent_in_window(recipient_key)

        if user_sent_counts[recipient_key] >= DM_MAX_PER_USER_PER_WINDOW:
            await _defer(delivery_id, recipient_key)
            continue

        message = imessage.html_to_plain(format_job_message(job))
        try:
            await asyncio.to_thread(imessage.send_text, address, message)
            await asyncio.to_thread(mark_delivery_sent, delivery_id, None)
            user_sent_counts[recipient_key] += 1
            stats["sent"] += 1
            log.info(f"  ✓ iMessage sent to {address}: {job.title}")
        except Exception as e:
            err = str(e)[:200]
            await asyncio.to_thread(
                mark_delivery_failed, delivery_id, err, _is_retryable_error(err)
            )
            stats["failed"] += 1
            log.error(f"  ✗ iMessage send error to {address}: {job.title} — {e}")

        await asyncio.sleep(0.5)

    log.info(
        f"📬 iMessage delivery batch: {stats['sent']} sent, {stats['failed']} failed, "
        f"{stats['deferred']} deferred, {stats['skipped']} skipped"
    )
    return stats
