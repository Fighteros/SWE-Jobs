# V2 Changelog

What changed from v1 to v2. V2 is a complete rewrite from a simple job aggregator into a production-grade platform.

## Pipeline

| | V1 | V2 |
|---|----|----|
| **Stages** | fetch -> filter -> dedup -> send (4) | fetch -> enrich -> filter -> dedup -> insert -> send -> notify -> track -> monitor (9) |
| **Job model** | ~5 fields (title, company, location, url, source) | 20+ fields (+ salary, seniority, country, topics, telegram tracking) |
| **Filtering** | Boolean keyword match | Weighted scoring (+10 title, +8 tags, +3 partial, -20 exclude, threshold = 10) |
| **Dedup** | URL-only exact match via `seen_jobs.json` | URL exact + pg_trgm fuzzy title (>= 0.7 similarity) + batch internal |
| **Storage** | Flat JSON file on `data` branch | PostgreSQL (Supabase) with 8 tables, RLS, GIN indexes |
| **Reliability** | Basic try/except | Circuit breaker per source (3-strike, exponential backoff, DB-persisted) |
| **Monitoring** | None | Post-run alerts (zero jobs, slow runs, circuit breaks, daily digest) |
| **Geo support** | None | Country detection (75 countries, 200+ city patterns), 4 geo-topics |
| **Notifications** | Broadcast to topics only | + Personalized DM alerts with subscription filters |
| **Analytics** | None | REST API + web dashboard (stats, salary, trends) |
| **Env vars** | ~10 | 30+ |

## New Modules

### `core/` package (all new)

| Module | Purpose |
|--------|---------|
| `config.py` | Centralized environment variable loading (Supabase, Telegram, API keys) |
| `models.py` | `Job` dataclass with 20+ fields including salary_min/max, seniority, country, topics, telegram_message_ids |
| `db.py` | PostgreSQL access layer with connection pooling, CRUD, fuzzy matching, circuit breaker state |
| `enrichment.py` | Pipeline: salary parsing -> seniority detection -> country detection -> topic routing |
| `filtering.py` | Weighted keyword scoring with configurable threshold |
| `dedup.py` | Three-layer deduplication (URL exact + fuzzy title + batch internal) |
| `keywords.py` | Include/exclude keyword lists with scoring weights for 40+ categories |
| `salary_parser.py` | Freetext salary extraction (currencies, hourly/monthly/yearly normalization, k-suffix) |
| `seniority.py` | Regex-based classification: intern / junior / mid / senior / lead / executive |
| `country_detector.py` | Location string -> ISO country code (75 countries, 200+ city patterns) |
| `geo.py` | Geo-filtering rules (Egypt/Saudi = all jobs, rest = remote only) |
| `channels.py` | 11 tech + 4 geo Telegram topics, 170+ routing keywords per topic |
| `circuit_breaker.py` | Per-source retry with exponential backoff (2s, 5s), 3-strike circuit, DB-persisted |
| `monitoring.py` | Post-run anomaly checks + admin Telegram alerts + daily digest |
| `logging_config.py` | Structured JSON logging |

### `bot/` package (rewritten)

V1 had a simple `telegram_sender.py` that just posted messages. V2 adds full interactivity:

| Module | Purpose |
|--------|---------|
| `app.py` | Bot application factory with handler registration |
| `commands.py` | 10 commands: `/subscribe`, `/unsubscribe`, `/mysubs`, `/search`, `/saved`, `/stats`, `/top`, `/salary`, `/start`, `/help` |
| `callbacks.py` | Inline button handlers for subscription flows, pagination, save/report actions |
| `keyboards.py` | Dynamic inline keyboard generation for multi-step flows |
| `sender.py` | Job formatting (HTML + emoji) with inline buttons (Apply, Save, Report), multi-topic routing, message ID tracking |
| `notifications.py` | Personalized DM alerts matching user subscriptions, rate-limited (20/user/hour) |

### `api/` package (new)

FastAPI backend for the web dashboard:

| Module | Purpose |
|--------|---------|
| `app.py` | FastAPI factory with CORS + rate limiting (slowapi) |
| `routes_jobs.py` | `GET /api/jobs/search` -- full-text search with filters (seniority, source, country), pagination |
| `routes_stats.py` | `GET /api/stats` (summary), `GET /api/salary` (breakdowns with percentiles), `GET /api/trends` (weekly skill trends) |
| `middleware.py` | Rate limiting configuration (30 req/min) |

### `dashboard/` (new)

React 19 + TypeScript + Vite + TailwindCSS + Recharts:

| Page | Purpose |
|------|---------|
| Home | Job listing with search bar, filters (source, seniority, country, remote toggle), infinite scroll |
| Stats | Bar/pie charts showing jobs by source, topic, company |
| Salary | Salary distributions by seniority, role, country (line charts, percentiles) |
| Trends | Skill popularity trends over time (week-over-week % change) |

## Database (Supabase PostgreSQL)

8 tables defined in `supabase/migrations/001_init.sql`:

| Table | Purpose |
|-------|---------|
| `jobs` | Full job records with enrichment fields, trigram + GIN indexes |
| `users` | Telegram subscribers with JSONB subscriptions (topics, seniority, keywords, min_salary) |
| `user_saved_jobs` | Bookmarks (user_id, job_id) |
| `bot_runs` | Execution tracking (jobs_fetched, jobs_filtered, jobs_new, jobs_sent, source_stats, errors) |
| `source_health` | Circuit breaker state (consecutive_failures, circuit_open_until, last_error) |
| `job_feedback` | User feedback (save, report) |
| `jobs_archive` | Archived old jobs (same schema, fewer indexes) |

Row Level Security enabled on all tables. `anon` role limited to SELECT on `jobs`.

## GitHub Actions Workflows

| Workflow | V1 | V2 |
|----------|----|----|
| `deploy_backend.yml` | -- | Auto-deploy backend on push |
| `deploy_dashboard.yml` | -- | Builds React app (GitHub Pages; moving to Vercel) |
| `ci.yml` | -- | CI gate: tests, lint, typecheck, build |
| `archive_jobs.yml` | -- | Removed (run archival via server cron instead) |
| `job_bot.yml` | Basic cron, ~10 env vars | Removed (server.py scheduler replaced it) |

## Test Suite (new)

9 test files in `tests/`:

- `test_models.py` -- Job dataclass serialization
- `test_db.py` -- Database CRUD, fuzzy dedup, circuit breaker state
- `test_filtering.py` -- Keyword scoring, geo-filtering
- `test_dedup.py` -- URL normalization, batch dedup
- `test_enrichment.py` -- Salary/seniority/country/topic enrichment
- `test_salary_parser.py` -- Salary extraction edge cases
- `test_seniority.py` -- Seniority classification
- `test_country_detector.py` -- Country/city pattern matching
- `test_circuit_breaker.py` -- Retry logic and circuit state

## Dependencies Added

**Backend:** psycopg2-binary, python-telegram-bot 21+, fastapi, uvicorn, slowapi, python-json-logger, python-dotenv

**Frontend:** React 19, React Router, Recharts, Tailwind CSS 4, Vite, Supabase client, TypeScript 6

## Post-V2 Update: Durable Delivery Queue (2026-09)

Decoupled Telegram delivery from ingestion using a PostgreSQL-backed durable queue. No new infrastructure — Postgres is the queue.

| | Before | After |
|---|--------|-------|
| **Send cap** | First 50 jobs per run sent; rest lost | No cap — every job enqueued, delivered independently |
| **Scheduling** | One loop: fetch + send + notify every 5 min | Fetch (ingest/enqueue) every 5 min + delivery every 60s, independent and overlapping |
| **Delivery tracking** | `jobs.sent_at` (one flag per job) | `job_deliveries` row per (job, topic) and per (job, subscriber) |
| **Failure handling** | Failed topic = job unsent; DM failures dropped | Per-record retry with backoff (5 attempts, 30s base), stale-worker lease recovery, dead-letter + replay |
| **DM rate limit** | Excess DMs dropped | Excess deferred back to pending, drained in later cycles |
| **Restarts** | In-flight batch lost | Queue survives restarts (durable Postgres state) |
| **Dead ends** | Silent drops | Explicit `dead_letter` / `skipped` states with reasons; admin alerts |

New pieces: `job_deliveries` table (migration `007`), `core/delivery_queue.py`, `core/delivery_scheduler.py`, `core/subscription_matching.py`, `scripts/backfill_job_deliveries.py`, backfill of pre-queue unsent jobs, queue-aware monitoring. See `docs/ARCHITECTURE.md — Delivery Queue Operations` for the runbook.

## Post-V2 Update: Admin Dashboard — Milestone 1 (2026-10)

Began the admin-only dashboard program. Milestone 1 is a baseline & boundary milestone
(no auth yet): documentation + CI, dependency upgrades, removal of direct Supabase
browser access, removal of anonymous database grants, removal of GitHub Pages routing,
and boundary tests. JWT auth, RBAC, and TOTP are explicitly deferred to later milestones.

See [ADMIN_DASHBOARD_CHANGELOG.md](ADMIN_DASHBOARD_CHANGELOG.md) for the per-change log
and [ADMIN_DASHBOARD.md](ADMIN_DASHBOARD.md) for the design.
