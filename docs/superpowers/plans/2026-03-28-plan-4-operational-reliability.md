# Plan 4: Operational Reliability — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add retry with backoff, DB-backed circuit breaker, structured JSON logging, run tracking via `bot_runs`, monitoring alerts, and a daily digest — so the bot self-heals from source failures and operators know when something breaks.

**Architecture:** Circuit breaker state persists in the `source_health` table across GitHub Actions runs. Each cron run creates a `bot_runs` row for tracking. Alert messages go to a separate admin Telegram topic/DM. Logging switches to JSON format for easier parsing.

**Tech Stack:** Python 3.11, psycopg2, python-json-logger

**Spec:** `docs/superpowers/specs/2026-03-28-v2-redesign-design.md` (Section 5)

**Depends on:** Plan 1 (core/db.py, source_health table, bot_runs table)
**Blocks:** Plan 6 (integration)

---

## File Structure

```
core/
├── circuit_breaker.py    # Per-source retry, backoff, circuit breaker (DB-backed)
├── monitoring.py         # Run tracking, alert triggers, daily digest
└── logging_config.py     # Structured JSON logging setup
```

---

### Task 1: Structured JSON Logging

**Files:**
- Create: `core/logging_config.py`
- Modify: `requirements.txt` — add `python-json-logger>=2.0.0`

- [ ] **Step 1: Update requirements.txt**

Add `python-json-logger>=2.0.0` to `requirements.txt`.

- [ ] **Step 2: Write core/logging_config.py**

```python
# core/logging_config.py
"""
Structured JSON logging configuration.
Replaces plain text logs for easier parsing and monitoring.
"""

import logging
import sys

from pythonjsonlogger import jsonlogger


def setup_logging(level: str = "INFO") -> None:
    """
    Configure structured JSON logging.
    Call once at application startup.
    """
    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
```

- [ ] **Step 3: Commit**

```bash
git add core/logging_config.py requirements.txt
git commit -m "feat: add structured JSON logging configuration"
```

---

### Task 2: Circuit Breaker

**Files:**
- Create: `core/circuit_breaker.py`
- Create: `tests/test_circuit_breaker.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_circuit_breaker.py
"""Tests for the circuit breaker with DB-backed state."""

from unittest.mock import patch, MagicMock
from core.circuit_breaker import fetch_with_retry, is_circuit_open


class TestFetchWithRetry:
    @patch("core.circuit_breaker.is_circuit_open", return_value=False)
    @patch("core.circuit_breaker._record_success")
    def test_success_on_first_try(self, mock_record, mock_open):
        def fetcher():
            return [{"title": "Dev"}]

        result = fetch_with_retry("test_source", fetcher)
        assert result == [{"title": "Dev"}]
        mock_record.assert_called_once_with("test_source")

    @patch("core.circuit_breaker.is_circuit_open", return_value=False)
    @patch("core.circuit_breaker._record_failure")
    @patch("core.circuit_breaker._record_success")
    @patch("time.sleep")
    def test_retries_on_failure(self, mock_sleep, mock_success, mock_failure, mock_open):
        call_count = 0
        def fetcher():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("timeout")
            return [{"title": "Dev"}]

        result = fetch_with_retry("test_source", fetcher, max_retries=3)
        assert result == [{"title": "Dev"}]
        assert call_count == 3

    @patch("core.circuit_breaker.is_circuit_open", return_value=True)
    def test_skips_when_circuit_open(self, mock_open):
        def fetcher():
            return [{"title": "Dev"}]

        result = fetch_with_retry("test_source", fetcher)
        assert result == []

    @patch("core.circuit_breaker.is_circuit_open", return_value=False)
    @patch("core.circuit_breaker._record_failure")
    @patch("time.sleep")
    def test_returns_empty_after_max_retries(self, mock_sleep, mock_failure, mock_open):
        def fetcher():
            raise Exception("always fails")

        result = fetch_with_retry("test_source", fetcher, max_retries=2)
        assert result == []


class TestIsCircuitOpen:
    @patch("core.db.is_source_circuit_open", return_value=True)
    def test_open(self, mock_db):
        assert is_circuit_open("failing_source") is True

    @patch("core.db.is_source_circuit_open", return_value=False)
    def test_closed(self, mock_db):
        assert is_circuit_open("healthy_source") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd G:/projects/SWE-Jobs && python -m pytest tests/test_circuit_breaker.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# core/circuit_breaker.py
"""
Per-source retry with backoff and DB-backed circuit breaker.
State persists in the source_health table across GitHub Actions runs.
"""

import time
import logging
from typing import Callable

from core import db

log = logging.getLogger(__name__)

# Retry delays in seconds (index = retry attempt)
RETRY_DELAYS = [2, 5]


def is_circuit_open(source: str) -> bool:
    """Check if a source's circuit breaker is open (should be skipped)."""
    try:
        return db.is_source_circuit_open(source)
    except Exception as e:
        log.warning(f"Failed to check circuit state for {source}: {e}")
        return False  # If DB is down, try fetching anyway


def _record_success(source: str) -> None:
    """Record a successful fetch — resets circuit breaker."""
    try:
        db.upsert_source_health(source, success=True)
    except Exception as e:
        log.warning(f"Failed to record success for {source}: {e}")


def _record_failure(source: str, error: str) -> None:
    """Record a failed fetch — increments failure count, may open circuit."""
    try:
        db.upsert_source_health(source, success=False, error=error)
    except Exception as e:
        log.warning(f"Failed to record failure for {source}: {e}")


def fetch_with_retry(
    source: str,
    fetcher: Callable,
    max_retries: int = 2,
    timeout: int = 15,
) -> list:
    """
    Fetch jobs from a source with retry and circuit breaker.

    Args:
        source: Source identifier (e.g. 'remotive')
        fetcher: Callable that returns list of jobs
        max_retries: Number of retry attempts after first failure
        timeout: Per-request timeout (passed to fetcher if supported)

    Returns: List of jobs (empty if all attempts fail or circuit is open)
    """
    # Check circuit breaker
    if is_circuit_open(source):
        log.warning(f"⚡ Circuit OPEN for {source} — skipping")
        return []

    last_error = None
    for attempt in range(1 + max_retries):
        try:
            result = fetcher()
            _record_success(source)
            if attempt > 0:
                log.info(f"✓ {source} succeeded on retry {attempt}")
            return result if result else []
        except Exception as e:
            last_error = str(e)
            if attempt < max_retries:
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                log.warning(f"⚠ {source} attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                time.sleep(delay)
            else:
                log.error(f"✗ {source} failed after {max_retries + 1} attempts: {e}")

    _record_failure(source, last_error or "unknown")
    return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd G:/projects/SWE-Jobs && python -m pytest tests/test_circuit_breaker.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add core/circuit_breaker.py tests/test_circuit_breaker.py
git commit -m "feat: add DB-backed circuit breaker with retry and backoff"
```

---

### Task 3: Run Monitoring and Alerts

**Files:**
- Create: `core/monitoring.py`

- [ ] **Step 1: Write core/monitoring.py**

```python
# core/monitoring.py
"""
Run monitoring, alert triggers, and daily digest.
Sends alerts to a separate admin Telegram topic or DM.
"""

import logging
from typing import Optional
from telegram import Bot
from telegram.error import TelegramError

from core.config import ADMIN_TELEGRAM_ID, TELEGRAM_BOT_TOKEN
from core import db

log = logging.getLogger(__name__)


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def send_admin_alert(bot: Bot, message: str) -> bool:
    """Send an alert message to the admin via DM."""
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
        run = db._fetchone("SELECT * FROM bot_runs WHERE id = %s", (run_id,))
        if not run:
            return alerts

        # Alert: zero jobs fetched (all sources failed)
        if run["jobs_fetched"] == 0:
            msg = "🚨 <b>ALERT: Zero jobs fetched</b>\nAll sources failed this run."
            await send_admin_alert(bot, msg)
            alerts.append(msg)

        # Alert: run took too long
        if run["finished_at"] and run["started_at"]:
            # Duration check via DB
            duration = db._fetchone(
                "SELECT EXTRACT(EPOCH FROM (%s - %s)) as seconds",
                (run["finished_at"], run["started_at"]),
            )
            if duration and duration["seconds"] > 300:
                msg = f"⏰ <b>ALERT: Slow run</b>\nRun took {int(duration['seconds'])}s (threshold: 300s)"
                await send_admin_alert(bot, msg)
                alerts.append(msg)

        # Alert: Telegram send success rate below 80%
        if run["jobs_new"] > 0 and run["jobs_sent"] > 0:
            success_rate = run["jobs_sent"] / run["jobs_new"]
            if success_rate < 0.8:
                msg = (
                    f"📉 <b>ALERT: Low send rate</b>\n"
                    f"Sent {run['jobs_sent']}/{run['jobs_new']} "
                    f"({success_rate:.0%} success rate)"
                )
                await send_admin_alert(bot, msg)
                alerts.append(msg)

        # Alert: circuit breaker opened
        broken = db._fetchall(
            "SELECT source FROM source_health WHERE circuit_open_until > now()"
        )
        for row in broken:
            msg = f"⚡ <b>ALERT: Circuit breaker open</b>\nSource: {_escape_html(row['source'])}"
            await send_admin_alert(bot, msg)
            alerts.append(msg)

    except Exception as e:
        log.error(f"Alert check failed: {e}")

    return alerts


async def send_daily_digest(bot: Bot) -> bool:
    """
    Send a daily summary to the admin.
    Call this once per day (e.g. at midnight via a scheduled GitHub Actions job).
    """
    try:
        # Jobs sent today
        today_stats = db._fetchone(
            """SELECT
                 COUNT(*) as total,
                 COUNT(CASE WHEN sent_at IS NOT NULL THEN 1 END) as sent
               FROM jobs
               WHERE created_at > now() - make_interval(days := 1)"""
        )

        # Source health
        sources = db._fetchall(
            """SELECT source, consecutive_failures, circuit_open_until > now() AS is_broken
               FROM source_health
               ORDER BY consecutive_failures DESC"""
        )

        # Error count today
        errors = db._fetchone(
            """SELECT COUNT(*) as count FROM bot_runs
               WHERE started_at > now() - make_interval(days := 1)
                 AND jsonb_array_length(errors) > 0"""
        )

        lines = [
            "📊 <b>Daily Digest</b>\n",
            f"Jobs found today: {today_stats['total']}",
            f"Jobs sent today: {today_stats['sent']}",
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
```

- [ ] **Step 2: Commit**

```bash
git add core/monitoring.py
git commit -m "feat: add run monitoring, alert triggers, and daily digest"
```

---

### Task 4: Final Verification

- [ ] **Step 1: Run all tests**

Run: `cd G:/projects/SWE-Jobs && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Verify imports**

Run:
```bash
cd G:/projects/SWE-Jobs && python -c "
from core.circuit_breaker import fetch_with_retry, is_circuit_open
from core.monitoring import check_alerts, send_daily_digest
from core.logging_config import setup_logging
print('All reliability modules imported OK')
"
```
Expected: "All reliability modules imported OK"

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat: complete Plan 4 — operational reliability"
```

---

## Summary

After completing this plan:

- **Circuit breaker** — DB-backed, persists across GitHub Actions runs, auto-opens at 3 failures, auto-closes after 30 min
- **Retry with backoff** — 2 retries per source with 2s/5s delays
- **Structured JSON logging** — replaces plain text
- **Run tracking** — every cron run logged in `bot_runs` with stats
- **Alert triggers** — zero jobs, slow runs, low send rate, circuit breaker opened
- **Daily digest** — admin DM with jobs/source health summary

**Next:** Plan 5 (Web Dashboard) builds the React SPA and FastAPI endpoints.
