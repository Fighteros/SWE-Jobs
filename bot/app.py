"""
Telegram bot application setup.
Uses python-telegram-bot in polling mode with asyncio.
"""

import logging
import time
from telegram.error import TelegramError
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
)
from telegram.request import HTTPXRequest
from core.config import TELEGRAM_BOT_TOKEN

log = logging.getLogger(__name__)

_app: Application | None = None

# PTB retries polling errors (e.g. Telegram 502s) forever with backoff — that's
# fine for a transient blip, but if the host's path to Telegram is broken (DNS,
# firewall, routing) it retries forever with no recovery, and `updater.running`
# stays True the whole time so server.py's dead-poller watchdog never fires.
# Track how long polling has been failing *continuously* (i.e. with no successful
# get_updates in between — see _wrap_get_updates_for_liveness below) so the
# watchdog can force a restart (fresh network stack) when a streak runs too long.
_error_streak_started_at: float = 0.0


def _on_polling_error(exc: TelegramError) -> None:
    """error_callback for start_polling: log once (no traceback spam) and mark a streak."""
    global _error_streak_started_at
    if _error_streak_started_at == 0.0:
        _error_streak_started_at = time.monotonic()
    log.warning("Telegram polling error (auto-retrying): %s", exc)


def _on_polling_success() -> None:
    """Called after every successful get_updates (including empty long-poll timeouts)."""
    global _error_streak_started_at
    _error_streak_started_at = 0.0


def polling_stuck(threshold: float = 300.0) -> bool:
    """True if polling has been failing continuously for over `threshold` seconds."""
    if _error_streak_started_at == 0.0:
        return False
    return (time.monotonic() - _error_streak_started_at) > threshold


def _wrap_get_updates_for_liveness(app: Application) -> None:
    """
    Wrap bot.get_updates so a successful call (including empty long-poll timeouts,
    which don't raise) resets the error streak. Without this, intermittent failures
    separated by successes would otherwise look like one continuous outage.
    """
    original = app.bot.get_updates

    async def _tracked(*args, **kwargs):
        result = await original(*args, **kwargs)
        _on_polling_success()
        return result

    app.bot.get_updates = _tracked


def get_app() -> Application:
    """Get or create the bot Application singleton."""
    global _app
    if _app is None:
        if not TELEGRAM_BOT_TOKEN:
            raise RuntimeError("TELEGRAM_BOT_TOKEN not set")

        # Tuned HTTP clients for resilient long-polling on a self-hosted server.
        # PTB defaults (tiny pool, ~5s timeouts) make transient Telegram 502s and
        # connection resets surface as NetworkError(httpx.ReadError) more often
        # than necessary. PTB uses a *separate* request object for get_updates, so
        # both are configured; the get_updates read_timeout must exceed the
        # long-poll timeout (30s, set in start_polling).
        request = HTTPXRequest(
            connection_pool_size=8,
            connect_timeout=10.0,
            read_timeout=20.0,
            write_timeout=20.0,
            pool_timeout=10.0,
        )
        get_updates_request = HTTPXRequest(
            connection_pool_size=2,
            connect_timeout=10.0,
            read_timeout=40.0,
            write_timeout=20.0,
            pool_timeout=10.0,
        )
        _app = (
            Application.builder()
            .token(TELEGRAM_BOT_TOKEN)
            .request(request)
            .get_updates_request(get_updates_request)
            .build()
        )
        _register_handlers(_app)
        log.info("Telegram bot application created")
    return _app


def _register_handlers(app: Application) -> None:
    """Register all command and callback handlers."""
    from bot.commands import (
        cmd_start, cmd_help, cmd_subscribe, cmd_unsubscribe,
        cmd_mysubs, cmd_search, cmd_saved, cmd_stats, cmd_status, cmd_top,
        cmd_salary, cmd_applied, cmd_streak, cmd_blacklist,
        cmd_contact, cmd_messages, cmd_broadcast,
    )
    from bot.callbacks import handle_callback

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("mysubs", cmd_mysubs))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("saved", cmd_saved))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("salary", cmd_salary))
    app.add_handler(CommandHandler("applied", cmd_applied))
    app.add_handler(CommandHandler("streak", cmd_streak))
    app.add_handler(CommandHandler("blacklist", cmd_blacklist))
    app.add_handler(CommandHandler("contact", cmd_contact))
    app.add_handler(CommandHandler("messages", cmd_messages))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))

    # Callback queries (inline button presses)
    app.add_handler(CallbackQueryHandler(handle_callback))


async def start_polling() -> None:
    """Start the bot in polling mode."""
    app = get_app()
    await app.initialize()
    await app.start()
    _wrap_get_updates_for_liveness(app)
    await app.updater.start_polling(
        drop_pending_updates=True,
        timeout=30,            # long-poll timeout (s); must stay < get_updates read_timeout
        bootstrap_retries=-1,  # retry initial getMe/deleteWebhook forever (network may lag at boot)
        error_callback=_on_polling_error,
    )
    log.info("Bot polling started")


async def stop_polling() -> None:
    """Stop the bot gracefully."""
    if _app and _app.updater:
        await _app.updater.stop()
        await _app.stop()
        await _app.shutdown()
        log.info("Bot polling stopped")
