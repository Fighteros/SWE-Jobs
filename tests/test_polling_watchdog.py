"""Tests for bot.app's polling liveness tracking, wrapper, and error handler."""

import asyncio

import bot.app as app_mod


def _reset():
    app_mod.reset_polling_state()


def test_no_errors_not_stuck():
    _reset()
    assert app_mod.polling_stuck() is False


def test_single_error_not_stuck():
    _reset()
    app_mod._on_polling_error(Exception("Bad Gateway"))
    assert app_mod.polling_stuck(threshold=300) is False


def test_continuous_errors_past_threshold_are_stuck(monkeypatch):
    _reset()
    t = [1000.0]
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: t[0])

    app_mod._on_polling_error(Exception("Bad Gateway"))  # streak starts at t=1000
    for _ in range(6):
        t[0] += 60  # PTB retries roughly every poll cycle; keep the streak alive
        app_mod._on_polling_error(Exception("Bad Gateway"))
    # streak is now 360s old, well past a 300s threshold, and still actively failing

    assert app_mod.polling_stuck(threshold=300) is True


def test_success_resets_streak(monkeypatch):
    """A successful get_updates (via _on_polling_success) clears the streak outright."""
    _reset()
    t = [1000.0]
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: t[0])

    app_mod._on_polling_error(Exception("Bad Gateway"))
    t[0] += 400  # would be "stuck" if the streak were still open
    app_mod._on_polling_success()

    assert app_mod.polling_stuck(threshold=300) is False


def test_intermittent_failures_separated_by_success_are_not_one_outage(monkeypatch):
    """Failures with a real success in between must not accumulate into one continuous streak."""
    _reset()
    t = [1000.0]
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: t[0])

    for _ in range(10):
        app_mod._on_polling_error(Exception("Bad Gateway"))
        t[0] += 30
        app_mod._on_polling_success()  # recovers each time — never a continuous outage
        t[0] += 30

    assert app_mod.polling_stuck(threshold=300) is False


def test_reset_polling_state_clears_streak(monkeypatch):
    _reset()
    t = [1000.0]
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: t[0])

    app_mod._on_polling_error(Exception("Bad Gateway"))
    t[0] += 400
    assert app_mod.polling_stuck(threshold=300) is True

    app_mod.reset_polling_state()
    assert app_mod.polling_stuck(threshold=300) is False
    assert app_mod.polling_status()["error_streak_seconds"] == 0.0


def test_polling_status_reports_streak_and_last_success(monkeypatch):
    _reset()
    t = [1000.0]
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: t[0])

    app_mod._on_polling_error(Exception("Bad Gateway"))
    t[0] += 10
    status = app_mod.polling_status()
    assert status["stuck"] is False
    assert status["error_streak_seconds"] == 10.0
    assert status["last_success_seconds_ago"] is None  # no success yet

    t[0] += 5
    app_mod._on_polling_success()
    t[0] += 3
    status = app_mod.polling_status()
    assert status["stuck"] is False
    assert status["error_streak_seconds"] == 0.0
    assert status["last_success_seconds_ago"] == 3.0


# ---------------------------------------------------------------------------
# Liveness wrapper
# ---------------------------------------------------------------------------

class _FakeBot:
    async def get_updates(self, **kwargs):
        return []


class _FakeApp:
    def __init__(self):
        self.bot = _FakeBot()


async def test_liveness_wrapper_resets_streak_on_success():
    app = _FakeApp()
    app_mod._wrap_get_updates_for_liveness(app)

    app_mod._error_streak_started_at = 123.0  # pretend polling was failing
    await app.bot.get_updates(timeout=30)

    assert app_mod._error_streak_started_at == 0.0
    _reset()


async def test_liveness_wrapper_is_idempotent():
    """Wrapping the same bot class twice must not nest trackers."""
    app = _FakeApp()
    app_mod._wrap_get_updates_for_liveness(app)
    first = _FakeBot.get_updates

    app_mod._wrap_get_updates_for_liveness(app)

    assert _FakeBot.get_updates is first
    assert getattr(_FakeBot.get_updates, "_is_liveness_tracked", False)
    assert getattr(app.bot.get_updates, "_is_liveness_tracked", False)
    _reset()


async def test_liveness_wrapper_survives_instance_replacement():
    """A fresh Application gets a fresh bot instance; tracking must still apply."""
    app_mod._wrap_get_updates_for_liveness(_FakeApp())
    fresh_app = _FakeApp()

    app_mod._error_streak_started_at = 123.0
    await fresh_app.bot.get_updates(timeout=30)

    assert app_mod._error_streak_started_at == 0.0
    _reset()


async def test_liveness_wrapper_installs_on_slotted_bot_class():
    """PTB's ExtBot forbids instance attribute assignment; the wrap must still work."""
    class _SlottedBot:
        __slots__ = ()

        def __setattr__(self, key, value):
            raise AttributeError(f"Attribute `{key}` of class `_SlottedBot` can't be set!")

        async def get_updates(self, **kwargs):
            return []

    class _SlottedApp:
        def __init__(self):
            self.bot = _SlottedBot()

    app = _SlottedApp()
    app_mod._wrap_get_updates_for_liveness(app)

    app_mod._error_streak_started_at = 123.0
    await app.bot.get_updates(timeout=30)

    assert app_mod._error_streak_started_at == 0.0
    assert getattr(app.bot.get_updates, "_is_liveness_tracked", False)
    _reset()


# ---------------------------------------------------------------------------
# Global update error handler
# ---------------------------------------------------------------------------

class _FakeChat:
    id = 42


class _FakeUpdate:
    effective_chat = _FakeChat()


class _FakeBotSender:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


def _make_context(bot, error=None):
    class _Ctx:
        pass

    ctx = _Ctx()
    ctx.bot = bot
    ctx.error = error or RuntimeError("boom")
    return ctx


async def test_update_error_handler_replies_generically(caplog):
    bot = _FakeBotSender()
    ctx = _make_context(bot)

    with caplog.at_level("ERROR"):
        await app_mod._handle_update_error(_FakeUpdate(), ctx)

    assert len(bot.sent) == 1
    chat_id, text = bot.sent[0]
    assert chat_id == 42
    assert "boom" not in text  # internals never leaked to the user
    assert any("boom" in r.message or r.exc_info for r in caplog.records)


async def test_update_error_handler_survives_send_failure(caplog):
    class _FailingBot:
        async def send_message(self, chat_id, text):
            from telegram.error import NetworkError

            raise NetworkError("can't reach user")

    ctx = _make_context(_FailingBot())

    with caplog.at_level("ERROR"):
        await app_mod._handle_update_error(_FakeUpdate(), ctx)  # must not raise

    assert any(r.levelname == "ERROR" for r in caplog.records)


async def test_update_error_handler_skips_reply_without_chat():
    bot = _FakeBotSender()
    ctx = _make_context(bot)

    await app_mod._handle_update_error(None, ctx)  # must not raise

    assert bot.sent == []
