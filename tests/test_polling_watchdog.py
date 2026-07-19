"""Tests for bot.app's polling error-streak tracking (used by server.py's watchdog)."""

import bot.app as app_mod


def _reset():
    app_mod._last_error_at = 0.0
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


def test_recovered_stream_is_not_stuck(monkeypatch):
    """A gap longer than _ERROR_STREAK_GAP means polling recovered — new streak, not stuck."""
    _reset()
    t = [1000.0]
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: t[0])

    app_mod._on_polling_error(Exception("Bad Gateway"))
    t[0] += 400  # long gap: polling succeeded quietly in between, then failed again
    app_mod._on_polling_error(Exception("Bad Gateway"))

    assert app_mod.polling_stuck(threshold=300) is False
