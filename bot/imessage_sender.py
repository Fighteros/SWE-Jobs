"""
bot/imessage_sender.py — deliver queued job records over iMessage (Photon).

Used instead of bot/sender.deliver_group_topic_records when
DELIVERY_CHANNEL=imessage. Each group-topic record is one (job, topic)
attempt; iMessage has no topics, so a job is sent once per batch to every
configured recipient and all of its records share the outcome.
"""

import asyncio
import logging

from core import db_async as adb
from core import imessage
from core.delivery_queue import (
    mark_delivery_failed,
    mark_delivery_sent,
    mark_delivery_skipped,
)
from core.models import Job
from bot.sender import format_job_message

log = logging.getLogger(__name__)


async def deliver_imessage_records(records: list[dict]) -> dict:
    """
    Send a batch of claimed group_topic delivery records via iMessage.

    Returns a stats dict with sent/failed/skipped counts (per record, matching
    the Telegram delivery stats shape).
    """
    stats = {"sent": 0, "failed": 0, "skipped": 0}

    if not records:
        return stats

    # Pre-load jobs to avoid N+1 lookups.
    job_ids = {r["job_id"] for r in records}
    jobs_by_id: dict[int, Job] = {}
    for job_id in job_ids:
        row = await adb._fetchone("SELECT * FROM jobs WHERE id = %s", (job_id,))
        if row:
            jobs_by_id[job_id] = Job.from_db_row(row)

    # iMessage has no topics: send each job once, then apply the outcome to
    # every (job, topic) record for that job.
    sent_job_ids: set[int] = set()
    failed_job_errors: dict[int, str] = {}

    for i, record in enumerate(records):
        job_id = record["job_id"]
        if job_id in sent_job_ids or job_id in failed_job_errors:
            continue

        job = jobs_by_id.get(job_id)
        if not job:
            failed_job_errors[job_id] = "job not found"
            continue

        message = imessage.html_to_plain(format_job_message(job))
        try:
            result = await asyncio.to_thread(imessage.send_to_recipients, message)
            if result["sent"] > 0:
                sent_job_ids.add(job_id)
                log.info(f"  ✓ iMessage sent ({result['sent']} recipients): {job.title}")
            else:
                failed_job_errors[job_id] = "all iMessage recipients failed"
                log.error(f"  ✗ iMessage failed for all recipients: {job.title}")
        except Exception as e:
            failed_job_errors[job_id] = str(e)[:200]
            log.error(f"  ✗ iMessage send error: {job.title} — {e}")

        if i < len(records) - 1:
            await asyncio.sleep(0.5)

    for record in records:
        delivery_id = record["id"]
        job_id = record["job_id"]
        job = jobs_by_id.get(job_id)
        if not job:
            await asyncio.to_thread(mark_delivery_failed, delivery_id, "job not found", False)
            stats["failed"] += 1
        elif job_id in sent_job_ids:
            # message_id column is BIGINT (Telegram ids); Photon guids are
            # strings, so nothing is stored there for iMessage deliveries.
            await asyncio.to_thread(mark_delivery_sent, delivery_id, None)
            stats["sent"] += 1
        else:
            await asyncio.to_thread(
                mark_delivery_failed, delivery_id, failed_job_errors[job_id], True
            )
            stats["failed"] += 1

    if sum(stats.values()):
        log.info(f"📊 iMessage batch: {stats}")

    return stats
