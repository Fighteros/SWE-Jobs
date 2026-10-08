# Architecture

SWE-Jobs runs on a self-hosted VPS as a Docker Compose stack. The `backend` service runs the FastAPI application, Telegram polling supervisor, job-fetch scheduler, and delivery scheduler. The `db` service runs PostgreSQL on the private Compose network.

## Job and delivery flow

1. The fetch scheduler calls the registered fetchers in `sources/`.
2. The pipeline enriches jobs with salary, seniority, country, and Telegram topic data, then filters and deduplicates them.
3. New jobs and their delivery records are written to PostgreSQL.
4. The independent delivery scheduler claims queued records and sends messages to Telegram topics or subscriber DMs.
5. Retryable failures remain queued with backoff; permanent failures are recorded as dead letters.

Fetch timing is controlled by `FETCH_INTERVAL_MINUTES`. Delivery timing and limits use the `DELIVERY_*` and `DM_*` settings documented in [Configuration](CONFIGURATION.md).

## Main components

- `sources/`: job board and ATS fetchers; `sources/__init__.py` registers active fetchers.
- `core/`: filtering, enrichment, PostgreSQL access, durable delivery queue, schedulers, and monitoring.
- `bot/`: Telegram commands, callbacks, polling, formatting, and sending.
- `api/`: FastAPI routes for job search, stats, salary, trends, and `/health`.
- `postgres/migrations/`: ordered SQL schema migrations. The custom PostgreSQL image loads these on first initialization.
- `docker-compose.yml`: private PostgreSQL plus the long-running backend service.

## Database and operations

PostgreSQL is the source of truth for jobs, Telegram users, subscriptions, source health, and pending deliveries. `pg_trgm` supports fuzzy job deduplication. Database credentials are read from `.env`.

The Postgres entrypoint applies initialization scripts only when its data volume is empty. For an existing database, apply new migration files manually, then rebuild and restart the backend as needed. See [Self-hosting](SELF_HOSTING.md) for deployment, migration, and backup commands.

## Runtime and deployment

`server.py` runs the FastAPI API and supervised bot/schedulers in one service. `GET /health` is used by the Docker health check. `main.py` provides a one-off ingestion run and should not run concurrently with the server's fetch scheduler.

`.github/workflows/deploy_backend.yml` updates the VPS on pushes to `main`. `.github/workflows/archive_jobs.yml` archives old delivered jobs weekly. The server handles recurring fetch and delivery work; GitHub Actions does not run the bot pipeline.
