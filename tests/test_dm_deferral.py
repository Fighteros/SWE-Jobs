"""Rate-limited deliveries sleep until DB-clock capacity and never busy-spin."""
from datetime import datetime, timezone, timedelta
import os
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.notifications import deliver_subscriber_dm_records
from core.delivery_queue import release_delivery_to_pending, claim_pending_deliveries
from core.delivery_scheduler import run_delivery_cycle
from core.models import Job

NOW = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)
RETRY_AT = NOW + timedelta(minutes=30)


def record(i, recipient="42"):
    return {"id": i, "job_id": i, "recipient_key": recipient}


@pytest.mark.asyncio
async def test_deferred_batch_has_future_retry_and_no_telegram_send(caplog):
    records = [record(i) for i in range(1, 51)]
    calls = []

    async def fetchone(sql, params):
        calls.append((sql, params))
        return {"retry_at": RETRY_AT} if "array_agg" in sql else {"count": 20}

    with patch("bot.notifications.adb._fetchone", side_effect=fetchone), \
         patch("bot.notifications.adb._fetchall", return_value=[{"id": 1, "telegram_id": 42}]), \
         patch("bot.notifications.Job.from_db_row", return_value=MagicMock()), \
         patch("bot.notifications.DM_MAX_PER_USER_PER_WINDOW", 20), \
         patch("bot.notifications.DM_RATE_WINDOW_SECONDS", 3600), \
         patch("bot.notifications.release_delivery_to_pending") as release:
        # Job preload fetches use the same mock, but their contents are not used.
        bot = MagicMock(send_message=AsyncMock())
        with caplog.at_level("INFO"):
            stats = await deliver_subscriber_dm_records(bot, records)

    assert stats["deferred"] == 50 and stats["sent"] == stats["failed"] == 0
    bot.send_message.assert_not_called()
    assert release.call_count == 50
    assert all(call.args[1] == RETRY_AT for call in release.call_args_list)
    query, params = next((s, p) for s, p in calls if "array_agg" in s)
    assert params == (20, 3600, 3600, "subscriber_dm", "42", "sent", 3600)
    assert "ORDER BY sent_at DESC" in query and "now()" in query
    assert "deferred until" in caplog.text and RETRY_AT.isoformat() in caplog.text


@pytest.mark.asyncio
async def test_mixed_recipients_preserve_eligible_sends_and_in_batch_quota():
    counts = {"42": 20, "43": 19}
    job = Job(title="Engineer", company="Acme", location="Cairo", url="https://example.com/job", source="test")

    async def fetchone(sql, params):
        if "array_agg" in sql:
            return {"retry_at": RETRY_AT}
        if "COUNT" in sql:
            return {"count": counts[params[1]]}
        return {"id": params[0]}

    with patch("bot.notifications.adb._fetchone", side_effect=fetchone), \
         patch("bot.notifications.adb._fetchall", return_value=[{"id": 1, "telegram_id": 42}, {"id": 2, "telegram_id": 43}]), \
         patch("bot.notifications.adb.get_user_alerts", return_value=[{"position": 1}]), \
         patch("bot.notifications.adb.get_blacklist", return_value={}), \
         patch("bot.notifications.Job.from_db_row", return_value=job), \
         patch("bot.notifications._matching_alert", return_value={"position": 1}), \
         patch("bot.notifications.job_blocked_by_blacklist", return_value=False), \
         patch("bot.notifications.DM_MAX_PER_USER_PER_WINDOW", 20), \
         patch("bot.notifications.mark_delivery_sent") as sent, \
         patch("bot.notifications.release_delivery_to_pending") as release:
        bot = MagicMock(send_message=AsyncMock(return_value=MagicMock(message_id=123)))
        stats = await deliver_subscriber_dm_records(bot, [record(1), record(2, "43"), record(3, "43")])
    assert stats["sent"] == 1 and stats["deferred"] == 2
    bot.send_message.assert_awaited_once()
    assert bot.send_message.call_args.kwargs["chat_id"] == 43
    sent.assert_called_once_with(2, 123)
    assert {c.args[0] for c in release.call_args_list} == {1, 3}


def test_release_preserves_future_timestamp_and_refunds_attempt():
    with patch("core.delivery_queue.db._execute") as execute:
        release_delivery_to_pending(7, RETRY_AT)
    sql, params = execute.call_args.args
    assert "next_attempt_at = %s" in sql
    assert "attempts = GREATEST(attempts - 1, 0)" in sql
    assert params == ("pending", RETRY_AT, 7)


@pytest.mark.asyncio
async def test_all_deferred_guard_keeps_other_users_and_group_work_moving():
    seen_calls = []
    def claim(size, kind, exclude):
        seen_calls.append((kind, set(exclude)))
        pool = [record(11)] if kind == "group_topic" else [record(1), record(2, "43")]
        return [r for r in pool if r["id"] not in exclude][:1]

    with patch("core.delivery_scheduler.recover_stale_deliveries", return_value={"recovered": 0, "dead_lettered": 0}), \
         patch("core.delivery_scheduler._claim", side_effect=claim), \
         patch("core.delivery_scheduler.deliver_group_topic_records", return_value={"sent": 1}) as group, \
         patch("core.delivery_scheduler.deliver_subscriber_dm_records", side_effect=[{"deferred": 1}, {"sent": 1}]) as dm:
        stats = await run_delivery_cycle(MagicMock(), max_cycle_seconds=10, batch_size=1)
    assert dm.call_count == 2 and group.call_count == 1
    assert len(seen_calls) == 6
    assert stats["dm_deferred"] == stats["dm_sent"] == stats["group_topic_sent"] == 1
    assert seen_calls[-1][1] == {1, 2, 11}


def test_claim_excludes_ids_already_visited():
    with patch("core.delivery_queue.db._get_conn") as conn:
        cursor = conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []
        claim_pending_deliveries(50, exclude_ids=[1, 2])
    sql, params = cursor.execute.call_args.args
    assert "NOT (id = ANY(%s::bigint[]))" in sql
    assert [1, 2] in params


@pytest.mark.parametrize("name", ["DM_MAX_PER_USER_PER_WINDOW", "DM_RATE_WINDOW_SECONDS"])
@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
def test_invalid_quota_fails_with_clear_config_error(name, value):
    env = dict(os.environ, DM_MAX_PER_USER_PER_WINDOW="20", DM_RATE_WINDOW_SECONDS="3600")
    env[name] = value
    result = subprocess.run([sys.executable, "-c", "import core.config"], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert f"{name} must be a positive integer" in result.stderr
