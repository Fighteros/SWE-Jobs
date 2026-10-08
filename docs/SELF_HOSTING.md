# Self-hosting

SWE-Jobs runs on a Linux VPS with Docker Compose. The backend and PostgreSQL communicate over a private Docker network. The database port is not published to the internet.

## Requirements

- Linux VPS with Docker Engine and Docker Compose plugin.
- 2 GB RAM recommended because browser-based job sources use Playwright.
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

The `deploy_backend.yml` GitHub Actions workflow pulls `main` and runs `docker compose up -d --build` on the configured server. Set the repository secrets `SERVER_HOST`, `SERVER_USER`, `SERVER_SSH_KEY`, and `PROJECT_PATH`. Application configuration remains in the server's `.env` file.

For a manual update:

```bash
git pull origin main
docker compose up -d --build
```

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
