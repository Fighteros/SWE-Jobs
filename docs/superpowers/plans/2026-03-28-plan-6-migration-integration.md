# Plan 6: Migration & Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire all v2 components together into a working system: rewrite `main.py` to use the new pipeline, migrate `seen_jobs.json` into PostgreSQL, update source fetchers to use the new Job model, update the GitHub Actions workflow, and retire v1 code.

**Architecture:** The new `main.py` orchestrates: fetch (with circuit breaker) → enrich → filter → dedup (DB-backed) → insert → send (with buttons) → notify subscribers → track run. Sources continue returning `Job` objects but the old root-level `config.py` and `models.py` are replaced by imports from `core/`.

**Tech Stack:** Python 3.11, psycopg2, python-telegram-bot

**Spec:** `docs/superpowers/specs/2026-03-28-v2-redesign-design.md` (Section 6)

**Depends on:** Plans 1-5 (everything)
**Blocks:** Nothing — this is the final plan

---

## File Structure

Changes to existing files:

```
main.py                     # REWRITE: new v2 pipeline
sources/__init__.py         # MODIFY: wrap fetchers with circuit breaker
sources/*.py                # MODIFY: update imports from config -> core.config, etc.
.github/workflows/
├── job_bot.yml             # MODIFY: add Supabase env vars, remove seen_jobs.json steps
└── archive_jobs.yml        # CREATE: weekly job archival workflow
scripts/
└── migrate_seen_jobs.py    # CREATE: one-time migration script
```

Files to delete after migration:
```
config.py                   # Replaced by core/config.py + core/keywords.py + core/channels.py + core/geo.py
models.py                   # Replaced by core/models.py
dedup.py                    # Replaced by core/dedup.py
telegram_sender.py          # Replaced by bot/sender.py
```

---

### Task 1: Migration Script — Import seen_jobs.json into PostgreSQL

**Files:**
- Create: `scripts/migrate_seen_jobs.py`

- [ ] **Step 1: Write the migration script**

```python
# scripts/migrate_seen_jobs.py
"""
One-time migration: import seen_jobs.json URLs into the jobs table.
This prevents re-sending jobs that were already sent in v1.

Usage:
  1. Checkout the data branch: git checkout origin/data -- seen_jobs.json
  2. Run: python scripts/migrate_seen_jobs.py
  3. Delete seen_jobs.json when done
"""

import json
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)


def main():
    seen_file = "seen_jobs.json"

    try:
        with open(seen_file, "r", encoding="utf-8") as f:
            seen_ids = json.load(f)
    except FileNotFoundError:
        log.error(f"{seen_file} not found. Fetch it from the data branch first.")
        sys.exit(1)

    if not isinstance(seen_ids, list):
        log.error(f"Expected a JSON array, got {type(seen_ids)}")
        sys.exit(1)

    log.info(f"Found {len(seen_ids)} seen job IDs to migrate")

    from core import db

    inserted = 0
    skipped = 0
    for uid in seen_ids:
        if not uid or not isinstance(uid, str):
            skipped += 1
            continue

        # Insert minimal row — just enough to prevent re-sending
        try:
            result = db._execute(
                """INSERT INTO jobs (unique_id, title, company, location, url, source, sent_at)
                   VALUES (%s, %s, %s, %s, %s, %s, now())
                   ON CONFLICT (unique_id) DO NOTHING
                   RETURNING id""",
                (uid, "Migrated from v1", "", "", uid if uid.startswith("http") else "", "v1_migration"),
            )
            if result:
                inserted += 1
            else:
                skipped += 1
        except Exception as e:
            log.warning(f"Failed to insert {uid[:50]}: {e}")
            skipped += 1

    log.info(f"Migration complete: {inserted} inserted, {skipped} skipped (of {len(seen_ids)} total)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add scripts/migrate_seen_jobs.py
git commit -m "feat: add v1 -> v2 migration script for seen_jobs.json"
```

---

### Task 2: Update Source Fetchers — Imports

**Files:**
- Modify: all 15 `sources/*.py` files
- Modify: `sources/__init__.py`

The source fetchers currently import `from models import Job` and `import config`. They need to import from `core/` instead. The `Job` dataclass in `core/models.py` has additional fields with defaults, so existing source code that creates `Job(...)` objects will continue to work — new fields default to empty/None.

- [ ] **Step 1: Update imports in all source files**

For each file in `sources/` (except `__init__.py` and `http_utils.py`), change:
```python
# OLD
from models import Job
import config
# or
from config import RAPIDAPI_KEY, ...

# NEW
from core.models import Job
from core.config import RAPIDAPI_KEY, ...  # (only the specific keys they use)
```

Files to update:
- `sources/remotive.py`: `from models import Job` → `from core.models import Job`
- `sources/himalayas.py`: same
- `sources/jobicy.py`: same
- `sources/remoteok.py`: same
- `sources/arbeitnow.py`: same
- `sources/wwr.py`: same
- `sources/workingnomads.py`: same
- `sources/jsearch.py`: `from models import Job` + `from config import RAPIDAPI_KEY` → `from core.models import Job` + `from core.config import RAPIDAPI_KEY`
- `sources/linkedin.py`: same pattern
- `sources/adzuna.py`: `from config import ADZUNA_APP_ID, ADZUNA_APP_KEY` → `from core.config import ...`
- `sources/themuse.py`: same pattern
- `sources/findwork.py`: same pattern
- `sources/jooble.py`: same pattern
- `sources/reed.py`: same pattern
- `sources/usajobs.py`: same pattern

Also update `sources/http_utils.py`:
```python
# OLD
from config import REQUEST_TIMEOUT
# NEW
from core.config import REQUEST_TIMEOUT
```

- [ ] **Step 2: Update sources/__init__.py to use circuit breaker**

```python
# sources/__init__.py
"""
Source registry with circuit breaker integration.
"""

from sources.remotive import fetch_remotive
from sources.himalayas import fetch_himalayas
from sources.jobicy import fetch_jobicy
from sources.remoteok import fetch_remoteok
from sources.arbeitnow import fetch_arbeitnow
from sources.wwr import fetch_wwr
from sources.workingnomads import fetch_workingnomads
from sources.jsearch import fetch_jsearch
from sources.linkedin import fetch_linkedin
from sources.adzuna import fetch_adzuna
from sources.themuse import fetch_themuse
from sources.findwork import fetch_findwork
from sources.jooble import fetch_jooble
from sources.reed import fetch_reed
from sources.usajobs import fetch_usajobs

# (display_name, source_key, fetch_function)
ALL_FETCHERS = [
    ("Remotive",        "remotive",       fetch_remotive),
    ("Himalayas",       "himalayas",      fetch_himalayas),
    ("Jobicy",          "jobicy",         fetch_jobicy),
    ("RemoteOK",        "remoteok",       fetch_remoteok),
    ("Arbeitnow",       "arbeitnow",      fetch_arbeitnow),
    ("WWR",             "wwr",            fetch_wwr),
    ("Working Nomads",  "workingnomads",  fetch_workingnomads),
    ("JSearch",         "jsearch",        fetch_jsearch),
    ("LinkedIn",        "linkedin",       fetch_linkedin),
    ("Adzuna",          "adzuna",         fetch_adzuna),
    ("The Muse",        "themuse",        fetch_themuse),
    ("Findwork",        "findwork",       fetch_findwork),
    ("Jooble",          "jooble",         fetch_jooble),
    ("Reed",            "reed",           fetch_reed),
    ("USAJobs",         "usajobs",        fetch_usajobs),
]
```

- [ ] **Step 3: Verify sources still import cleanly**

Run:
```bash
cd G:/projects/SWE-Jobs && python -c "
from sources import ALL_FETCHERS
print(f'{len(ALL_FETCHERS)} fetchers registered')
for name, key, fn in ALL_FETCHERS:
    print(f'  {name} ({key}): {fn.__module__}.{fn.__name__}')
print('All sources OK')
"
```
Expected: 15 fetchers listed

- [ ] **Step 4: Commit**

```bash
git add sources/
git commit -m "feat: update source fetchers to import from core/ package"
```

---

### Task 3: Rewrite main.py — V2 Pipeline

**Files:**
- Rewrite: `main.py`

- [ ] **Step 1: Write the new main.py**

```python
# main.py
"""
Programming Jobs Bot v2 — Main entry point.
Orchestrates: fetch (with circuit breaker) → enrich → filter → dedup → insert → send → notify → track.
"""

import os
import sys
import asyncio
import logging
import time

from core.logging_config import setup_logging
from core.config import MAX_JOBS_PER_RUN, SEED_MODE_ENV, TELEGRAM_BOT_TOKEN
from core import db
from core.enrichment import enrich_job
from core.filtering import filter_jobs
from core.dedup import deduplicate_batch, fuzzy_dedup_against_db
from core.circuit_breaker import fetch_with_retry
from sources import ALL_FETCHERS

setup_logging()
log = logging.getLogger("main")


async def main():
    start = time.time()
    log.info("Programming Jobs Bot v2 — Starting run")

    # ── 1. Start run tracking ──────────────────────────────
    run_id = db.start_run()
    source_stats = {}
    errors = []

    is_seed = os.getenv(SEED_MODE_ENV, "").lower() in ("1", "true", "yes")
    if is_seed:
        log.info("SEED MODE: will register all jobs without sending")

    # ── 2. Fetch from all sources (with circuit breaker) ────
    all_jobs = []
    for name, source_key, fetcher in ALL_FETCHERS:
        log.info(f"Fetching from {name}...")
        jobs = fetch_with_retry(source_key, fetcher)
        all_jobs.extend(jobs)
        source_stats[source_key] = len(jobs)
        if not jobs:
            errors.append({"source": source_key, "error": "no jobs returned"})
        else:
            log.info(f"  {name}: {len(jobs)} raw jobs")

    log.info(f"Total raw jobs: {len(all_jobs)}")

    # ── 3. Enrich all jobs ──────────────────────────────────
    for job in all_jobs:
        enrich_job(job)

    # ── 4. Filter (weighted scoring + geo) ──────────────────
    filtered = filter_jobs(all_jobs)
    log.info(f"After filtering: {len(filtered)} jobs")

    # ── 5. Deduplicate ──────────────────────────────────────
    # Get existing unique_ids from DB
    existing = db._fetchall("SELECT unique_id FROM jobs")
    seen_ids = {row["unique_id"] for row in existing}

    new_jobs = deduplicate_batch(filtered, seen_ids)
    log.info(f"New jobs: {len(new_jobs)}")

    # ── 6. Insert into DB + fuzzy dedup ─────────────────────
    inserted_jobs = []  # List of (Job, db_id) tuples
    for job in new_jobs:
        # Check fuzzy duplicate
        dupe_id = fuzzy_dedup_against_db(job, db)
        if dupe_id:
            log.debug(f"Fuzzy dupe: {job.title} matches existing #{dupe_id}")
            continue

        result = db.insert_job(job)
        if result:
            inserted_jobs.append((job, result["id"]))

    log.info(f"Inserted: {len(inserted_jobs)} jobs")

    # ── 7. Send or seed ─────────────────────────────────────
    jobs_sent = 0
    if is_seed:
        log.info(f"Seed mode: {len(inserted_jobs)} jobs registered (no sending)")
    else:
        to_send = inserted_jobs[:MAX_JOBS_PER_RUN]
        if len(inserted_jobs) > MAX_JOBS_PER_RUN:
            log.warning(f"Capped to {MAX_JOBS_PER_RUN} (had {len(inserted_jobs)})")

        if to_send and TELEGRAM_BOT_TOKEN:
            from telegram import Bot
            from bot.sender import send_jobs
            from bot.notifications import notify_subscribers

            bot = Bot(token=TELEGRAM_BOT_TOKEN)
            async with bot:
                log.info(f"Sending {len(to_send)} jobs to Telegram...")
                jobs_sent = await send_jobs(bot, to_send)
                log.info(f"Sent {jobs_sent} messages")

                # Notify subscribers
                dm_count = await notify_subscribers(bot, to_send)
                log.info(f"Sent {dm_count} DM alerts")
        elif not TELEGRAM_BOT_TOKEN:
            log.warning("No TELEGRAM_BOT_TOKEN — skipping send")
        else:
            log.info("No new jobs to send")

    # ── 8. Finish run tracking ──────────────────────────────
    db.finish_run(
        run_id,
        jobs_fetched=len(all_jobs),
        jobs_filtered=len(filtered),
        jobs_new=len(new_jobs),
        jobs_sent=jobs_sent,
        source_stats=source_stats,
        errors=errors,
    )

    # ── 9. Check alerts ─────────────────────────────────────
    if TELEGRAM_BOT_TOKEN:
        try:
            from telegram import Bot
            from core.monitoring import check_alerts
            bot = Bot(token=TELEGRAM_BOT_TOKEN)
            async with bot:
                await check_alerts(bot, run_id)
        except Exception as e:
            log.warning(f"Alert check failed: {e}")

    elapsed = time.time() - start
    log.info(f"Run complete in {elapsed:.1f}s. Fetched={len(all_jobs)} Filtered={len(filtered)} New={len(new_jobs)} Sent={jobs_sent}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Commit**

```bash
git add main.py
git commit -m "feat: rewrite main.py with v2 pipeline (enrich, score, dedup, buttons, alerts)"
```

---

### Task 4: Update GitHub Actions Workflow

**Files:**
- Rewrite: `.github/workflows/job_bot.yml`
- Create: `.github/workflows/archive_jobs.yml`

- [ ] **Step 1: Rewrite job_bot.yml**

```yaml
name: Programming Jobs Bot v2

on:
  schedule:
    - cron: '*/5 * * * *'
  workflow_dispatch:

jobs:
  run-bot:
    runs-on: ubuntu-latest
    timeout-minutes: 10

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run bot
        env:
          # Supabase
          SUPABASE_DB_HOST: ${{ secrets.SUPABASE_DB_HOST }}
          SUPABASE_DB_PORT: ${{ secrets.SUPABASE_DB_PORT }}
          SUPABASE_DB_NAME: ${{ secrets.SUPABASE_DB_NAME }}
          SUPABASE_DB_USER: ${{ secrets.SUPABASE_DB_USER }}
          SUPABASE_DB_PASSWORD: ${{ secrets.SUPABASE_DB_PASSWORD }}
          # Telegram
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_GROUP_ID: ${{ secrets.TELEGRAM_GROUP_ID }}
          ADMIN_TELEGRAM_ID: ${{ secrets.ADMIN_TELEGRAM_ID }}
          # Topic Thread IDs
          TOPIC_GENERAL: ${{ secrets.TOPIC_GENERAL }}
          TOPIC_BACKEND: ${{ secrets.TOPIC_BACKEND }}
          TOPIC_FRONTEND: ${{ secrets.TOPIC_FRONTEND }}
          TOPIC_MOBILE: ${{ secrets.TOPIC_MOBILE }}
          TOPIC_DEVOPS: ${{ secrets.TOPIC_DEVOPS }}
          TOPIC_QA: ${{ secrets.TOPIC_QA }}
          TOPIC_AI_ML: ${{ secrets.TOPIC_AI_ML }}
          TOPIC_CYBERSECURITY: ${{ secrets.TOPIC_CYBERSECURITY }}
          TOPIC_GAMEDEV: ${{ secrets.TOPIC_GAMEDEV }}
          TOPIC_BLOCKCHAIN: ${{ secrets.TOPIC_BLOCKCHAIN }}
          TOPIC_EGYPT: ${{ secrets.TOPIC_EGYPT }}
          TOPIC_SAUDI: ${{ secrets.TOPIC_SAUDI }}
          TOPIC_INTERNSHIPS: ${{ secrets.TOPIC_INTERNSHIPS }}
          TOPIC_ERP: ${{ secrets.TOPIC_ERP }}
          # API Keys
          RAPIDAPI_KEY: ${{ secrets.RAPIDAPI_KEY }}
          ADZUNA_APP_ID: ${{ secrets.ADZUNA_APP_ID }}
          ADZUNA_APP_KEY: ${{ secrets.ADZUNA_APP_KEY }}
          FINDWORK_API_KEY: ${{ secrets.FINDWORK_API_KEY }}
          JOOBLE_API_KEY: ${{ secrets.JOOBLE_API_KEY }}
          REED_API_KEY: ${{ secrets.REED_API_KEY }}
          MUSE_API_KEY: ${{ secrets.MUSE_API_KEY }}
        run: python main.py
```

- [ ] **Step 2: Create archive_jobs.yml**

```yaml
name: Archive Old Jobs

on:
  schedule:
    - cron: '0 3 * * 0'  # Every Sunday at 3am UTC
  workflow_dispatch:

jobs:
  archive:
    runs-on: ubuntu-latest
    timeout-minutes: 5

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Archive old jobs
        env:
          SUPABASE_DB_HOST: ${{ secrets.SUPABASE_DB_HOST }}
          SUPABASE_DB_PORT: ${{ secrets.SUPABASE_DB_PORT }}
          SUPABASE_DB_NAME: ${{ secrets.SUPABASE_DB_NAME }}
          SUPABASE_DB_USER: ${{ secrets.SUPABASE_DB_USER }}
          SUPABASE_DB_PASSWORD: ${{ secrets.SUPABASE_DB_PASSWORD }}
        run: |
          python -c "
          from core import db

          # Move jobs older than 7 days to archive
          moved = db._execute('''
              WITH moved AS (
                  DELETE FROM jobs
                  WHERE created_at < now() - interval '7 days'
                    AND sent_at IS NOT NULL
                  RETURNING *
              )
              INSERT INTO jobs_archive
              SELECT * FROM moved
              ON CONFLICT (unique_id) DO NOTHING
          ''')
          print('Archive complete')

          # Delete archived jobs older than 90 days
          db._execute('''
              DELETE FROM jobs_archive
              WHERE created_at < now() - interval '90 days'
          ''')
          print('Pruned old archive entries')
          "
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/job_bot.yml .github/workflows/archive_jobs.yml
git commit -m "feat: update GitHub Actions for v2 (Supabase, no seen_jobs.json) + archival"
```

---

### Task 5: Delete V1 Files

**Files:**
- Delete: `config.py` (root level)
- Delete: `models.py` (root level)
- Delete: `dedup.py` (root level)
- Delete: `telegram_sender.py` (root level)

- [ ] **Step 1: Remove old files**

```bash
git rm config.py models.py dedup.py telegram_sender.py
```

- [ ] **Step 2: Clean up __pycache__**

Add to `.gitignore` if not already there:
```
__pycache__/
*.pyc
.env
```

```bash
git rm -r --cached __pycache__/ sources/__pycache__/ 2>/dev/null || true
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: remove v1 files (config, models, dedup, telegram_sender)"
```

---

### Task 6: End-to-End Verification

- [ ] **Step 1: Verify all imports work**

Run:
```bash
cd G:/projects/SWE-Jobs && python -c "
# Core
from core.config import TELEGRAM_BOT_TOKEN, SUPABASE_DB_HOST
from core.keywords import INCLUDE_KEYWORDS
from core.channels import CHANNELS
from core.geo import EGYPT_PATTERNS
from core.models import Job
from core.enrichment import enrich_job
from core.filtering import filter_jobs
from core.dedup import deduplicate_batch
from core.circuit_breaker import fetch_with_retry
from core.monitoring import check_alerts

# Sources
from sources import ALL_FETCHERS

# Bot
from bot.app import get_app
from bot.sender import format_job_message
from bot.commands import cmd_help
from bot.callbacks import handle_callback
from bot.notifications import notify_subscribers

# API
from api.app import create_app

print(f'Core: OK')
print(f'Sources: {len(ALL_FETCHERS)} fetchers')
print(f'Bot: OK')
print(f'API: OK')
print('All v2 imports successful')
"
```
Expected: All imports OK

- [ ] **Step 2: Run all tests**

Run: `cd G:/projects/SWE-Jobs && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 3: Dry run (no DB/Telegram needed)**

Run:
```bash
cd G:/projects/SWE-Jobs && python -c "
from core.models import Job
from core.enrichment import enrich_job
from core.filtering import is_programming_job, passes_geo_filter

# Simulate a job through the pipeline
job = Job(
    title='Senior Python Developer',
    company='Acme Corp',
    location='Cairo, Egypt',
    url='https://example.com/job/123',
    source='remotive',
    salary_raw='\$80,000 - \$120,000',
    is_remote=True,
    tags=['python', 'django'],
)

enriched = enrich_job(job)
print(f'Title: {enriched.title}')
print(f'Salary: {enriched.salary_min}-{enriched.salary_max} {enriched.salary_currency}')
print(f'Seniority: {enriched.seniority}')
print(f'Country: {enriched.country}')
print(f'Topics: {enriched.topics}')
print(f'Is programming job: {is_programming_job(enriched)}')
print(f'Passes geo filter: {passes_geo_filter(enriched)}')
print('Pipeline OK')
"
```
Expected: Shows enriched job with salary, seniority, country, topics

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete Plan 6 — v2 migration and integration done"
```

---

## Summary

After completing this plan:

- **New main.py** — full v2 pipeline with enrichment, scoring, fuzzy dedup, buttons, alerts
- **Source fetchers** — updated imports, wrapped with circuit breaker
- **GitHub Actions** — simplified (no more seen_jobs.json branch), Supabase-backed
- **Job archival** — weekly workflow keeps DB under 500MB
- **Migration script** — one-time import of seen_jobs.json into PostgreSQL
- **V1 code removed** — clean slate

## Deployment Checklist

After all 6 plans are implemented:

1. Create Supabase project, run `001_init.sql`
2. Add Supabase secrets to GitHub repository
3. Deploy FastAPI + bot to Render/Railway
4. Run migration: `python scripts/migrate_seen_jobs.py`
5. Trigger first run manually: GitHub Actions → Run workflow
6. Verify jobs appear in Telegram with buttons
7. Test bot commands (/subscribe, /search, /saved)
8. Deploy dashboard to GitHub Pages
9. Set up ADMIN_TELEGRAM_ID for alerts
10. Monitor first few automated runs
