# Self-hosting

SWE-Jobs runs on a Linux VPS with Docker Compose. The backend and PostgreSQL communicate over a private Docker network. The database port is not published to the internet.

## Requirements

- Linux VPS with Docker Engine and Docker Compose plugin.
- 2 GB RAM recommended because browser-based job sources use the Scrapling stealth browser.
- Telegram bot token, group ID, topic thread IDs, and any optional job-source API keys.

## Initial setup

Clone the repository on the VPS and create the environment file:

```bash
git clone https://github.com/Fighteros/SWE-Jobs.git
cd SWE-Jobs
cp .env.example .env
```

Edit `.env`. Set a strong `DB_PASSWORD`, Telegram credentials, topic IDs, and any API keys you use. The default `DB_HOST=db` and `DB_PORT=5432` are for Compose networking.

Start the stack and check service health:

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f backend
```

The API listens on port `8000` by default. The database stays private. To access it for maintenance, use `docker compose exec db psql -U postgres -d postgres`.

## Deploying updates

The `deploy_backend.yml` GitHub Actions workflow pulls `main`, runs `docker compose up -d --build` on the configured server, then polls the backend `/health` endpoint and fails the run if the new build does not come up healthy. Set the repository secrets `SERVER_HOST`, `SERVER_USER`, `SERVER_SSH_KEY`, and `PROJECT_PATH`. Application configuration remains in the server's `.env` file.

Deploys are serialized with a GitHub Actions concurrency group, so two pushes can no longer race on the server's git checkout.

To get a Telegram message for every deploy result (success or failure), also set the repository secrets `TELEGRAM_BOT_TOKEN` (the bot token) and `TELEGRAM_ADMIN_CHAT_ID` (your Telegram user ID, same value as `ADMIN_TELEGRAM_ID` in `.env`). Without them the notification step skips silently. The `archive_jobs.yml` workflow sends the same notifications and applies `postgres/migrations/008_jobs_archive.sql` automatically before archiving, so older databases get the previously missing `jobs_archive` table.

For a manual update:

```bash
git pull --ff-only origin main
docker compose up -d --build
```

## Crash resilience and alerting

Three layers keep the bot from going down silently:

1. **In-process supervision.** The Telegram poller is supervised (`bot/polling.py`): transient Telegram outages heal in-process, unrecoverable states exit the container so Docker (`restart: unless-stopped`) brings it back. The admin gets a Telegram message when polling recovers and before a fatal exit.
2. **Health-gated restart.** `/health` returns 503 while the polling supervisor is not running, so the Docker healthcheck fails for a bot-down backend. The `autoheal` service in `docker-compose.yml` watches the healthcheck and restarts the unhealthy container. It needs access to the Docker socket; remove the `autoheal` service if you do not want that.
3. **Telegram alerts.** On every backend (re)start a message is sent (`STARTUP_ALERT=true` in `.env`), and repeated fetch, delivery, or supervisor failures alert after `ALERT_CONSECUTIVE_FAILURES` (default 3) consecutive errors, plus a recovery message when they succeed again. All alerts go to `ADMIN_TELEGRAM_ID` via the bot token.

## Database migrations

The Postgres image applies files from `postgres/migrations/` only when it initializes an empty data volume. For an existing database, apply each new migration once, in order:

```bash
docker compose exec -T db psql -U postgres -d postgres -v ON_ERROR_STOP=1 -f - < postgres/migrations/007_job_deliveries.sql
```

Use the migration file that is new for your deployment. After adding the durable delivery queue to an existing database, backfill subscriber deliveries with:

```bash
docker compose exec -T backend python -m scripts.backfill_job_deliveries
```

The backfill is idempotent. Check queue counts with:

```bash
docker compose exec db psql -U postgres -d postgres -c "SELECT status, delivery_type, COUNT(*) FROM job_deliveries GROUP BY 1,2 ORDER BY 1;"
```

## Backups and restore

Create a compressed logical backup with the included script:

```bash
mkdir -p backups
./scripts/backup_db.sh
```

Copy backups off the VPS and retain them according to your recovery needs. To restore into an initialized database:

```bash
gunzip -c backups/swejobs_YYYYMMDD_HHMMSS.sql.gz | docker compose exec -T db psql -U postgres -d postgres -v ON_ERROR_STOP=1
```

The `backups/` directory is ignored by Git.
