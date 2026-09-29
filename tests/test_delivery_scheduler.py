"""
Tests for core/delivery_scheduler.py.
"""

from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from core.delivery_scheduler import run_delivery_cycle
from core.delivery_queue import DELIVERY_TYPE_GROUP_TOPIC, DELIVERY_TYPE_SUBSCRIBER_DM


class FakeBot:
    def __init__(self):
        self.send_message = AsyncMock(return_value=MagicMock(message_id=123))


@pytest.mark.asyncio
async def test_cycle_drains_group_topic_and_dm_batches():
    bot = FakeBot()
    group_records = [
        {"id": 1, "job_id": 10, "delivery_type": DELIVERY_TYPE_GROUP_TOPIC, "recipient_key": "backend"},
    ]
    dm_records = [
        {"id": 2, "job_id": 10, "delivery_type": DELIVERY_TYPE_SUBSCRIBER_DM, "recipient_key": "42"},
    ]

    with patch("core.delivery_scheduler.recover_stale_deliveries", return_value={"recovered": 0, "dead_lettered": 0}), \
         patch("core.delivery_scheduler._claim", side_effect=[group_records, dm_records, [], []]) as mock_claim, \
         patch("core.delivery_scheduler.deliver_group_topic_records", return_value={"sent": 1, "failed": 0, "skipped": 0}) as mock_group, \
         patch("core.delivery_scheduler.deliver_subscriber_dm_records", return_value={"sent": 1, "failed": 0, "deferred": 0}) as mock_dm:
        stats = await run_delivery_cycle(bot, max_cycle_seconds=10, batch_size=10)

    assert mock_claim.call_count >= 2  # group and DM claim attempted
    assert mock_group.call_count == 1
    assert mock_dm.call_count == 1
    assert stats["group_topic_sent"] == 1
    assert stats["dm_sent"] == 1


@pytest.mark.asyncio
async def test_cycle_stops_when_no_work():
    bot = FakeBot()

    with patch("core.delivery_scheduler.recover_stale_deliveries", return_value={"recovered": 0, "dead_lettered": 0}), \
         patch("core.delivery_scheduler._claim", return_value=[]):
        stats = await run_delivery_cycle(bot, max_cycle_seconds=10)

    assert stats["group_topic_sent"] == 0
    assert stats["dm_sent"] == 0


@pytest.mark.asyncio
async def test_cycle_respects_budget():
    bot = FakeBot()

    with patch("core.delivery_scheduler.recover_stale_deliveries", return_value={"recovered": 0, "dead_lettered": 0}), \
         patch("core.delivery_scheduler._claim", return_value=[]), \
         patch("core.delivery_scheduler.time.monotonic", side_effect=[0, 100, 100, 100]):
        stats = await run_delivery_cycle(bot, max_cycle_seconds=1)

    # Budget exhausted immediately; no batches attempted beyond the check.
    assert stats == {
        "stale_recovered": 0,
        "stale_dead_lettered": 0,
        "group_topic_sent": 0,
        "group_topic_failed": 0,
        "group_topic_skipped": 0,
        "dm_sent": 0,
        "dm_failed": 0,
        "dm_deferred": 0,
    }
