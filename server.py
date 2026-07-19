"""
FastAPI server + Telegram bot polling + scheduled job fetcher.
All run in the same asyncio event loop.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn

from core.logging_config import setup_logging
from api.app import create_app
from core.config import FETCH_INTERVAL_MINUTES

setup_logging()
log = logging.getLogger(__name__)

_scheduler_task: asyncio.Task | None = None
_polling_task: asyncio.Task | None = None
_shutting_down = False

# How often the watchdog re-checks that Telegram polling is still alive.
_POLL_WATCHDOG_INTERVAL = 30  # seconds


async def _job_fetch_loop():
    """Run the main fetch-and-send pipeline on a fixed interval."""
    from main import main as run_pipeline

    interval = FETCH_INTERVAL_MINUTES * 60
    log.info(f"Job scheduler started — running every {FETCH_INTERVAL_MINUTES} min")

    while True:
        try:
            log.info("Scheduler: starting job fetch run…")
            await run_pipeline()
            log.info("Scheduler: run complete")
        except Exception:
            log.exception("Scheduler: run failed (will retry next interval)")
        await asyncio.sleep(interval)


async def _polling_watchdog():
    """
    Start Telegram polling and keep it alive.

    PTB retries network errors internally, but if its polling task ever dies (or
    fails to start), uvicorn keeps this process alive — so the bot would be
    silently down until a manual restart, and Docker's restart policy never
    fires. This watchdog starts polling (retrying transient startup failures),
    then exits the process if the updater stops unexpectedly, so Docker
    (restart: unless-stopped) brings the whole stack back.

    Note: this catches a *dead* poller and a poller stuck in a continuous
    error-retry streak (e.g. host can't reach Telegram) — see bot.app.polling_stuck.
    Loop blocking is prevented separately by running all DB I/O off-loop
    (see core/db_async.py).
    """
    from bot.app import start_polling, get_app, polling_stuck

    backoff = 5
    for attempt in range(1, 6):
        try:
            await start_polling()
            break
        except Exception:
            log.exception(
                "Bot polling failed to start (attempt %d/5); retrying in %ds",
                attempt, backoff,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
    else:
        log.critical("Bot polling could not start after retries — exiting for restart")
        os._exit(1)

    log.info("Bot polling started alongside FastAPI")

    # Supervise: if the updater stops unexpectedly, exit so Docker restarts us.
    bot_app = get_app()
    while not _shutting_down:
        await asyncio.sleep(_POLL_WATCHDOG_INTERVAL)
        if _shutting_down:
            break
        updater = bot_app.updater
        if updater is None or not updater.running:
            log.critical("Telegram updater stopped unexpectedly — exiting for restart")
            os._exit(1)
        if polling_stuck():
            log.critical("Telegram polling stuck in an error retry loop — exiting for restart")
            os._exit(1)


@asynccontextmanager
async def lifespan(app):
    """Startup: launch supervised bot polling + job scheduler. Shutdown: cancel both, close DB."""
    global _scheduler_task, _polling_task, _shutting_down

    # Start Telegram bot polling under a watchdog that restarts the process if it dies.
    _polling_task = asyncio.create_task(_polling_watchdog())

    # Start the periodic job fetcher
    _scheduler_task = asyncio.create_task(_job_fetch_loop())
    log.info("Job fetch scheduler started alongside FastAPI")

    yield

    # Shutdown
    _shutting_down = True

    # Stop the watchdog first so the deliberate updater stop isn't treated as a crash.
    if _polling_task and not _polling_task.done():
        _polling_task.cancel()
        try:
            await _polling_task
        except asyncio.CancelledError:
            pass

    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
        log.info("Job fetch scheduler stopped")

    try:
        from bot.app import stop_polling
        await stop_polling()
    except Exception:
        pass

    try:
        from core.db import close_pool
        close_pool()
    except Exception:
        pass


app = create_app(lifespan=lifespan)

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
