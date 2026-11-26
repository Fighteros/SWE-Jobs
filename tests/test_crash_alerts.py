"""Tests for crash/health alerting: sync admin alerts, notify_admin, health
endpoint status codes, and the polling supervisor's alive flag + fatal alert."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from bot import polling as polling_mod
from bot.polling import PollingSupervisor
from core import monitoring


# ---------------------------------------------------------------------------
# send_admin_alert_sync
# ---------------------------------------------------------------------------

def test_sync_alert_skips_without_config():
    with patch.object(monitoring, "ADMIN_TELEGRAM_ID", ""), \
         patch.object(monitoring, "TELEGRAM_BOT_TOKEN", ""):
        assert monitoring.send_admin_alert_sync("hi") is False


def test_sync_alert_posts_to_telegram():
    resp = MagicMock(status=200)
    with patch.object(monitoring, "ADMIN_TELEGRAM_ID", "123"), \
         patch.object(monitoring, "TELEGRAM_BOT_TOKEN", "tok"), \
         patch("scrapling.fetchers.Fetcher.post", return_value=resp) as mock_post:
        assert monitoring.send_admin_alert_sync("backend down") is True
        mock_post.assert_called_once()
        call = mock_post.call_args
        assert call.args[0] == "https://api.telegram.org/bottok/sendMessage"
        assert call.kwargs["json"]["chat_id"] == 123


def test_sync_alert_never_raises():
    with patch.object(monitoring, "ADMIN_TELEGRAM_ID", "123"), \
         patch.object(monitoring, "TELEGRAM_BOT_TOKEN", "tok"), \
         patch("scrapling.fetchers.Fetcher.post", side_effect=ConnectionError("no network")):
        assert monitoring.send_admin_alert_sync("backend down") is False


# ---------------------------------------------------------------------------
# notify_admin
# ---------------------------------------------------------------------------

async def test_notify_admin_without_token_returns_false():
    with patch.object(monitoring, "TELEGRAM_BOT_TOKEN", ""):
        assert await monitoring.notify_admin("hi") is False


async def test_notify_admin_uses_passed_bot():
    bot = AsyncMock()
    with patch.object(monitoring, "ADMIN_TELEGRAM_ID", "123"):
        assert await monitoring.notify_admin("hello", bot) is True
        bot.send_message.assert_awaited_once()
        assert bot.send_message.call_args.kwargs["chat_id"] == 123


# ---------------------------------------------------------------------------
# /health status codes
# ---------------------------------------------------------------------------

def test_health_unhealthy_when_supervisor_not_running():
    from api.app import create_app

    with patch("bot.polling.supervisor_alive", return_value=False), \
         patch("bot.polling.get_supervisor_status", return_value={"running": False}):
        client = TestClient(create_app())
        resp = client.get("/health")
        assert resp.status_code == 503
        assert resp.json()["status"] == "unhealthy"


def test_health_ok_while_supervisor_alive():
    from api.app import create_app

    with patch("bot.polling.supervisor_alive", return_value=True), \
         patch("bot.polling.get_supervisor_status", return_value={"running": False}):
        # Mid-recovery still counts as alive: the supervisor is on it.
        client = TestClient(create_app())
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Supervisor alive flag + fatal alert
# ---------------------------------------------------------------------------

class _FakeApp:
    def __init__(self):
        self.updater = MagicMock(running=True)


async def test_supervisor_alive_flag_tracks_run_lifecycle():
    assert polling_mod.supervisor_alive() is False

    sup = PollingSupervisor(
        app_factory=lambda: _FakeApp(),
        start_fn=AsyncMock(),
        stop_fn=AsyncMock(),
        check_interval=0.01,
        exit_fn=lambda code: None,
    )
    task = asyncio.create_task(sup.run())
    await asyncio.sleep(0.05)
    assert polling_mod.supervisor_alive() is True

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert polling_mod.supervisor_alive() is False


async def test_fatal_sends_alert_before_exit():
    sup = PollingSupervisor(
        app_factory=lambda: _FakeApp(),
        start_fn=AsyncMock(),
        stop_fn=AsyncMock(),
        exit_fn=MagicMock(),
    )
    with patch("core.monitoring.send_admin_alert_sync") as mock_alert:
        sup._fatal("Telegram polling stuck; recovery failed")
        mock_alert.assert_called_once()
        assert "going down" in mock_alert.call_args.args[0]
    sup._exit.assert_called_once_with(1)


async def test_fatal_alert_failure_still_exits():
    sup = PollingSupervisor(
        app_factory=lambda: _FakeApp(),
        start_fn=AsyncMock(),
        stop_fn=AsyncMock(),
        exit_fn=MagicMock(),
    )
    with patch("core.monitoring.send_admin_alert_sync", side_effect=RuntimeError("boom")):
        sup._fatal("reason")
    sup._exit.assert_called_once_with(1)
