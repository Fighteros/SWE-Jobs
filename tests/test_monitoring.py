import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from core.monitoring import check_alerts


def _run(**overrides):
    run = {
        "jobs_fetched": 1,
        "finished_at": None,
        "started_at": None,
        "source_stats": {},
        "jobs_sent": 0,
    }
    run.update(overrides)
    return run


def test_check_alerts_ignores_dead_letter_deliveries():
    bot = object()
    run = _run()

    async def fetchone(query, _params):
        if "FROM bot_runs" in query:
            return run
        if "status = 'dead_letter'" in query:
            return {"count": 1}
        return None

    async def run_check():
        with patch("core.monitoring.adb._fetchone", side_effect=fetchone), \
             patch("core.monitoring.adb._fetchall", return_value=[]), \
             patch("core.db.ensure_circuit_alert_schema", return_value=True), \
             patch("core.monitoring.send_admin_alert", new_callable=AsyncMock) as send_alert:
            alerts = await check_alerts(bot, run_id=1)

        assert alerts == []
        send_alert.assert_not_awaited()

    asyncio.run(run_check())


def test_circuit_open_alert_sent_once_and_marked():
    """An open, not-yet-alerted circuit sends one alert and is marked."""
    bot = object()
    run = _run()
    open_until = datetime(2026, 11, 24, 1, 0, tzinfo=timezone.utc)
    executed = []

    async def fetchone(query, _params):
        if "FROM bot_runs" in query:
            return run
        return None

    async def fetchall(query, _params=()):
        if "circuit_open_until > now()" in query:
            return [{
                "source": "wuzzuf",
                "last_error": "Wuzzuf collection failed: Access challenge",
                "consecutive_failures": 3,
                "circuit_open_until": open_until,
            }]
        return []

    async def execute(query, params=()):
        executed.append((query, params))
        return None

    async def run_check():
        with patch("core.monitoring.adb._fetchone", side_effect=fetchone), \
             patch("core.monitoring.adb._fetchall", side_effect=fetchall), \
             patch("core.monitoring.adb._execute", side_effect=execute), \
             patch("core.db.ensure_circuit_alert_schema", return_value=True), \
             patch("core.monitoring.send_admin_alert", new_callable=AsyncMock) as send_alert:
            alerts = await check_alerts(bot, run_id=1)
            return alerts, send_alert

    alerts, send_alert = asyncio.run(run_check())

    assert len(alerts) == 1
    assert "Circuit breaker open" in alerts[0]
    assert "wuzzuf" in alerts[0]
    assert "muted" in alerts[0]
    send_alert.assert_awaited_once()
    # The source is marked as alerted so the next run stays quiet.
    assert any("circuit_open_alerted_at = now()" in q and p == ("wuzzuf",) for q, p in executed)


def test_circuit_open_within_cooldown_sends_nothing():
    """A circuit already alerted within the cooldown is filtered out by SQL."""
    bot = object()
    run = _run()
    seen_params = []

    async def fetchone(query, _params):
        if "FROM bot_runs" in query:
            return run
        return None

    async def fetchall(query, params=()):
        seen_params.append(params)
        return []  # cooldown filter in SQL excludes the already-alerted source

    async def run_check():
        with patch("core.monitoring.adb._fetchone", side_effect=fetchone), \
             patch("core.monitoring.adb._fetchall", side_effect=fetchall), \
             patch("core.monitoring.adb._execute", new_callable=AsyncMock) as execute, \
             patch("core.db.ensure_circuit_alert_schema", return_value=True), \
             patch("core.monitoring.ALERT_CIRCUIT_COOLDOWN_HOURS", 6), \
             patch("core.monitoring.send_admin_alert", new_callable=AsyncMock) as send_alert:
            alerts = await check_alerts(bot, run_id=1)
            return alerts, send_alert, execute

    alerts, send_alert, execute = asyncio.run(run_check())

    assert alerts == []
    send_alert.assert_not_awaited()
    execute.assert_not_awaited()
    # The cooldown hours are passed to the throttling query.
    assert any(p == (6,) for p in seen_params)


def test_circuit_recovery_alert_sent_and_cleared():
    """A source that was alerted-open and is healthy again gets one recovery alert."""
    bot = object()
    run = _run()
    executed = []

    async def fetchone(query, _params):
        if "FROM bot_runs" in query:
            return run
        return None

    async def fetchall(query, _params=()):
        if "circuit_open_until > now()" in query:
            return []
        if "consecutive_failures = 0" in query:
            return [{"source": "wuzzuf"}]
        return []

    async def execute(query, params=()):
        executed.append((query, params))
        return None

    async def run_check():
        with patch("core.monitoring.adb._fetchone", side_effect=fetchone), \
             patch("core.monitoring.adb._fetchall", side_effect=fetchall), \
             patch("core.monitoring.adb._execute", side_effect=execute), \
             patch("core.db.ensure_circuit_alert_schema", return_value=True), \
             patch("core.monitoring.send_admin_alert", new_callable=AsyncMock) as send_alert:
            alerts = await check_alerts(bot, run_id=1)
            return alerts, send_alert

    alerts, send_alert = asyncio.run(run_check())

    assert len(alerts) == 1
    assert "RECOVERED" in alerts[0]
    assert "wuzzuf" in alerts[0]
    send_alert.assert_awaited_once()
    assert any("circuit_open_alerted_at = NULL" in q and p == ("wuzzuf",) for q, p in executed)


def test_circuit_fallback_alerts_only_for_failures_within_the_run():
    """Without the alert-state column, only circuits opened this run alert."""
    bot = object()
    started = datetime(2026, 11, 23, 21, 30, tzinfo=timezone.utc)
    run = _run(started_at=started)
    seen_params = []

    async def fetchone(query, _params):
        if "FROM bot_runs" in query:
            return run
        return None

    async def fetchall(query, params=()):
        seen_params.append((query, params))
        if "last_failure_at >=" in query:
            return [{"source": "wuzzuf", "last_error": "Access challenge"}]
        return []

    async def run_check():
        with patch("core.monitoring.adb._fetchone", side_effect=fetchone), \
             patch("core.monitoring.adb._fetchall", side_effect=fetchall), \
             patch("core.monitoring.adb._execute", new_callable=AsyncMock) as execute, \
             patch("core.db.ensure_circuit_alert_schema", return_value=False), \
             patch("core.monitoring.send_admin_alert", new_callable=AsyncMock) as send_alert:
            alerts = await check_alerts(bot, run_id=1)
            return alerts, send_alert, execute

    alerts, send_alert, execute = asyncio.run(run_check())

    assert len(alerts) == 1
    assert "Circuit breaker open" in alerts[0]
    send_alert.assert_awaited_once()
    # No alert-state marking in fallback mode.
    execute.assert_not_awaited()
    # The query is scoped to failures since this run started.
    assert any(p == (started,) for _, p in seen_params)
