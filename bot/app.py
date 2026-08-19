"""
Telegram bot application factory and explicit polling lifecycle.
Uses python-telegram-bot in polling mode with asyncio.

Lifecycle ownership lives in bot/polling.py (PollingSupervisor): this module
only builds fresh Applications and provides start/stop primitives that are
safe to call on any instance, exactly once or partially-failed.
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

# ---------------------------------------------------------------------------
# Polling liveness tracking (consumed by bot.polling.PollingSupervisor)
# ---------------------------------------------------------------------------
# PTB retries polling errors (e.g. Telegram 502s) forever with backoff — that's
# fine for a transient blip, but if the host's path to Telegram is broken (DNS,
# firewall, routing) it retries forever with no recovery, and `updater.running`
# stays True the whole time so a purely dead-poller watchdog never fires.
# Track how long polling has been failing *continuously* (i.e. with no successful
# get_updates in between — see _wrap_get_updates_for_liveness below) so the
# supervisor can rebuild the poller when a streak runs too long.
_error_streak_started_at: float = 0.0
_last_success_at: float = 0.0


def _on_polling_error(exc: TelegramError) -> None:
    """error_callback for start_polling: log once (no traceback spam) and mark a streak."""
    global _error_streak_started_at
    if _error_streak_started_at == 0.0:
        _error_streak_started_at = time.monotonic()
    log.warning("Telegram polling error (auto-retrying): %s", exc)


def _on_polling_success() -> None:
    """Called after every successful get_updates (including empty long-poll timeouts)."""
    global _error_streak_started_at, _last_success_at
    _error_streak_started_at = 0.0
    _last_success_at = time.monotonic()


def polling_stuck(threshold: float = 300.0) -> bool:
    """True if polling has been failing continuously for over `threshold` seconds."""
    if _error_streak_started_at == 0.0:
        return False
    return (time.monotonic() - _error_streak_started_at) > threshold


def reset_polling_state() -> None:
    """Clear streak/liveness bookkeeping (called before starting a fresh instance)."""
    global _error_streak_started_at, _last_success_at
    _error_streak_started_at = 0.0
    _last_success_at = 0.0


def polling_status() -> dict:
    """Liveness snapshot for health endpoints."""
    now = time.monotonic()
    return {
        "stuck": polling_stuck(),
        "error_streak_seconds": round(now - _error_streak_started_at, 1)
        if _error_streak_started_at
        else 0.0,
        "last_success_seconds_ago": round(now - _last_success_at, 1)
        if _last_success_at
        else None,
    }


def _wrap_get_updates_for_liveness(app: Application) -> None:
    """
    Wrap bot.get_updates so a successful call (including empty long-poll timeouts,
    which don't raise) resets the error streak. Idempotent: wrapping twice adds
    a single tracking layer.

    PTB's TelegramObject forbids assigning attributes on bot *instances*
    (`AttributeError: ... can't be set!`), so the wrapper is installed once on
    the bot's class instead — it then applies to every instance, including the
    fresh Application built per recovery attempt.
    """
    bot = app.bot
    if getattr(bot.get_updates, "_is_liveness_tracked", False):
        return

    cls = type(bot)
    original = cls.get_updates

    async def _tracked(self, *args, **kwargs):
        result = await original(self, *args, **kwargs)
        _on_polling_success()
        return result

    _tracked._is_liveness_tracked = True
    cls.get_updates = _tracked


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_application() -> Application:
    """
    Build a fresh Telegram Application: tuned HTTP pools, all handlers, and a
    global error handler for update-processing exceptions. A new instance per
    start/recovery attempt guarantees fresh network state and untouched
    lifecycle flags.
    """
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
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .request(request)
        .get_updates_request(get_updates_request)
        .build()
    )
    _register_handlers(app)
    app.add_error_handler(_handle_update_error)
    log.info("Telegram bot application created")
    return app


async def _handle_update_error(update: object, context) -> None:
    """
    Global PTB error handler: log full context server-side and, best-effort,
    tell the user something generic — never internals or stack traces.
    """
    log.error(
        "Unhandled error while processing update: %s",
        context.error,
        exc_info=context.error,
    )
    try:
        effective_chat = getattr(update, "effective_chat", None) if update is not None else None
        if effective_chat is not None:
            await context.bot.send_message(
                chat_id=effective_chat.id,
                text="Something went wrong while handling your request. Please try again.",
            )
    except TelegramError:
        pass  # can't reach the user; already logged


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


# ---------------------------------------------------------------------------
# Explicit lifecycle primitives (operate on a given Application instance)
# ---------------------------------------------------------------------------

async def start_polling(app: Application) -> None:
    """
    Bring a fresh Application into polling mode:
    liveness wrap → initialize → start → updater.start_polling.
    On partial failure everything already started is unwound and the error
    re-raised, so the caller can simply discard the instance.
    """
    _wrap_get_updates_for_liveness(app)
    await app.initialize()
    try:
        await app.start()
    except Exception:
        await app.shutdown()
        raise

    try:
        await app.updater.start_polling(
            drop_pending_updates=True,
            timeout=30,            # long-poll timeout (s); must stay < get_updates read_timeout
            bootstrap_retries=0,   # supervisor owns startup retries with backoff
            error_callback=_on_polling_error,
        )
    except Exception:
        await app.stop()
        await app.shutdown()
        raise
    log.info("Bot polling started")


async def stop_polling(app: Application) -> None:
    """Tear a polling Application down completely. Idempotent per instance."""
    if app is None:
        return
    if app.updater is not None and app.updater.running:
        await app.updater.stop()
    if app.running:
        await app.stop()
    if app.initialized:
        await app.shutdown()
    log.info("Bot polling stopped")
