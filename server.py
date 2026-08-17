"""
FastAPI server + supervised Telegram bot polling + scheduled job fetcher.
All run in the same asyncio event loop.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn

from core.logging_config import setup_logging
from api.app import create_app
from core.config import FETCH_INTERVAL_MINUTES
from bot.polling import PollingSupervisor

setup_logging()
log = logging.getLogger(__name__)

_scheduler_task: asyncio.Task | None = None
_supervisor_task: asyncio.Task | None = None
_supervisor: PollingSupervisor | None = None


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


@asynccontextmanager
async def lifespan(app):
    """
    Startup: launch supervised bot polling + job scheduler.
    Shutdown: cancel both, tear the bot down, close DB.

    Polling is supervised by bot.polling.PollingSupervisor: transient Telegram
    outages (502s, timeouts) heal via PTB's own retries, a stuck/dead poller is
    rebuilt in-process with fresh network state, and only unrecoverable states
    exit the process so Docker (restart: unless-stopped) restarts the stack.
    """
    global _supervisor, _supervisor_task, _scheduler_task

    _supervisor = PollingSupervisor()
    _supervisor_task = asyncio.create_task(
        _supervisor.run(), name="telegram-polling-supervisor"
    )

    _scheduler_task = asyncio.create_task(_job_fetch_loop(), name="job-fetch-scheduler")
    log.info("Job fetch scheduler started alongside FastAPI")

    yield

    # Stop the supervisor first so the deliberate updater stop isn't treated
    # as a crash. run() also tears down in its finally block; stop() is
    # idempotent.
    for task in (_supervisor_task, _scheduler_task):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    if _supervisor:
        await _supervisor.stop()

    try:
        from core.db import close_pool
        close_pool()
    except Exception:
        pass


app = create_app(lifespan=lifespan)

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
