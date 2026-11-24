"""
core/config.py — SWE-Jobs v2 configuration.

Loads environment variables for PostgreSQL, Telegram, API keys, and misc
settings. This module is the sole place for env-var access in v2 code.

NOTE: The root-level config.py is NOT modified — it remains in use by
existing v1 source fetchers.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# PostgreSQL
# =============================================================================

DB_HOST: str = os.getenv("DB_HOST", "localhost")
DB_PORT: int = int(os.getenv("DB_PORT", "5432"))
DB_NAME: str = os.getenv("DB_NAME", "postgres")
DB_USER: str = os.getenv("DB_USER", "postgres")
DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
DB_SSLMODE: str = os.getenv("DB_SSLMODE", "disable")

# Connection resilience — keep a stalled DB connection from hanging the event loop.
# connect_timeout fails fast if the db container is unreachable; statement_timeout
# caps any single query server-side; maxconn bounds concurrent DB ops (now that DB
# calls run on worker threads).
DB_CONNECT_TIMEOUT: int = int(os.getenv("DB_CONNECT_TIMEOUT", "10"))               # seconds
DB_STATEMENT_TIMEOUT_MS: int = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "30000"))  # 30s
DB_POOL_MAXCONN: int = int(os.getenv("DB_POOL_MAXCONN", "10"))

# =============================================================================
# Telegram
# =============================================================================

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_GROUP_ID: str = os.getenv("TELEGRAM_GROUP_ID", "")
TELEGRAM_SEND_DELAY: int = 3  # seconds between messages

# Polling supervision (bot/polling.py) — all optional, sensible defaults.
# Brief Telegram outages (502s, timeouts) are retried by PTB itself; these
# control when the supervisor rebuilds the poller in-process and when it gives
# up and exits so the container supervisor restarts the stack.
TELEGRAM_POLL_CHECK_INTERVAL: int = int(os.getenv("TELEGRAM_POLL_CHECK_INTERVAL", "30"))        # seconds between liveness checks
TELEGRAM_POLL_STUCK_THRESHOLD: int = int(os.getenv("TELEGRAM_POLL_STUCK_THRESHOLD", "300"))     # continuous failure streak that triggers a rebuild
TELEGRAM_POLL_STARTUP_RETRIES: int = int(os.getenv("TELEGRAM_POLL_STARTUP_RETRIES", "5"))       # initial start attempts before exiting
TELEGRAM_POLL_RECOVERY_ATTEMPTS: int = int(os.getenv("TELEGRAM_POLL_RECOVERY_ATTEMPTS", "3"))   # rebuild attempts per incident before exiting
TELEGRAM_POLL_BACKOFF_INITIAL: float = float(os.getenv("TELEGRAM_POLL_BACKOFF_INITIAL", "2"))   # first retry delay (seconds)
TELEGRAM_POLL_BACKOFF_MAX: float = float(os.getenv("TELEGRAM_POLL_BACKOFF_MAX", "60"))          # retry delay ceiling (seconds)
TELEGRAM_POLL_STOP_TIMEOUT: float = float(os.getenv("TELEGRAM_POLL_STOP_TIMEOUT", "30"))        # teardown timeout before abandoning an instance

# =============================================================================
# API Keys (all optional — sources are skipped if key is absent)
# =============================================================================

RAPIDAPI_KEY: str = os.getenv("RAPIDAPI_KEY", "")
ADZUNA_APP_ID: str = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY: str = os.getenv("ADZUNA_APP_KEY", "")
FINDWORK_API_KEY: str = os.getenv("FINDWORK_API_KEY", "")
JOOBLE_API_KEY: str = os.getenv("JOOBLE_API_KEY", "")
REED_API_KEY: str = os.getenv("REED_API_KEY", "")
MUSE_API_KEY: str = os.getenv("MUSE_API_KEY", "")

# =============================================================================
# Admin
# =============================================================================

ADMIN_TELEGRAM_ID: str = os.getenv("ADMIN_TELEGRAM_ID", "")

# =============================================================================
# iMessage delivery (Photon Spectrum) — used when DELIVERY_CHANNEL=imessage
# =============================================================================
# Which channel job deliveries and admin alerts go out on. "telegram" is the
# original bot; "imessage" delivers personalized (preference-matched) jobs
# and admin alerts over iMessage through the Photon Spectrum sidecar
# (sidecar/ — a small Node service wrapping the spectrum-ts SDK, the same
# service and architecture the Hermes agent uses for iMessage).
DELIVERY_CHANNEL: str = os.getenv("DELIVERY_CHANNEL", "telegram").strip().lower()
# Loopback URL of the imessage sidecar (docker-compose service "imessage-sidecar").
IMESSAGE_SIDECAR_URL: str = os.getenv("IMESSAGE_SIDECAR_URL", "http://localhost:8789")
IMESSAGE_WEBHOOK_SECRET: str = os.getenv("IMESSAGE_WEBHOOK_SECRET", "")
IMESSAGE_REQUEST_TIMEOUT: int = int(os.getenv("IMESSAGE_REQUEST_TIMEOUT", "15"))  # seconds
# Sidecar credentials: Spectrum project id + secret from app.photon.codes
# (consumed by the sidecar, not the Python app; listed here for .env parity).
SPECTRUM_PROJECT_ID: str = os.getenv("SPECTRUM_PROJECT_ID", "")
SPECTRUM_PROJECT_SECRET: str = os.getenv("SPECTRUM_PROJECT_SECRET", "")
# Comma-separated iMessage addresses (E.164 phone and/or email) that receive
# ADMIN ALERTS (startup/crash/circuit-breaker). Job deliveries are personal:
# they go to each registered iMessage user with matching saved alerts.
IMESSAGE_RECIPIENTS: list[str] = [
    addr.strip() for addr in os.getenv("IMESSAGE_RECIPIENTS", "").split(",") if addr.strip()
]

# Crash / health alerting. These make silent failures visible in Telegram.
# Message the admin whenever the backend (re)starts, so a crash-restart loop
# shows up instead of failing silently.
STARTUP_ALERT: bool = os.getenv("STARTUP_ALERT", "true").lower() in ("1", "true", "yes")
# Alert after this many consecutive failures of the fetch pipeline, the
# delivery scheduler, or the polling supervisor's own liveness checks.
ALERT_CONSECUTIVE_FAILURES: int = int(os.getenv("ALERT_CONSECUTIVE_FAILURES", "3"))
# Minimum hours between "circuit breaker open" alerts for the same source
# while it stays broken. The first open and the recovery always alert.
ALERT_CIRCUIT_COOLDOWN_HOURS: int = int(os.getenv("ALERT_CIRCUIT_COOLDOWN_HOURS", "6"))

# =============================================================================
# Misc
# =============================================================================

REQUEST_TIMEOUT: int = 15        # seconds for HTTP requests
SEED_MODE_ENV: str = "SEED_MODE" # env var name checked to force seed mode
FETCH_INTERVAL_MINUTES: int = int(os.getenv("FETCH_INTERVAL_MINUTES", "5"))

# Delivery queue settings — all have safe defaults if unset.
DELIVERY_INTERVAL_SECONDS: int = int(os.getenv("DELIVERY_INTERVAL_SECONDS", "60"))
DELIVERY_BATCH_SIZE: int = int(os.getenv("DELIVERY_BATCH_SIZE", "50"))
DELIVERY_MAX_ATTEMPTS: int = int(os.getenv("DELIVERY_MAX_ATTEMPTS", "5"))
DELIVERY_RETRY_BASE_SECONDS: int = int(os.getenv("DELIVERY_RETRY_BASE_SECONDS", "30"))
DELIVERY_PROCESSING_LEASE_SECONDS: int = int(os.getenv("DELIVERY_PROCESSING_LEASE_SECONDS", "600"))
DELIVERY_IDLE_SLEEP_SECONDS: int = int(os.getenv("DELIVERY_IDLE_SLEEP_SECONDS", "10"))
DELIVERY_MAX_CYCLE_SECONDS: int = int(os.getenv("DELIVERY_MAX_CYCLE_SECONDS", "50"))
def _positive_int_env(name: str, default: int) -> int:
    """Reject quotas that would silently defer every delivery forever."""
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


DM_MAX_PER_USER_PER_WINDOW: int = _positive_int_env("DM_MAX_PER_USER_PER_WINDOW", 20)
DM_RATE_WINDOW_SECONDS: int = _positive_int_env("DM_RATE_WINDOW_SECONDS", 3600)

# Number of 20-job pages fetched per Wuzzuf category.
WUZZUF_MAX_PAGES: int = int(os.getenv("WUZZUF_MAX_PAGES", "3"))
