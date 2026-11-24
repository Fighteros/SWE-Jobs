import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core import imessage


@pytest.fixture
def sidecar_env():
    with patch("core.imessage.IMESSAGE_SIDECAR_URL", "http://sidecar:8789"), \
         patch("core.imessage.IMESSAGE_RECIPIENTS", ["+201099599616", "a@b.com"]):
        yield


def _mock_response(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


# --- html_to_plain -----------------------------------------------------------

def test_html_to_plain_strips_tags_and_unescapes():
    assert imessage.html_to_plain("<b>Senior Dev</b> &amp; Co") == "Senior Dev & Co"


def test_html_to_plain_expands_links():
    html = '🔗 <a href="https://x.dev/job/1">Apply Now</a>'
    assert imessage.html_to_plain(html) == "🔗 Apply Now: https://x.dev/job/1"


# --- Sidecar client ----------------------------------------------------------

def test_send_text_posts_to_sidecar_send_endpoint(sidecar_env):
    with patch("core.imessage.requests.post") as post:
        post.return_value = _mock_response({"ok": True})
        imessage.send_text("+201099599616", "hello")

    post.assert_called_once()
    url = post.call_args.args[0] if post.call_args.args else post.call_args.kwargs["url"]
    assert url == "http://sidecar:8789/send"
    assert post.call_args.kwargs["json"] == {"to": "+201099599616", "text": "hello"}


def test_send_text_raises_when_sidecar_reports_not_ok(sidecar_env):
    with patch("core.imessage.requests.post") as post:
        post.return_value = _mock_response({"ok": False, "error": "boom"})
        with pytest.raises(RuntimeError):
            imessage.send_text("+201099599616", "hello")


def test_send_to_recipients_counts_partial_failures(sidecar_env):
    def fake_send(address, text):
        if address == "a@b.com":
            raise RuntimeError("boom")

    with patch("core.imessage.send_text", side_effect=fake_send):
        stats = imessage.send_to_recipients("hi")

    assert stats == {"sent": 1, "failed": 1}


def test_configured_requires_url_and_recipients(sidecar_env):
    assert imessage.configured()
    with patch("core.imessage.IMESSAGE_RECIPIENTS", []):
        assert not imessage.configured()


# --- Synthetic user ids ------------------------------------------------------

def test_imessage_user_id_is_negative_and_stable():
    id1 = imessage.imessage_user_telegram_id("+201099599616")
    id2 = imessage.imessage_user_telegram_id("+201099599616")
    id3 = imessage.imessage_user_telegram_id(" +201099599616 ")
    other = imessage.imessage_user_telegram_id("a@b.com")

    assert id1 == id2 == id3
    assert id1 < 0
    assert id1 != other
    assert imessage.is_imessage_user(id1)
    assert not imessage.is_imessage_user(123456789)


# --- Queued personalized delivery over iMessage ------------------------------

def _record(rec_id, job_id, recipient_key="-42"):
    return {"id": rec_id, "job_id": job_id, "recipient_key": recipient_key}


def test_deliver_imessage_records_sends_to_user_address():
    from bot import imessage_sender

    job = MagicMock()
    job.title = "Senior Python Dev"
    records = [_record(1, 10), _record(2, 11)]

    fake_job_cls = MagicMock()
    fake_job_cls.from_db_row.return_value = job

    async def run():
        with patch("bot.imessage_sender.adb._fetchone", new=AsyncMock(return_value={"id": 10, "count": 0})), \
             patch("bot.imessage_sender.adb._fetchall",
                   new=AsyncMock(return_value=[{"telegram_id": -42, "username": "+201099599616"}])), \
             patch("bot.imessage_sender.Job", fake_job_cls), \
             patch("bot.imessage_sender.format_job_message", return_value="<b>Job</b>"), \
             patch("bot.imessage_sender.imessage.send_text") as send, \
             patch("bot.imessage_sender.imessage.html_to_plain", side_effect=lambda h: h), \
             patch("bot.imessage_sender.mark_delivery_sent") as mark_sent, \
             patch("bot.imessage_sender.mark_delivery_failed") as mark_failed:
            stats = await imessage_sender.deliver_imessage_records(records)
            return stats, send, mark_sent, mark_failed

    stats, send, mark_sent, mark_failed = asyncio.run(run())

    assert stats["sent"] == 2 and stats["failed"] == 0
    assert send.call_count == 2
    assert all(c.args[0] == "+201099599616" for c in send.call_args_list)
    assert mark_sent.call_count == 2
    mark_failed.assert_not_called()


def test_deliver_imessage_records_skips_telegram_users():
    from bot import imessage_sender

    job = MagicMock()
    records = [_record(1, 10, recipient_key="123456789")]

    fake_job_cls = MagicMock()
    fake_job_cls.from_db_row.return_value = job

    async def run():
        with patch("bot.imessage_sender.adb._fetchone", new=AsyncMock(return_value={"id": 10, "count": 0})), \
             patch("bot.imessage_sender.adb._fetchall",
                   new=AsyncMock(return_value=[{"telegram_id": 123456789, "username": "tguser"}])), \
             patch("bot.imessage_sender.Job", fake_job_cls), \
             patch("bot.imessage_sender.imessage.send_text") as send, \
             patch("bot.imessage_sender.mark_delivery_skipped") as mark_skipped:
            stats = await imessage_sender.deliver_imessage_records(records)
            return stats, send, mark_skipped

    stats, send, mark_skipped = asyncio.run(run())

    assert stats["skipped"] == 1
    send.assert_not_called()
    mark_skipped.assert_called_once()


def test_deliver_imessage_records_marks_send_failure_retryable():
    from bot import imessage_sender

    job = MagicMock()
    records = [_record(1, 10)]

    fake_job_cls = MagicMock()
    fake_job_cls.from_db_row.return_value = job

    async def run():
        with patch("bot.imessage_sender.adb._fetchone", new=AsyncMock(return_value={"id": 10, "count": 0})), \
             patch("bot.imessage_sender.adb._fetchall",
                   new=AsyncMock(return_value=[{"telegram_id": -42, "username": "+201099599616"}])), \
             patch("bot.imessage_sender.Job", fake_job_cls), \
             patch("bot.imessage_sender.format_job_message", return_value="<b>Job</b>"), \
             patch("bot.imessage_sender.imessage.send_text",
                   side_effect=RuntimeError("connection refused")), \
             patch("bot.imessage_sender.imessage.html_to_plain", side_effect=lambda h: h), \
             patch("bot.imessage_sender.mark_delivery_sent") as mark_sent, \
             patch("bot.imessage_sender.mark_delivery_failed") as mark_failed:
            stats = await imessage_sender.deliver_imessage_records(records)
            return stats, mark_sent, mark_failed

    stats, mark_sent, mark_failed = asyncio.run(run())

    assert stats["failed"] == 1
    mark_sent.assert_not_called()
    # Retryable failure: the record is retried later, not dead-lettered.
    assert mark_failed.call_args.args[2] is True


# --- Scheduler routing -------------------------------------------------------

def test_scheduler_routes_dm_records_to_imessage_and_skips_group_topics():
    from core import delivery_scheduler

    records = [_record(1, 10)]

    async def run():
        with patch("core.config.DELIVERY_CHANNEL", "imessage"), \
             patch("core.delivery_scheduler.recover_stale_deliveries",
                   return_value={"recovered": 0, "dead_lettered": 0}), \
             patch("core.delivery_scheduler._claim") as claim, \
             patch("bot.imessage_sender.deliver_imessage_records",
                   new=AsyncMock(return_value={"sent": 1, "failed": 0, "deferred": 0})) as im_deliver, \
             patch("core.delivery_scheduler.deliver_group_topic_records",
                   new=AsyncMock()) as tg_deliver, \
             patch("core.delivery_scheduler.deliver_subscriber_dm_records",
                   new=AsyncMock()) as dm_deliver:
            # First pass: one DM record, no group records; second pass: nothing.
            claim.side_effect = [[], records, [], []]
            stats = await delivery_scheduler.run_delivery_cycle(None, max_cycle_seconds=30)
            return stats, im_deliver, tg_deliver, dm_deliver, claim

    stats, im_deliver, tg_deliver, dm_deliver, claim = asyncio.run(run())

    im_deliver.assert_awaited_once()
    tg_deliver.assert_not_awaited()
    dm_deliver.assert_not_awaited()
    assert stats["dm_sent"] == 1
    assert stats["group_topic_sent"] == 0


# --- Enqueue gating ----------------------------------------------------------

def test_enqueue_skips_group_topics_in_imessage_mode():
    from core import delivery_queue

    with patch("core.config.DELIVERY_CHANNEL", "imessage"), \
         patch("core.delivery_queue.build_group_topic_deliveries") as group_builder, \
         patch("core.delivery_queue.build_subscriber_dm_deliveries", return_value=[]) as dm_builder, \
         patch("core.delivery_queue._insert_delivery_rows", return_value=0):
        result = delivery_queue.enqueue_job_deliveries([("job", 1)])

    group_builder.assert_not_called()
    dm_builder.assert_called_once()
    assert result == {"group_topic_queued": 0, "subscriber_dm_queued": 0}


# --- Admin alerts ------------------------------------------------------------

def test_admin_alert_routes_to_imessage_in_imessage_mode():
    from core import monitoring

    async def run():
        with patch("core.monitoring.DELIVERY_CHANNEL", "imessage"), \
             patch("core.monitoring._imessage.configured", return_value=True), \
             patch("core.monitoring._imessage.send_to_recipients",
                   return_value={"sent": 1, "failed": 0}) as send, \
             patch("core.monitoring._imessage.html_to_plain", side_effect=lambda h: "plain"):
            return await monitoring.send_admin_alert(None, "<b>alert</b>"), send

    ok, send = asyncio.run(run())

    assert ok is True
    send.assert_called_once_with("plain")


def test_admin_alert_unconfigured_imessage_returns_false():
    from core import monitoring

    async def run():
        with patch("core.monitoring.DELIVERY_CHANNEL", "imessage"), \
             patch("core.monitoring._imessage.configured", return_value=False):
            return await monitoring.send_admin_alert(None, "alert")

    assert asyncio.run(run()) is False
