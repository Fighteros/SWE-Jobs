"""
core/delivery_scheduler.py — Independent delivery cycle for the durable queue.

A delivery cycle claims due records, sends them, and persists results. It
respects a runtime budget so that slow Telegram responses do not push the
scheduler past its next interval.
"""

import asyncio
import logging
import time
from typing import Optional

from telegram import Bot

from core import config
from core.delivery_queue import (
    DELIVERY_TYPE_GROUP_TOPIC,
    DELIVERY_TYPE_SUBSCRIBER_DM,
    recover_stale_deliveries,
)
from bot.sender import deliver_group_topic_records
from bot.notifications import deliver_subscriber_dm_records

log = logging.getLogger(__name__)


async def run_delivery_cycle(
    bot: Bot,
    max_cycle_seconds: Optional[int] = None,
    batch_size: Optional[int] = None,
    lease_seconds: Optional[int] = None,
    max_attempts: Optional[int] = None,
) -> dict:
    """
    Run one delivery cycle: recover stale records, then drain due batches.

    Returns aggregate stats for the cycle.
    """
    max_cycle_seconds = max_cycle_seconds if max_cycle_seconds is not None else config.DELIVERY_MAX_CYCLE_SECONDS
    batch_size = batch_size if batch_size is not None else config.DELIVERY_BATCH_SIZE

    start = time.monotonic()

    def _budget_remaining() -> float:
        return max_cycle_seconds - (time.monotonic() - start)

    stats = {
        "stale_recovered": 0,
        "stale_dead_lettered": 0,
        "group_topic_sent": 0,
        "group_topic_failed": 0,
        "group_topic_skipped": 0,
        "dm_sent": 0,
        "dm_failed": 0,
        "dm_deferred": 0,
    }

    # Recover records left behind by crashed/hung workers.
    stale_stats = recover_stale_deliveries(lease_seconds=lease_seconds, max_attempts=max_attempts)
    stats["stale_recovered"] = stale_stats["recovered"]
    stats["stale_dead_lettered"] = stale_stats["dead_lettered"]

    while _budget_remaining() > 1.0:
        # Claim group-topic records first, then DM records. They are independent.
        group_records = await asyncio.to_thread(
            _claim, batch_size, DELIVERY_TYPE_GROUP_TOPIC
        )
        if group_records:
            group_stats = await deliver_group_topic_records(bot, group_records)
            stats["group_topic_sent"] += group_stats.get("sent", 0)
            stats["group_topic_failed"] += group_stats.get("failed", 0)
            stats["group_topic_skipped"] += group_stats.get("skipped", 0)

        dm_records = await asyncio.to_thread(
            _claim, batch_size, DELIVERY_TYPE_SUBSCRIBER_DM
        )
        if dm_records:
            dm_stats = await deliver_subscriber_dm_records(bot, dm_records)
            stats["dm_sent"] += dm_stats.get("sent", 0)
            stats["dm_failed"] += dm_stats.get("failed", 0)
            stats["dm_deferred"] += dm_stats.get("deferred", 0)

        if not group_records and not dm_records:
            break

    elapsed = time.monotonic() - start
    log.info(
        f"Delivery cycle complete in {elapsed:.1f}s: {stats}"
    )
    return stats


def _claim(batch_size: int, delivery_type: str):
    """Synchronous wrapper so claim runs on a worker thread."""
    from core.delivery_queue import claim_pending_deliveries

    return claim_pending_deliveries(batch_size, delivery_type=delivery_type)
