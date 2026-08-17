"""
Supervised Telegram polling lifecycle.

PollingSupervisor owns the bot Application end-to-end:

- Brief polling errors (Telegram 502s, timeouts) are retried by PTB itself;
  the supervisor only watches.
- A continuous failure streak past TELEGRAM_POLL_STUCK_THRESHOLD, or a dead
  updater, triggers an in-process recovery: full teardown + fresh Application
  (fresh HTTP pools, fresh network state) + restart, with jittered backoff.
- After TELEGRAM_POLL_RECOVERY_ATTEMPTS consecutive failed recovery starts the
  process exits non-zero, so the container supervisor (restart: unless-stopped)
  brings the whole stack back.

This replaces the older "watchdog" that could only exit the process: transient
outages now heal without losing uptime, and only genuinely unrecoverable
states escalate to a container restart.
"""

import asyncio
import logging
import os
import random

from bot import app as bot_app

log = logging.getLogger(__name__)

# Module-level handle so /health can report supervisor state without wiring
# (api.app imports lazily). Exactly one supervisor exists per process.
_supervisor: "PollingSupervisor | None" = None


def get_supervisor_status() -> dict:
    """Snapshot of supervised polling health for the /health endpoint."""
    if _supervisor is None:
        return {"running": False}
    return _supervisor.status()


class PollingSupervisor:
    """Start Telegram polling, keep it alive, rebuild it when it gets stuck."""

    def __init__(
        self,
        *,
        app_factory=None,
        start_fn=None,
        stop_fn=None,
        check_interval: int | None = None,
        stuck_threshold: int | None = None,
        startup_retries: int | None = None,
        recovery_attempts: int | None = None,
        backoff_initial: float | None = None,
        backoff_max: float | None = None,
        stop_timeout: float | None = None,
        exit_fn=None,
    ):
        from core import config

        self._app_factory = app_factory or bot_app.create_application
        self._start_fn = start_fn or bot_app.start_polling
        self._stop_fn = stop_fn or bot_app.stop_polling
        self._check_interval = check_interval if check_interval is not None else config.TELEGRAM_POLL_CHECK_INTERVAL
        self._stuck_threshold = stuck_threshold if stuck_threshold is not None else config.TELEGRAM_POLL_STUCK_THRESHOLD
        self._startup_retries = startup_retries if startup_retries is not None else config.TELEGRAM_POLL_STARTUP_RETRIES
        self._recovery_attempts = recovery_attempts if recovery_attempts is not None else config.TELEGRAM_POLL_RECOVERY_ATTEMPTS
        self._backoff_initial = backoff_initial if backoff_initial is not None else config.TELEGRAM_POLL_BACKOFF_INITIAL
        self._backoff_max = backoff_max if backoff_max is not None else config.TELEGRAM_POLL_BACKOFF_MAX
        self._stop_timeout = stop_timeout if stop_timeout is not None else config.TELEGRAM_POLL_STOP_TIMEOUT
        self._exit = exit_fn or os._exit

        self._app = None
        self._stopping = False
        self._restarts = 0
        self._start_attempts = 0

    # ------------------------------------------------------------------
    # Main entrypoint
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start polling (with retries) and supervise until stopped/cancelled."""
        global _supervisor
        _supervisor = self
        try:
            if not await self._start_with_retries():
                self._fatal(
                    f"Bot polling could not start after {self._startup_retries} attempts"
                )
                return
            log.info("Bot polling started alongside FastAPI")
            await self._supervise_loop()
        except asyncio.CancelledError:
            log.info("Polling supervisor cancelled — shutting bot down")
            raise
        finally:
            await self._teardown()

    async def _start_with_retries(self) -> bool:
        """Try to reach a polling state; retry with backoff. True on success."""
        for attempt in range(1, self._startup_retries + 1):
            if self._stopping:
                return False
            if await self._start_once():
                return True
            if attempt < self._startup_retries:
                await self._backoff(attempt)
        return False

    async def _start_once(self) -> bool:
        """Create a fresh Application and bring it into polling mode."""
        self._start_attempts += 1
        bot_app.reset_polling_state()
        try:
            app = self._app_factory()
            await self._start_fn(app)
        except Exception:
            log.exception("Telegram polling failed to start (attempt %d)", self._start_attempts)
            return False
        self._app = app
        return True

    async def _supervise_loop(self) -> None:
        """Rebuild the poller when it dies or gets stuck in an error loop."""
        while not self._stopping:
            await asyncio.sleep(self._check_interval)
            if self._stopping:
                break

            app = self._app
            updater = app.updater if app is not None else None
            dead = updater is None or not updater.running
            stuck = bot_app.polling_stuck(self._stuck_threshold)

            if not dead and not stuck:
                continue

            reason = (
                "Telegram updater stopped unexpectedly"
                if dead
                else "Telegram polling stuck in a continuous error loop"
            )
            log.warning("%s — attempting in-process recovery", reason)
            if not await self._recover(reason):
                self._fatal(f"{reason}; recovery failed")
                return

    async def _recover(self, reason: str) -> bool:
        """Tear the current instance down and start a fresh one. True on success."""
        await self._teardown()
        for attempt in range(1, self._recovery_attempts + 1):
            if self._stopping:
                return False
            await self._backoff(attempt)
            if await self._start_once():
                self._restarts += 1
                log.warning(
                    "%s — recovered with a fresh polling instance (restart #%d)",
                    reason, self._restarts,
                )
                return True
        return False

    # ------------------------------------------------------------------
    # Shutdown / escalation
    # ------------------------------------------------------------------

    async def stop(self) -> None:
        """Graceful shutdown (lifespan); also guards against deliberate-stop-as-crash."""
        self._stopping = True
        await self._teardown()

    async def _teardown(self) -> None:
        """Stop the current Application, if any. Safe to call repeatedly."""
        app, self._app = self._app, None
        if app is None:
            return
        try:
            await asyncio.wait_for(self._stop_fn(app), timeout=self._stop_timeout)
        except asyncio.TimeoutError:
            log.error(
                "Timed out stopping the Telegram app after %.1fs — abandoning instance "
                "(fresh instance gets fresh HTTP pools)",
                self._stop_timeout,
            )
        except Exception:
            log.exception("Error stopping the Telegram app — continuing with fresh instance")

    def _fatal(self, reason: str) -> None:
        """Exit so the container supervisor restarts the stack."""
        if self._stopping:
            return
        log.critical("%s — exiting for container restart", reason)
        self._exit(1)

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    async def _backoff(self, attempt: int) -> None:
        """Exponential backoff with jitter (50–100% of the target delay)."""
        delay = min(self._backoff_initial * (2 ** (attempt - 1)), self._backoff_max)
        delay *= 0.5 + random.random() * 0.5
        await asyncio.sleep(delay)

    def status(self) -> dict:
        """Supervisor + liveness snapshot for the /health endpoint."""
        updater = self._app.updater if self._app is not None else None
        return {
            "running": not self._stopping and updater is not None and bool(updater.running),
            "restarts": self._restarts,
            "start_attempts": self._start_attempts,
            "supervisor_alive": True,
            **bot_app.polling_status(),
        }
