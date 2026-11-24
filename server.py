"""
FastAPI server + supervised Telegram bot polling + scheduled job fetcher +
independent delivery scheduler. All run in the same asyncio event loop.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager

import uvicorn
from telegram import Bot

from core.logging_config import setup_logging
from api.app import create_app
from core.config import (
    ALERT_CONSECUTIVE_FAILURES,
    DELIVERY_CHANNEL,
    FETCH_INTERVAL_MINUTES,
    DELIVERY_INTERVAL_SECONDS,
    DELIVERY_IDLE_SLEEP_SECONDS,
    IMESSAGE_SIDECAR_URL,
    STARTUP_ALERT,
    TELEGRAM_BOT_TOKEN,
)
from core.delivery_scheduler import run_delivery_cycle
from bot.polling import PollingSupervisor

setup_logging()
log = logging.getLogger(__name__)

_scheduler_task: asyncio.Task | None = None
_delivery_task: asyncio.Task | None = None
_supervisor_task: asyncio.Task | None = None
_supervisor: PollingSupervisor | None = None

_fetch_lock = asyncio.Lock()
_delivery_lock = asyncio.Lock()


async def _job_fetch_loop():
    """Run the ingestion pipeline on a fixed interval. Fetch cycles do not overlap."""
    from main import main as run_pipeline

    from core.monitoring import notify_admin

    interval = FETCH_INTERVAL_MINUTES * 60
    log.info(f"Fetch scheduler started — running every {FETCH_INTERVAL_MINUTES} min")

    failures = 0
    while True:
        if _fetch_lock.locked():
            log.warning("Fetch scheduler: previous cycle still running, skipping this tick")
        else:
            async with _fetch_lock:
                try:
                    log.info("Fetch scheduler: starting ingestion run…")
                    await run_pipeline()
                    log.info("Fetch scheduler: run complete")
                    if failures >= ALERT_CONSECUTIVE_FAILURES:
                        await notify_admin(
                            f"✅ <b>Job fetch recovered</b> after {failures} consecutive failed runs."
                        )
                    failures = 0
                except Exception:
                    failures += 1
                    log.exception("Fetch scheduler: run failed (will retry next interval)")
                    if failures == ALERT_CONSECUTIVE_FAILURES:
                        await notify_admin(
                            "🚨 <b>Job fetch failing</b>\n"
                            f"{failures} consecutive ingestion runs failed — new jobs are "
                            "not being collected. See server logs."
                        )
        await asyncio.sleep(interval)


async def _delivery_loop():
    """
    Run the delivery scheduler on a fixed interval. Delivery cycles do not
    overlap. Uses PostgreSQL row locks for worker-level protection.
    """
    log.info(
        f"Delivery scheduler started — running every {DELIVERY_INTERVAL_SECONDS}s"
    )

    from core import imessage as _imessage

    use_imessage = DELIVERY_CHANNEL == "imessage"
    channel_label = "iMessage" if use_imessage else "Telegram"

    if use_imessage and not IMESSAGE_SIDECAR_URL:
        log.warning(
            "DELIVERY_CHANNEL=imessage but IMESSAGE_SIDECAR_URL is not set "
            "— delivery scheduler will sleep forever"
        )
        while True:
            await asyncio.sleep(DELIVERY_INTERVAL_SECONDS)
    if not use_imessage and not TELEGRAM_BOT_TOKEN:
        log.warning("No TELEGRAM_BOT_TOKEN — delivery scheduler will sleep forever")
        while True:
            await asyncio.sleep(DELIVERY_INTERVAL_SECONDS)

    from core.monitoring import notify_admin

    # iMessage mode needs no Telegram Bot; Telegram mode cannot run without one.
    from contextlib import nullcontext
    bot_ctx = nullcontext(None) if use_imessage else Bot(token=TELEGRAM_BOT_TOKEN)
    failures = 0
    async with bot_ctx as bot:
        while True:
            if _delivery_lock.locked():
                log.warning("Delivery scheduler: previous cycle still running, skipping this tick")
                await asyncio.sleep(DELIVERY_INTERVAL_SECONDS)
                continue

            cycle_start = time.monotonic()
            stats = {}
            async with _delivery_lock:
                try:
                    log.info("Delivery scheduler: starting cycle…")
                    stats = await run_delivery_cycle(bot)
                    if failures >= ALERT_CONSECUTIVE_FAILURES:
                        await notify_admin(
                            f"✅ <b>{channel_label} delivery recovered</b> after {failures} consecutive failed cycles.",
                            bot,
                        )
                    failures = 0
                except Exception:
                    failures += 1
                    log.exception("Delivery scheduler: cycle failed (will retry next interval)")
                    if failures == ALERT_CONSECUTIVE_FAILURES:
                        await notify_admin(
                            f"🚨 <b>{channel_label} delivery failing</b>\n"
                            f"{failures} consecutive delivery cycles failed — queued jobs are "
                            f"NOT reaching {channel_label}. See server logs.",
                            bot,
                        )

            total_work = (
                stats.get("group_topic_sent", 0)
                + stats.get("group_topic_failed", 0)
                + stats.get("group_topic_skipped", 0)
                + stats.get("dm_sent", 0)
                + stats.get("dm_failed", 0)
                + stats.get("dm_deferred", 0)
                + stats.get("stale_recovered", 0)
                + stats.get("stale_dead_lettered", 0)
            )

            elapsed = time.monotonic() - cycle_start
            if total_work == 0:
                await asyncio.sleep(DELIVERY_IDLE_SLEEP_SECONDS)
            else:
                await asyncio.sleep(max(0, DELIVERY_INTERVAL_SECONDS - elapsed))


@asynccontextmanager
async def lifespan(app):
    """
    Startup: launch supervised bot polling + fetch scheduler + delivery scheduler.
    Shutdown: cancel all, tear the bot down, close DB.

    Polling is supervised by bot.polling.PollingSupervisor: transient Telegram
    outages (502s, timeouts) heal via PTB's own retries, a stuck/dead poller is
    rebuilt in-process with fresh network state, and only unrecoverable states
    exit the process so Docker (restart: unless-stopped) restarts the stack.
    """
    global _supervisor, _supervisor_task, _scheduler_task, _delivery_task

    if TELEGRAM_BOT_TOKEN:
        _supervisor = PollingSupervisor()
        _supervisor_task = asyncio.create_task(
            _supervisor.run(), name="telegram-polling-supervisor"
        )
    else:
        # iMessage-only deployments run without the Telegram bot entirely.
        log.info("No TELEGRAM_BOT_TOKEN — Telegram bot polling disabled")

    _scheduler_task = asyncio.create_task(_job_fetch_loop(), name="job-fetch-scheduler")
    _delivery_task = asyncio.create_task(_delivery_loop(), name="job-delivery-scheduler")
    log.info("Fetch and delivery schedulers started alongside FastAPI")

    if STARTUP_ALERT:
        # Fire-and-forget: makes container restarts (crashes, OOM kills,
        # deploys) visible in Telegram instead of silent.
        async def _announce_start():
            try:
                from core.monitoring import notify_admin

                await notify_admin(
                    "✅ <b>SWE-Jobs backend started</b>\n"
                    "Bot polling, fetch and delivery schedulers are running."
                )
            except Exception:
                log.exception("Failed to send startup alert")

        asyncio.create_task(_announce_start())

    yield

    # Stop the supervisor first so the deliberate updater stop isn't treated
    # as a crash. run() also tears down in its finally block; stop() is
    # idempotent.
    for task in (_supervisor_task, _scheduler_task, _delivery_task):
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
