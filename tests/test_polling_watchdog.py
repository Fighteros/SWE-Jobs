"""Tests for bot.app's polling error-streak tracking (used by server.py's watchdog)."""

import bot.app as app_mod


def _reset():
    app_mod._error_streak_started_at = 0.0


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
