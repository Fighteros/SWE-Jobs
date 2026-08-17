"""Tests for bot.polling.PollingSupervisor: startup retries, in-process recovery, escalation."""

import asyncio

import pytest

from bot import polling as polling_mod
from bot.polling import PollingSupervisor


class FakeUpdater:
    def __init__(self, running=True):
        self.running = running


class FakeApp:
    def __init__(self):
        self.updater = FakeUpdater()


class Recorder:
    def __init__(self):
        self.created = 0
        self.started = []
        self.stopped = []
        self.exits = []


def make_supervisor(rec, *, factory=None, start=None, stop=None, **kwargs):
    def default_factory():
        rec.created += 1
        return FakeApp()

    async def default_start(app):
        rec.started.append(app)

    async def default_stop(app):
        rec.stopped.append(app)

    defaults = {"check_interval": 0.001, "backoff_initial": 0.0}
    defaults.update(kwargs)

    return PollingSupervisor(
        app_factory=factory or default_factory,
        start_fn=start or default_start,
        stop_fn=stop or default_stop,
        exit_fn=lambda code: rec.exits.append(code),
        **defaults,
    )


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

async def test_startup_succeeds_first_try():
    rec = Recorder()
    sup = make_supervisor(rec)

    assert await sup._start_with_retries() is True
    assert rec.created == 1
    assert len(rec.started) == 1
    assert sup._app is not None
    assert sup._start_attempts == 1


async def test_startup_retries_then_succeeds():
    rec = Recorder()

    def flaky_factory():
        rec.created += 1
        if rec.created < 3:
            raise ConnectionError("network not up yet")
        return FakeApp()

    sup = make_supervisor(rec, factory=flaky_factory)

    assert await sup._start_with_retries() is True
    assert rec.created == 3
    assert len(rec.started) == 1  # only the successful instance was started


async def test_run_exits_when_startup_retries_exhausted():
    rec = Recorder()

    def bad_factory():
        rec.created += 1
        raise ConnectionError("Telegram unreachable")

    sup = make_supervisor(rec, factory=bad_factory, startup_retries=3)

    await sup.run()

    assert rec.created == 3
    assert rec.exits == [1]


# ---------------------------------------------------------------------------
# Supervision / recovery
# ---------------------------------------------------------------------------

async def test_stuck_polling_rebuilds_in_process(monkeypatch):
    rec = Recorder()
    sup = make_supervisor(rec)
    assert await sup._start_with_retries() is True
    first_app = sup._app

    # Stuck exactly on the first liveness check, healthy afterwards.
    stuck_calls = {"n": 0}

    def fake_stuck(threshold=300.0):
        stuck_calls["n"] += 1
        return stuck_calls["n"] == 1

    monkeypatch.setattr(polling_mod.bot_app, "polling_stuck", fake_stuck)

    loop = asyncio.create_task(sup._supervise_loop())
    await asyncio.sleep(0.05)  # several check intervals elapse

    sup._stopping = True
    await loop

    assert rec.created == 2  # fresh Application for the rebuild
    assert sup._app is not first_app
    assert sup._restarts == 1
    assert rec.stopped == [first_app]  # old instance torn down gracefully
    assert rec.exits == []  # healed in-process, no process exit


async def test_dead_updater_rebuilds_in_process():
    rec = Recorder()
    sup = make_supervisor(rec)
    assert await sup._start_with_retries() is True
    first_app = sup._app
    first_app.updater.running = False  # poller died without being stuck

    loop = asyncio.create_task(sup._supervise_loop())
    await asyncio.sleep(0.05)

    sup._stopping = True
    await loop

    assert rec.created == 2
    assert sup._restarts == 1
    assert sup._app.updater.running is True
    assert rec.exits == []


async def test_recovery_exhaustion_exits_for_container_restart():
    rec = Recorder()

    def factory():
        rec.created += 1
        if rec.created > 1:
            raise ConnectionError("Telegram still unreachable")
        return FakeApp()

    sup = make_supervisor(rec, factory=factory, recovery_attempts=2)
    assert await sup._start_with_retries() is True
    sup._app.updater.running = False  # trigger a recovery that keeps failing

    loop = asyncio.create_task(sup._supervise_loop())
    await loop  # returns after _fatal

    assert rec.exits == [1]
    assert rec.created == 3  # initial start + 2 failed recovery attempts
    assert sup._restarts == 0


async def test_supervise_loop_ignores_healthy_poller():
    rec = Recorder()
    sup = make_supervisor(rec)
    assert await sup._start_with_retries() is True

    loop = asyncio.create_task(sup._supervise_loop())
    await asyncio.sleep(0.02)

    sup._stopping = True
    await loop

    assert rec.created == 1  # nothing rebuilt
    assert rec.stopped == []
    assert rec.exits == []


# ---------------------------------------------------------------------------
# Shutdown / teardown
# ---------------------------------------------------------------------------

async def test_stop_is_graceful_and_idempotent():
    rec = Recorder()
    sup = make_supervisor(rec)
    assert await sup._start_with_retries() is True
    app = sup._app

    await sup.stop()
    await sup.stop()  # second call must be a no-op

    assert rec.stopped == [app]
    assert rec.exits == []
    assert sup._app is None
    assert sup.status()["running"] is False


async def test_fatal_is_suppressed_during_shutdown():
    rec = Recorder()
    sup = make_supervisor(rec)

    sup._stopping = True
    sup._fatal("deliberate stop")

    assert rec.exits == []


async def test_run_cancellation_tears_down():
    rec = Recorder()
    sup = make_supervisor(rec, check_interval=0.05)

    task = asyncio.create_task(sup.run())
    await asyncio.sleep(0.01)  # startup completes
    assert len(rec.started) == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert rec.stopped == rec.started  # finally-block teardown ran


async def test_teardown_timeout_abandons_hung_instance():
    rec = Recorder()

    async def hanging_stop(app):
        rec.stopped.append(app)
        await asyncio.sleep(999)

    sup = make_supervisor(rec, stop=hanging_stop, stop_timeout=0.01)
    assert await sup._start_with_retries() is True

    await sup._teardown()  # must return despite the hang

    assert sup._app is None
    assert rec.stopped == rec.started


async def test_teardown_survives_stop_error():
    rec = Recorder()

    async def failing_stop(app):
        rec.stopped.append(app)
        raise RuntimeError("stop exploded")

    sup = make_supervisor(rec, stop=failing_stop)
    assert await sup._start_with_retries() is True

    await sup._teardown()  # must not raise

    assert sup._app is None


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

async def test_status_reflects_lifecycle():
    rec = Recorder()
    sup = make_supervisor(rec)

    before = sup.status()
    assert before["running"] is False
    assert before["restarts"] == 0

    assert await sup._start_with_retries() is True
    running = sup.status()
    assert running["running"] is True
    assert running["supervisor_alive"] is True
    assert "last_success_seconds_ago" in running

    await sup.stop()
    assert sup.status()["running"] is False


def test_get_supervisor_status_without_supervisor():
    status = polling_mod.get_supervisor_status()
    assert status == {"running": False} or "running" in status
