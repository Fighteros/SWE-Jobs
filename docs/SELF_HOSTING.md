# Self-hosting SWE-Jobs on your own server (VPS)

Run the **bot + Postgres database together** on one Linux VPS with Docker Compose.
The database stays private — bound to `localhost` on the server — and the bot reaches
it over the internal Docker network at `db:5432`. **Nothing about the DB is exposed to
the internet.**

## Requirements
- A Linux VPS (Ubuntu/Debian assumed below), **≥ 2 GB RAM** recommended — the bot
  bundles Playwright + Chromium for some scrapers; 1 GB may OOM.
- ~3 GB free disk for images + data.
- Your Telegram bot token, group/topic IDs, and API keys (same values as before).

## 1. Install Docker (skip if already installed)
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # log out/in afterwards so `docker` works without sudo
```

## 2. Get the code
```bash
git clone https://github.com/Fighteros/SWE-Jobs.git && cd SWE-Jobs   # fresh server
# or, if the repo is already on the server:   cd SWE-Jobs && git pull
# Everything is on main — no branch checkout needed.
```

## 3. Create `.env`
`.env` is gitignored — create it on the server. Set the database block to the container
and fill in your existing Telegram/API values:
```
DB_HOST=db
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=<a-strong-password>
DB_SSLMODE=disable

TELEGRAM_BOT_TOKEN=...
TELEGRAM_GROUP_ID=...
# TOPIC_*, RAPIDAPI_KEY, ADZUNA_*, ADMIN_TELEGRAM_ID, etc. — see .env.example
```

## 4. Start the stack
```bash
docker compose up -d --build      # builds + starts db (waits healthy) then backend
docker compose ps
```

## 5. Import your data
**Option A — copy the dump you already made** (from your PC):
```bash
# on your PC:
scp swejobs_data.sql USER@YOUR_VPS:~/SWE-Jobs/
# on the VPS:
docker compose cp swejobs_data.sql db:/tmp/swejobs_data.sql
docker compose exec -T db psql -U postgres -d postgres -v ON_ERROR_STOP=1 -f /tmp/swejobs_data.sql
```
**Option B — re-dump straight from Supabase on the VPS** (if still reachable):
```bash
docker run --rm -e PGPASSWORD='<supabase-db-password>' -e PGSSLMODE=require -v "$PWD:/out" postgres:17-alpine \
  pg_dump -h aws-1-eu-west-1.pooler.supabase.com -p 5432 -U postgres.<project-ref> -d postgres \
  --data-only --no-owner --no-privileges --disable-triggers \
  -t public.jobs -t public.jobs_archive -t public.users -t public.user_saved_jobs \
  -t public.bot_runs -t public.source_health -t public.job_feedback \
  -t public.user_applications -t public.user_alerts -t public.support_messages \
  -f /out/swejobs_data.sql
docker compose cp swejobs_data.sql db:/tmp/swejobs_data.sql
docker compose exec -T db psql -U postgres -d postgres -v ON_ERROR_STOP=1 -f /tmp/swejobs_data.sql
```

## 6. Verify
```bash
docker compose exec -T db psql -U postgres -d postgres -c "SELECT count(*) FROM jobs;"
docker compose logs -f backend     # watch it connect + run; Ctrl-C to stop tailing
```

## Backups — this is now your responsibility
You no longer have Supabase's managed backups. Schedule nightly dumps with the included
script:
```bash
crontab -e
# add (runs 3am daily):
0 3 * * * cd ~/SWE-Jobs && ./scripts/backup_db.sh >> backups/backup.log 2>&1
```
Restore from a backup:
```bash
docker compose down -v && docker compose up -d --build db        # fresh schema
zcat backups/swejobs_YYYYMMDD_HHMMSS.sql.gz | docker compose exec -T db psql -U postgres -d postgres
```

## Updating later
```bash
git pull
docker compose up -d --build
```

**Important:** the Postgres container applies `supabase/migrations/` only on the
**first boot** of an empty data volume. When a new migration file lands, apply it
to your existing database manually, e.g.:
```bash
docker compose exec -T db psql -U postgres -d postgres -f - < supabase/migrations/007_job_deliveries.sql
```

### After deploying the durable delivery queue (migration 007)
1. Apply the migration (command above).
2. Backfill subscriber-DM records for pre-queue jobs (idempotent, safe to re-run):
   ```bash
   docker compose exec -T backend python -m scripts.backfill_job_deliveries
   ```
3. Decide what to do with the old backlog (jobs the previous 50-job cap never
   sent). By default they will all deliver. To skip everything older than 7 days:
   ```bash
   docker compose exec db psql -U postgres -d postgres -c \
     "UPDATE job_deliveries jd SET status='skipped', dead_letter_reason='stale_backlog'
      FROM jobs j WHERE jd.job_id=j.id AND jd.status='pending'
      AND j.created_at < now() - interval '7 days';"
   ```
4. Verify both schedulers are running:
   ```bash
   docker compose logs --tail 50 backend | grep -E "Fetch scheduler|Delivery scheduler"
   docker compose exec db psql -U postgres -d postgres -c \
     "SELECT status, delivery_type, COUNT(*) FROM job_deliveries GROUP BY 1,2 ORDER BY 1;"
   ```

See [ARCHITECTURE.md — Delivery Queue Operations](ARCHITECTURE.md#delivery-queue-operations)
for monitoring, dead-letter replay, and backlog management.

## Security notes
- **The DB is private.** It's published only on `127.0.0.1:15432` on the server (for your
  own `psql`/GUI over an SSH tunnel). The bot uses the internal network, so you can even
  delete the `ports:` block on the `db` service to lock it down completely.
- **Port 8000** (the FastAPI/dashboard API) is only needed if your separately-deployed
  dashboard calls the backend. If so, put it behind a reverse proxy (Caddy/Nginx) with
  HTTPS. The Telegram bot itself needs **no inbound ports**.
