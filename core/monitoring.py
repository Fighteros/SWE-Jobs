"""
Run monitoring, alert triggers, and daily digest.
Sends alerts to a separate admin Telegram topic or DM.
"""

import asyncio
import logging
from typing import Optional
from telegram import Bot
from telegram.error import TelegramError

from core.config import (
    ADMIN_TELEGRAM_ID,
    ALERT_CIRCUIT_COOLDOWN_HOURS,
    DELIVERY_CHANNEL,
    TELEGRAM_BOT_TOKEN,
)
from core import db_async as adb
from core import imessage as _imessage

log = logging.getLogger(__name__)


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _send_admin_alert_imessage(message: str) -> bool:
    """iMessage mode: alerts go to the configured iMessage recipients."""
    if not _imessage.configured():
        log.debug("iMessage delivery not configured, skipping alert")
        return False
    stats = _imessage.send_to_recipients(_imessage.html_to_plain(message))
    return stats["sent"] > 0


async def send_admin_alert(bot: Optional[Bot], message: str) -> bool:
    """Send an alert message to the admin via the configured delivery channel."""
    if DELIVERY_CHANNEL == "imessage":
        return await asyncio.to_thread(_send_admin_alert_imessage, message)
    if not ADMIN_TELEGRAM_ID:
        log.debug("No ADMIN_TELEGRAM_ID set, skipping alert")
        return False

    try:
        await bot.send_message(
            chat_id=int(ADMIN_TELEGRAM_ID),
            text=message,
            parse_mode="HTML",
        )
        return True
    except TelegramError as e:
        log.error(f"Failed to send admin alert: {e}")
        return False


async def check_alerts(bot: Bot, run_id: int) -> list[str]:
    """
    Check alert triggers after a run completes.
    Returns list of alert messages sent.
    """
    alerts = []

    try:
        run = await adb._fetchone("SELECT * FROM bot_runs WHERE id = %s", (run_id,))
        if not run:
            return alerts

        # Alert: zero jobs fetched (all sources failed)
        if run["jobs_fetched"] == 0:
            msg = "🚨 <b>ALERT: Zero jobs fetched</b>\nAll sources failed this run."
            await send_admin_alert(bot, msg)
            alerts.append(msg)

        # Alert: run took too long
        if run["finished_at"] and run["started_at"]:
            duration = await adb._fetchone(
                "SELECT EXTRACT(EPOCH FROM (%s - %s)) as seconds",
                (run["finished_at"], run["started_at"]),
            )
            if duration and duration["seconds"] > 300:
                msg = f"⏰ <b>ALERT: Slow run</b>\nRun took {int(duration['seconds'])}s (threshold: 300s)"
                log.info(msg)

        # Alert: low queue insertion rate
        # jobs_sent is reused to store group-topic deliveries queued this run.
        stats = run.get("source_stats") or {}
        if isinstance(stats, str):
            import json as _json
            stats = _json.loads(stats)
        jobs_attempted = stats.get("_jobs_attempted", 0)
        jobs_queued = run.get("jobs_sent", 0)
        if jobs_attempted > 0:
            queue_rate = jobs_queued / jobs_attempted
            if queue_rate < 0.8:
                msg = (
                    f"📉 <b>ALERT: Low queue rate</b>\n"
                    f"Queued {jobs_queued}/{jobs_attempted} jobs "
                    f"({queue_rate:.0%} queue rate)"
                )
                await send_admin_alert(bot, msg)
                alerts.append(msg)

        # Alert: circuit breaker opened — once per outage, not every run.
        # circuit_open_alerted_at (migration 009) records the last alert so a
        # source that stays broken only re-alerts after the cooldown, and a
        # source that recovers gets one recovery alert.
        await _check_circuit_alerts(bot, run, alerts)

    except Exception as e:
        log.error(f"Alert check failed: {e}")

    return alerts


async def _check_circuit_alerts(bot: Bot, run: dict, alerts: list[str]) -> None:
    """Send circuit-breaker open/recovery alerts, throttled per source."""
    cooldown = ALERT_CIRCUIT_COOLDOWN_HOURS

    try:
        has_alert_state = await adb.ensure_circuit_alert_schema()
    except Exception as e:
        log.warning(f"Circuit alert schema check failed: {e}")
        has_alert_state = False

    if not has_alert_state:
        # Fallback without persisted alert state: alert only on the run whose
        # failure (re)opened the circuit — last_failure_at falls inside this
        # run — instead of on every run while the circuit is open.
        started_at = run.get("started_at")
        if not started_at:
            return
        broken = await adb._fetchall(
            """SELECT source, last_error FROM source_health
               WHERE circuit_open_until > now() AND last_failure_at >= %s""",
            (started_at,),
        )
        for row in broken:
            msg = (
                f"⚡ <b>ALERT: Circuit breaker open</b>\n"
                f"Source: {_escape_html(row['source'])}\n"
                f"Last error: {_escape_html((row.get('last_error') or 'unknown')[:150])}"
            )
            await send_admin_alert(bot, msg)
            alerts.append(msg)
        return

    broken = await adb._fetchall(
        """SELECT source, last_error, consecutive_failures, circuit_open_until
           FROM source_health
           WHERE circuit_open_until > now()
             AND (circuit_open_alerted_at IS NULL
                  OR circuit_open_alerted_at < now() - make_interval(hours := %s))""",
        (cooldown,),
    )
    for row in broken:
        until = row.get("circuit_open_until")
        until_txt = until.strftime("%H:%M UTC") if hasattr(until, "strftime") else str(until)
        msg = (
            f"⚡ <b>ALERT: Circuit breaker open</b>\n"
            f"Source: {_escape_html(row['source'])}\n"
            f"Last error: {_escape_html((row.get('last_error') or 'unknown')[:150])}\n"
            f"Fetching paused; next retry after {until_txt}. "
            f"Further alerts muted for {cooldown}h while it stays broken."
        )
        await send_admin_alert(bot, msg)
        alerts.append(msg)
        await adb._execute(
            "UPDATE source_health SET circuit_open_alerted_at = now() WHERE source = %s",
            (row["source"],),
        )

    # Recovery: was alerted while open and is healthy again.
    recovered = await adb._fetchall(
        """SELECT source FROM source_health
           WHERE circuit_open_alerted_at IS NOT NULL
             AND circuit_open_until IS NULL
             AND consecutive_failures = 0"""
    )
    for row in recovered:
        msg = (
            f"✅ <b>RECOVERED: Circuit breaker closed</b>\n"
            f"Source: {_escape_html(row['source'])}\n"
            f"Fetching has resumed."
        )
        await send_admin_alert(bot, msg)
        alerts.append(msg)
        await adb._execute(
            "UPDATE source_health SET circuit_open_alerted_at = NULL WHERE source = %s",
            (row["source"],),
        )


async def send_daily_digest(bot: Bot) -> bool:
    """
    Send a daily summary to the admin.
    Call this once per day (e.g. at midnight via a scheduled GitHub Actions job).
    """
    try:
        # Jobs found today
        today_jobs = await adb._fetchone(
            """SELECT COUNT(*) as total
               FROM jobs
               WHERE created_at > now() - make_interval(days := 1)"""
        )

        # Delivery stats from the durable queue
        delivery_stats = await adb._fetchall(
            """SELECT status, COUNT(*) as count
               FROM job_deliveries
               WHERE created_at > now() - make_interval(days := 1)
                  OR (sent_at IS NOT NULL AND sent_at > now() - make_interval(days := 1))
                  OR (failed_at IS NOT NULL AND failed_at > now() - make_interval(days := 1))
               GROUP BY status"""
        )

        status_counts = {row["status"]: row["count"] for row in delivery_stats}

        # Source health
        sources = await adb._fetchall(
            """SELECT source, consecutive_failures, circuit_open_until > now() AS is_broken
               FROM source_health
               ORDER BY consecutive_failures DESC"""
        )

        # Error count today
        errors = await adb._fetchone(
            """SELECT COUNT(*) as count FROM bot_runs
               WHERE started_at > now() - make_interval(days := 1)
                 AND jsonb_array_length(errors) > 0"""
        )

        lines = [
            "📊 <b>Daily Digest</b>\n",
            f"Jobs found today: {today_jobs['total']}",
            f"Group+DM sent today: {status_counts.get('sent', 0)}",
            f"Pending deliveries: {status_counts.get('pending', 0)}",
            f"Retrying (processing): {status_counts.get('processing', 0)}",
            f"Dead-letter: {status_counts.get('dead_letter', 0)}",
            f"Skipped: {status_counts.get('skipped', 0)}",
            f"Runs with errors: {errors['count']}\n",
            "<b>Source Health:</b>",
        ]

        for s in sources:
            status = "🔴 BROKEN" if s.get("is_broken") else "🟢 OK"
            if s["consecutive_failures"] > 0:
                status = f"🟡 {s['consecutive_failures']} failures"
            lines.append(f"  {s['source']}: {status}")

        msg = "\n".join(lines)
        return await send_admin_alert(bot, msg)

    except Exception as e:
        log.error(f"Daily digest failed: {e}")
        return False


async def get_queue_stats() -> dict:
    """Return current delivery-queue statistics."""
    rows = await adb._fetchall(
        """SELECT status, delivery_type, COUNT(*) as count
           FROM job_deliveries
           GROUP BY status, delivery_type"""
    )

    stats = {
        "pending": 0,
        "processing": 0,
        "sent": 0,
        "dead_letter": 0,
        "skipped": 0,
    }

    for row in rows:
        status = row["status"]
        d_type = row["delivery_type"]
        count = row["count"]
        stats[status] = stats.get(status, 0) + count
        if d_type not in stats:
            stats[d_type] = {"pending": 0, "processing": 0, "sent": 0, "dead_letter": 0, "skipped": 0}
        stats[d_type][status] = stats[d_type].get(status, 0) + count

    return stats


def send_admin_alert_sync(message: str, timeout: float = 5.0) -> bool:
    """
    Synchronous, best-effort admin alert for contexts where the event loop is
    unavailable or about to die (fatal exits, crash paths). Never raises.
    """
    if DELIVERY_CHANNEL == "imessage":
        try:
            return _send_admin_alert_imessage(message)
        except Exception as e:
            log.error("Sync admin alert failed: %s", e)
            return False
    if not ADMIN_TELEGRAM_ID or not TELEGRAM_BOT_TOKEN:
        log.debug("No ADMIN_TELEGRAM_ID/TELEGRAM_BOT_TOKEN set, skipping sync alert")
        return False

    try:
        import requests

        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": int(ADMIN_TELEGRAM_ID),
                "text": message,
                "parse_mode": "HTML",
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            log.error("Sync admin alert failed: HTTP %s", resp.status_code)
            return False
        return True
    except Exception as e:
        log.error("Sync admin alert failed: %s", e)
        return False


async def notify_admin(message: str, bot: Optional[Bot] = None) -> bool:
    """
    Async admin alert that works with or without an existing Bot instance.
    Creates a short-lived Bot when none is passed. Never raises.
    """
    if DELIVERY_CHANNEL == "imessage":
        try:
            return await asyncio.to_thread(_send_admin_alert_imessage, message)
        except Exception as e:
            log.error("Failed to send admin alert: %s", e)
            return False
    if bot is not None:
        return await send_admin_alert(bot, message)
    if not TELEGRAM_BOT_TOKEN:
        log.debug("No TELEGRAM_BOT_TOKEN set, skipping alert")
        return False

    try:
        async with Bot(token=TELEGRAM_BOT_TOKEN) as own_bot:
            return await send_admin_alert(own_bot, message)
    except Exception as e:
        log.error("Failed to send admin alert: %s", e)
        return False
