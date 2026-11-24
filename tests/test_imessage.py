import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core import imessage


@pytest.fixture(autouse=True)
def _clear_chat_cache():
    imessage._chat_guid_cache.clear()
    yield
    imessage._chat_guid_cache.clear()


@pytest.fixture
def photon_env():
    with patch("core.imessage.PHOTON_SERVER_ADDRESS", "imessage.example.com:443"), \
         patch("core.imessage.PHOTON_TOKEN", "tok-123"), \
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


# --- Photon client -----------------------------------------------------------

def test_chat_guid_is_created_once_and_cached(photon_env):
    with patch("core.imessage.requests.post") as post:
        post.return_value = _mock_response({"chat": {"guid": "any;-;+201099599616"}})
        guid1 = imessage.get_chat_guid("+201099599616")
        guid2 = imessage.get_chat_guid("+201099599616")

    assert guid1 == "any;-;+201099599616"
    assert guid2 == guid1
    post.assert_called_once()
    url = post.call_args.args[0] if post.call_args.args else post.call_args.kwargs["url"]
    assert url == "https://imessage.example.com:443/v1/chats"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer tok-123"
    assert post.call_args.kwargs["json"]["addresses"] == ["+201099599616"]


def test_send_text_posts_to_send_text_endpoint(photon_env):
    with patch("core.imessage.requests.post") as post:
        post.side_effect = [
            _mock_response({"chat": {"guid": "any;-;+201099599616"}}),
            _mock_response({"message": {"guid": "msg-1"}}),
        ]
        guid = imessage.send_text("+201099599616", "hello")

    assert guid == "msg-1"
    send_call = post.call_args_list[1]
    assert send_call.args[0].endswith("/v1/messages:sendText")
    assert send_call.kwargs["json"] == {"chatGuid": "any;-;+201099599616", "text": "hello"}


def test_send_to_recipients_counts_partial_failures(photon_env):
    def fake_send(address, text):
        if address == "a@b.com":
            raise RuntimeError("boom")
        return "ok"

    with patch("core.imessage.send_text", side_effect=fake_send):
        stats = imessage.send_to_recipients("hi")

    assert stats == {"sent": 1, "failed": 1}


def test_configured_requires_all_values(photon_env):
    assert imessage.configured()
    with patch("core.imessage.PHOTON_TOKEN", ""):
        assert not imessage.configured()


# --- Queued delivery over iMessage -------------------------------------------

def _record(rec_id, job_id):
    return {"id": rec_id, "job_id": job_id, "recipient_key": "backend"}


def test_deliver_imessage_records_sends_each_job_once():
    from bot import imessage_sender

    job = MagicMock()
    job.title = "Senior Python Dev"
    records = [_record(1, 10), _record(2, 10), _record(3, 11)]

    fake_job_cls = MagicMock()
    fake_job_cls.from_db_row.return_value = job

    async def run():
        with patch("bot.imessage_sender.adb._fetchone", new=AsyncMock(return_value={"id": 10})), \
             patch("bot.imessage_sender.Job", fake_job_cls), \
             patch("bot.imessage_sender.format_job_message", return_value="<b>Job</b>"), \
             patch("bot.imessage_sender.imessage.send_to_recipients",
                   return_value={"sent": 1, "failed": 0}) as send, \
             patch("bot.imessage_sender.imessage.html_to_plain", side_effect=lambda h: h), \
             patch("bot.imessage_sender.mark_delivery_sent") as mark_sent, \
             patch("bot.imessage_sender.mark_delivery_failed") as mark_failed:
            stats = await imessage_sender.deliver_imessage_records(records)
            return stats, send, mark_sent, mark_failed

    stats, send, mark_sent, mark_failed = asyncio.run(run())

    assert stats == {"sent": 3, "failed": 0, "skipped": 0}
    # Two distinct jobs -> two iMessage sends, three records marked sent.
    assert send.call_count == 2
    assert mark_sent.call_count == 3
    mark_failed.assert_not_called()


def test_deliver_imessage_records_marks_failed_when_all_recipients_fail():
    from bot import imessage_sender

    job = MagicMock()
    job.title = "Backend Dev"
    records = [_record(1, 10)]

    fake_job_cls = MagicMock()
    fake_job_cls.from_db_row.return_value = job

    async def run():
        with patch("bot.imessage_sender.adb._fetchone", new=AsyncMock(return_value={"id": 10})), \
             patch("bot.imessage_sender.Job", fake_job_cls), \
             patch("bot.imessage_sender.format_job_message", return_value="<b>Job</b>"), \
             patch("bot.imessage_sender.imessage.send_to_recipients",
                   return_value={"sent": 0, "failed": 2}), \
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

def test_scheduler_routes_group_records_to_imessage_and_skips_dms():
    from core import delivery_scheduler

    records = [_record(1, 10)]

    async def run():
        with patch("core.config.DELIVERY_CHANNEL", "imessage"), \
             patch("core.delivery_scheduler.recover_stale_deliveries",
                   return_value={"recovered": 0, "dead_lettered": 0}), \
             patch("core.delivery_scheduler._claim", return_value=records) as claim, \
             patch("bot.imessage_sender.deliver_imessage_records",
                   new=AsyncMock(return_value={"sent": 1, "failed": 0, "skipped": 0})) as im_deliver, \
             patch("core.delivery_scheduler.deliver_group_topic_records",
                   new=AsyncMock()) as tg_deliver, \
             patch("core.delivery_scheduler.deliver_subscriber_dm_records",
                   new=AsyncMock()) as dm_deliver:
            # One pass: after the iMessage batch, next claim returns nothing.
            claim.side_effect = [records, []]
            stats = await delivery_scheduler.run_delivery_cycle(None, max_cycle_seconds=30)
            return stats, im_deliver, tg_deliver, dm_deliver, claim

    stats, im_deliver, tg_deliver, dm_deliver, claim = asyncio.run(run())

    im_deliver.assert_awaited_once()
    tg_deliver.assert_not_awaited()
    dm_deliver.assert_not_awaited()
    # Only the group-topic claim ran; subscriber DMs are never claimed.
    assert all(c.args[1] == "group_topic" for c in claim.call_args_list)
    assert stats["group_topic_sent"] == 1


# --- Enqueue gating ----------------------------------------------------------

def test_enqueue_skips_subscriber_dms_in_imessage_mode():
    from core import delivery_queue

    with patch("core.config.DELIVERY_CHANNEL", "imessage"), \
         patch("core.delivery_queue.build_group_topic_deliveries", return_value=[]) as group, \
         patch("core.delivery_queue.build_subscriber_dm_deliveries") as dm_builder, \
         patch("core.delivery_queue._insert_delivery_rows", return_value=0):
        result = delivery_queue.enqueue_job_deliveries([("job", 1)])

    group.assert_called_once()
    dm_builder.assert_not_called()
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
