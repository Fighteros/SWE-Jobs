# SWE-Jobs

SWE-Jobs collects software and technology jobs from 30+ sources, enriches and filters listings, then delivers them to Telegram topics and subscriber alerts. It runs as a self-hosted Docker Compose service with a FastAPI backend, Telegram bot, scheduled ingestion and delivery workers, and PostgreSQL.

## What it does

- Fetches listings from remote, regional, social, and ATS job sources.
- Enriches listings with location, seniority, salary, and Telegram topic data.
- Filters and deduplicates jobs, then queues each Telegram delivery in PostgreSQL.
- Supports Telegram search, subscriptions, saved jobs, application tracking, salary insights, and support messages.
- Exposes a FastAPI API and health endpoint.
- Runs on a VPS with Docker Compose; GitHub Actions redeploys the backend and archives old jobs.

## Run locally

Requirements: Docker Compose, a Telegram bot token, a Telegram group, and topic IDs. Optional source API keys are configured through environment variables.

```bash
git clone https://github.com/Fighteros/SWE-Jobs.git
cd SWE-Jobs
Copy-Item .env.example .env  # PowerShell; use cp on macOS/Linux
```

Set `DB_PASSWORD`, Telegram credentials, topic IDs, and any source API keys in `.env`, then start the stack:

```bash
docker compose up -d --build
docker compose logs -f backend
```

The backend API listens on port `8000` by default. `GET /health` reports backend and Telegram polling status. PostgreSQL is private to the Compose network and is not published to the host.

For a production VPS setup, backups, and database operations, see [Self-hosting](docs/SELF_HOSTING.md). For environment variables, see [Configuration](docs/CONFIGURATION.md).

## Development

```bash
python -m venv .venv
python -m pip install -r requirements.txt -r requirements-dev.txt
Copy-Item .env.example .env
```

Run the application and PostgreSQL together with `docker compose up -d --build`. The database is private to the Compose network, so run the backend in Compose unless you deliberately configure a local database connection.

The test suite is under `tests/`. PostgreSQL integration tests require `TEST_DATABASE_URL`.

## Repository layout

```text
api/                 FastAPI application and routes
bot/                 Telegram bot, polling, and message delivery
core/                Database, filtering, enrichment, queue, and scheduling
docker/postgres/     PostgreSQL image and role initialization
postgres/migrations/ Ordered database schema migrations
docs/                Current architecture and operating guides
scripts/             Backup, migration, and maintenance utilities
sources/             Job source fetchers
tests/               Unit and PostgreSQL integration tests
```

## Deployment

Pushes to `main` run `.github/workflows/deploy_backend.yml`, which updates the configured VPS over SSH and rebuilds the Compose services. `.github/workflows/archive_jobs.yml` archives old delivered jobs weekly. The server's own schedulers handle recurring ingestion and Telegram delivery.
