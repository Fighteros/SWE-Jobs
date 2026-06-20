"""
core/config.py — SWE-Jobs v2 configuration.

Loads environment variables for Supabase, Telegram, API keys, and misc
settings. This module is the sole place for env-var access in v2 code.

NOTE: The root-level config.py is NOT modified — it remains in use by
existing v1 source fetchers.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# Supabase / PostgreSQL
# =============================================================================

SUPABASE_DB_HOST: str = os.getenv("DB_HOST", "")
SUPABASE_DB_PORT: int = int(os.getenv("DB_PORT", "") or "6543")
SUPABASE_DB_NAME: str = os.getenv("DB_NAME", "postgres")
SUPABASE_DB_USER: str = os.getenv("DB_USER", "postgres")
SUPABASE_DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
# sslmode: "prefer" works for both a no-SSL local container and an SSL managed
# host (tries SSL, falls back). Set DB_SSLMODE=disable for the local container,
# DB_SSLMODE=require for Supabase.
SUPABASE_DB_SSLMODE: str = os.getenv("DB_SSLMODE", "prefer")

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
# Misc
# =============================================================================

MAX_JOBS_PER_RUN: int = 50       # safety cap per run
REQUEST_TIMEOUT: int = 15        # seconds for HTTP requests
SEED_MODE_ENV: str = "SEED_MODE" # env var name checked to force seed mode
SEEN_JOBS_FILE: str = "seen_jobs.json"
FETCH_INTERVAL_MINUTES: int = int(os.getenv("FETCH_INTERVAL_MINUTES", "5"))
