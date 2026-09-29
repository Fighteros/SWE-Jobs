# Architecture

## Overview

SWE-Jobs is a job aggregation system. A long-lived FastAPI server (`server.py`) runs on the self-hosted VPS via Docker Compose and owns three independent background loops: the supervised Telegram bot poller, the scheduled **fetch** loop, and the scheduled **delivery** loop.

- **Fetch scheduler** runs every `FETCH_INTERVAL_MINUTES` (default 5): fetch -> enrich -> filter -> dedup -> insert -> **enqueue**. It never sends Telegram messages.
- **Delivery scheduler** runs every `DELIVERY_INTERVAL_SECONDS` (default 60): claims due records from the durable PostgreSQL queue and sends them to group topics and subscriber DMs.
- Fetch and delivery may overlap safely. Each has its own concurrency lock, and the queue uses `FOR UPDATE SKIP LOCKED` row locks for worker-level protection.

`main.py` remains a one-shot ingestion entrypoint for manual runs (e.g. seeding or testing) — do not run it while the server scheduler is active.

## Pipeline Stages

### 1. Fetch

Each of the 15 sources has a fetcher function in `sources/`. All fetchers return `list[Job]` and handle their own error cases (returning an empty list on failure).

Before fetching, the **circuit breaker** (`core/circuit_breaker.py`) checks if a source is healthy:
- Sources are retried with exponential backoff (2s, 5s delays)
- After 3 consecutive failures, the circuit opens (source is disabled)
- Circuit state is persisted in the `source_health` database table across runs
- Circuits auto-close after a cooldown period

### 2. Enrich

`core/enrichment.py` adds derived data to each job:

- **Salary parsing** (`core/salary_parser.py`) — extracts min/max/currency from free text, normalizes hourly/monthly to yearly
- **Seniority detection** (`core/seniority.py`) — regex patterns classify as intern/junior/mid/senior/lead/executive
- **Country detection** (`core/country_detector.py`) — maps location strings to ISO country codes using city/country patterns
- **Topic routing** (`core/channels.py`) — matches job title/tags against topic keywords to determine which Telegram topics receive the job

### 3. Filter

`core/filtering.py` applies two filters:

**Keyword scoring** — each job gets a weighted score:
- `+10` for exact whole-word match in title
- `+8` for exact match in tags
- `+3` for partial/substring match
- `-20` for exclude keyword match (instant rejection for irrelevant roles)
- Jobs must score >= 10 (configurable `SCORE_THRESHOLD`)

**Geo-filter** — controls which jobs pass based on location:
- Egypt or Saudi Arabia locations: all jobs pass (onsite + remote)
- Remote-only sources (remotive, remoteok, wwr, etc.): always pass
- Other onsite locations: filtered out

### 4. Deduplicate

`core/dedup.py` runs two dedup passes:

- **Exact URL dedup** — compares `unique_id` (URL with UTM parameters stripped) against existing database records
- **Fuzzy dedup** — uses PostgreSQL's `pg_trgm` extension to find titles with >= 0.7 similarity within a 7-day window, preventing near-duplicates from different sources

### 5. Insert

New jobs are inserted into the `jobs` table via `core/db.py`. The database layer uses connection pooling with SSL (required by Supabase).

### 6. Enqueue

After insertion, the ingestion pipeline creates durable delivery records in the `job_deliveries` table (`core/delivery_queue.py`):

- One `group_topic` record per matching topic.
- One `subscriber_dm` record per matching subscriber (first enabled alert wins; blacklist applied).
- Jobs with no topics get a single `skipped` record with reason `no topics assigned`.
- In `SEED_MODE`, records are created as `skipped` so no live Telegram sends are attempted.

This decouples ingestion from delivery: the fetch scheduler never sends Telegram messages.

### 7. Deliver

The independent delivery scheduler (`core/delivery_scheduler.py`) runs every minute and drains due `job_deliveries` records:

- Claims pending records with `FOR UPDATE SKIP LOCKED` so multiple workers cannot process the same delivery.
- Recovers records stuck in `processing` longer than `DELIVERY_PROCESSING_LEASE_SECONDS`.
- Sends group-topic messages via `bot/sender.py` and subscriber DMs via `bot/notifications.py`.
- Persists each result independently: `sent`, `pending` with backoff, or `dead_letter`.
- Stops when `DELIVERY_MAX_CYCLE_SECONDS` is reached; remaining records stay pending for the next cycle.

Delivery states:

| State | Meaning |
|-------|---------|
| `pending` | Waiting for next attempt |
| `processing` | Currently claimed by a worker |
| `sent` | Successfully delivered |
| `dead_letter` | Permanent failure or exhausted retries |
| `skipped` | Intentionally not sent (seed mode, no topic, etc.) |

Retry behavior:

- `DELIVERY_MAX_ATTEMPTS=5`
- `DELIVERY_RETRY_BASE_SECONDS=30`
- Backoff: 30s, 60s, 120s, 240s, capped at 24h
- Retryable errors: `RetryAfter`, `TimedOut`, `NetworkError`, transient Telegram/DB failures
- Permanent errors: blocked bot, forbidden, chat/user not found, missing topic config, invalid recipient

Dead-letter records can be replayed manually with `core.delivery_queue.replay_dead_letter(id)` or via `scripts/backfill_job_deliveries.py` for bulk backfills.

### 8. Monitor

`core/monitoring.py` checks for anomalies after each run and tracks queue statistics from `job_deliveries` rather than relying solely on `jobs.sent_at`.

Anomalies monitored:

- Zero jobs fetched (all sources may be down)
- Slow run duration
- Low queue insertion rate
- Circuit breaker activations
- Dead-letter records accumulating

Sends alerts to the admin via Telegram DM. Also sends a daily digest with run and queue statistics.

## Database Schema

```
jobs                    # Job listings with full enrichment
├── unique_id           # URL-based dedup key (UTM stripped)
├── title, company, location, url, source
├── salary_min, salary_max, salary_currency
├── seniority, is_remote, country
├── tags[]              # Source-provided tags
├── topics[]            # Computed topic assignments
├── telegram_message_ids  # {topic: message_id} aggregate (convenience)
├── created_at, sent_at
└── updated_at

job_deliveries          # Durable delivery queue
├── job_id              # References jobs.id
├── delivery_type       # group_topic | subscriber_dm
├── recipient_key       # topic key or telegram_id
├── status              # pending | processing | sent | dead_letter | skipped
├── attempts            # Number of delivery attempts
├── last_error          # Last error message
├── next_attempt_at     # When the record is due
├── processing_started_at
├── worker_id           # Worker that claimed the record
├── message_id          # Telegram message ID on success
├── dead_letter_reason  # Why it was dead-lettered
├── created_at, updated_at
├── sent_at
└── failed_at

users                   # Telegram users
├── telegram_id
├── subscriptions       # {topics, seniority, keywords, min_salary} (legacy)
├── notify_dm
└── blacklist

user_alerts             # Multiple alerts per user
├── user_id
├── position
├── topics, seniority, locations, sources, keywords
├── min_salary
└── dm_enabled

user_saved_jobs         # Bookmarked jobs (user_id, job_id)

bot_runs                # Execution tracking
├── jobs_fetched, jobs_filtered, jobs_new, jobs_sent
├── source_stats        # Per-source counts
└── errors

source_health           # Circuit breaker state
├── source
├── consecutive_failures
├── circuit_open_until
└── last_error

job_feedback            # User feedback on jobs (save, report)

jobs_archive            # Archived old jobs (same schema, fewer indexes)
```

All tables have Row Level Security enabled. The `anon` role can only SELECT from `jobs`.

### Key Indexes

- `jobs_title_trgm_idx` — GIN trigram index for fuzzy title matching
- `jobs_tags_gin_idx` — GIN index for tag array containment queries
- `jobs_topics_gin_idx` — GIN index for topic array queries
- `jobs_created_at_idx` — B-tree for date range queries
- `idx_job_deliveries_pending_due` — due pending work lookup
- `idx_job_deliveries_status` — status aggregations
- `idx_job_deliveries_job_id` — per-job delivery lookup
- `idx_job_deliveries_recipient` — per-recipient lookup
- `idx_job_deliveries_processing` — stale-processing recovery

## Telegram Bot

The interactive bot (`bot/`) uses `python-telegram-bot` and supports:

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/help` | List available commands |
| `/subscribe` | Set up job alerts (topics, seniority, keywords) |
| `/unsubscribe` | Remove alert subscription |
| `/mysubs` | View current subscriptions |
| `/search <query>` | Search jobs in database |
| `/saved` | View bookmarked jobs |
| `/stats` | Bot statistics |
| `/top` | Top companies/sources |
| `/salary` | Salary insights |

Inline keyboards handle multi-step flows like subscription setup.

## REST API

The FastAPI backend (`api/`) provides:

| Endpoint | Description | Rate Limit |
|----------|-------------|------------|
| `GET /api/jobs/search` | Full-text search with filters | 30/min |
| `GET /api/stats` | Summary statistics | — |
| `GET /api/salary` | Salary stats by seniority/role/country | — |
| `GET /api/trends` | Trending skills week-over-week | — |

Rate limiting via `slowapi`. CORS enabled for the dashboard origin.

## Web Dashboard

React 19 + TypeScript + Vite + TailwindCSS + Recharts.

Pages:
- **Home** — job listing with search and filters
- **Stats** — jobs by source, topic, company (bar/pie charts)
- **Salary** — salary distributions by seniority, role, country
- **Trends** — skill popularity trends over time

Connects to Supabase directly for reads and the FastAPI backend for aggregated queries.

## Deployment

- **Backend (bot + poller + fetch scheduler + delivery scheduler + API)** — self-hosted VPS, `docker compose up -d --build` (service `backend`, `restart: unless-stopped`). GitHub Actions (`deploy_backend.yml`) redeploys on push to `main`.
- **Database migrations** — the custom PostgreSQL image applies every migration in `supabase/migrations/` automatically **on first boot only** (empty `pgdata` volume). Existing databases must apply new migrations manually — see [Delivery Queue Operations](#delivery-queue-operations) below.
- **Backfill existing unsent jobs** — after migration `007_job_deliveries.sql` is applied, run `python scripts/backfill_job_deliveries.py` once to create subscriber-DM records for jobs inserted under the old 50-job cap.
- **Telegram polling supervision** — `bot/polling.py` `PollingSupervisor` starts polling, lets PTB retry transient errors (502s, timeouts), rebuilds the poller in-process after a continuous failure streak (fresh Application + HTTP pools), and only exits for a container restart if recovery keeps failing. `/health` reports polling liveness; the backend service has a Docker healthcheck.
- **Bot pipeline (manual)** — `main.py` one-shot ingestion workflow (`job_bot.yml`, manual dispatch only; overlaps with the server scheduler by design).
- **Dashboard** — GitHub Pages, deployed on push to `main` (`deploy_dashboard.yml`)
- **Job archival** — GitHub Actions periodic workflow (`archive_jobs.yml`)
- **Database** — self-hosted Postgres container in the same Compose stack

## Delivery Queue Operations

### Applying migrations to an existing database

The Postgres container runs init scripts only on the **first boot** of an empty `pgdata` volume. When a new migration lands, apply it manually:

```bash
docker compose exec -T db psql -U postgres -d postgres -f - < supabase/migrations/007_job_deliveries.sql
```

### Backfilling the delivery queue

After applying migration 007, create subscriber-DM records for jobs inserted before the queue existed (the migration itself already backfills group-topic records):

```bash
docker compose exec -T backend python -m scripts.backfill_job_deliveries
```

Idempotent and safe to re-run. It never touches jobs with `sent_at IS NOT NULL`.

### Monitoring the queue

```bash
docker compose exec db psql -U postgres -d postgres -c \
  "SELECT status, delivery_type, COUNT(*) FROM job_deliveries GROUP BY 1,2 ORDER BY 1;"

docker compose logs --tail 100 backend | grep -E "Fetch scheduler|Delivery scheduler|Delivery cycle"
```

Expected: `pending` drops as `sent` climbs. DMs are capped at `DM_MAX_PER_USER_PER_WINDOW` per user per `DM_RATE_WINDOW_SECONDS`; excess records stay `pending` and drain in later cycles.

### Dead-letter handling

Dead-letter records never retry automatically and trigger an admin alert after each fetch run. Inspect and replay:

```bash
docker compose exec db psql -U postgres -d postgres -c \
  "SELECT id, delivery_type, recipient_key, attempts, dead_letter_reason, last_error
   FROM job_deliveries WHERE status='dead_letter';"

# Replay a single record (error history is preserved):
docker compose exec db psql -U postgres -d postgres -c \
  "UPDATE job_deliveries SET status='pending', next_attempt_at=now()
   WHERE id=<ID> AND status='dead_letter';"
```

Programmatically: `core.delivery_queue.replay_dead_letter(delivery_id)`.

### Skipping a stale backlog

Jobs accumulated before the queue existed (e.g. under the old 50-job-per-run cap) can be excluded from delivery instead of flooding topics/subscribers:

```bash
docker compose exec db psql -U postgres -d postgres -c \
  "UPDATE job_deliveries jd SET status='skipped', dead_letter_reason='stale_backlog'
   FROM jobs j WHERE jd.job_id=j.id AND jd.status='pending'
   AND j.created_at < now() - interval '7 days';"
```

Only `pending` records are touched; `sent`, `processing`, and `dead_letter` are left alone. Idempotent — re-run to catch records that bounce back to `pending` from in-flight batches. Reversible:

```bash
docker compose exec db psql -U postgres -d postgres -c \
  "UPDATE job_deliveries SET status='pending', next_attempt_at=now()
   WHERE status='skipped' AND dead_letter_reason='stale_backlog';"
```
