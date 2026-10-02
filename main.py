"""
Programming Jobs Bot v2 — Main entry point.
Orchestrates: fetch (with circuit breaker) -> enrich -> filter -> dedup -> insert -> enqueue.
Telegram delivery is handled independently by the delivery scheduler.
"""

import os
import asyncio
import logging
import time
from datetime import datetime, timezone

from core.logging_config import setup_logging
from core.config import SEED_MODE_ENV, TELEGRAM_BOT_TOKEN
from core import db_async as adb
from core.delivery_queue import enqueue_job_deliveries
from core.enrichment import enrich_job
from core.filtering import filter_jobs
from core.dedup import deduplicate_batch
from core.circuit_breaker import fetch_with_retry
from sources import ALL_FETCHERS

setup_logging()
log = logging.getLogger("main")


async def main():
    start = time.time()
    log.info("Programming Jobs Bot v2 — Starting ingestion run")

    # ── 1. Start run tracking ──────────────────────────────
    run_id = await adb.start_run()
    source_stats = {}
    errors = []

    is_seed = os.getenv(SEED_MODE_ENV, "").lower() in ("1", "true", "yes")
    if is_seed:
        log.info("SEED MODE: will register all jobs without creating live deliveries")

    # ── 2. Fetch from all sources in parallel ────────────────
    # Limit concurrency for API-heavy sources that share rate limits.
    _api_semaphore = asyncio.Semaphore(4)

    async def _fetch_one(name, source_key, fetcher):
        async with _api_semaphore:
            jobs = await asyncio.to_thread(fetch_with_retry, source_key, fetcher)
        return name, source_key, jobs

    log.info(f"Fetching from {len(ALL_FETCHERS)} sources in parallel...")
    fetch_tasks = [
        _fetch_one(name, key, fetcher)
        for name, key, fetcher in ALL_FETCHERS
    ]
    results = await asyncio.gather(*fetch_tasks)

    all_jobs = []
    fetch_summary = []
    for name, source_key, jobs in results:
        all_jobs.extend(jobs)
        source_stats[source_key] = len(jobs)
        if not jobs:
            errors.append({"source": source_key, "error": "no jobs returned"})
        fetch_summary.append(f"{name}={len(jobs)}")

    # Track total jobs attempted (fetched) for monitoring queue-rate alert.
    source_stats["_jobs_attempted"] = len(all_jobs)

    log.info(f"Fetched {len(all_jobs)} jobs: {', '.join(fetch_summary)}")

    # ── 3. Enrich all jobs ──────────────────────────────────
    for job in all_jobs:
        enrich_job(job)

    # ── 4. Filter (weighted scoring + geo) ──────────────────
    filtered = filter_jobs(all_jobs)
    log.info(f"After filtering: {len(filtered)} jobs")

    # ── 5. Deduplicate ──────────────────────────────────────
    # Get existing unique_ids from DB
    existing = await adb._fetchall("SELECT unique_id FROM jobs")
    seen_ids = {row["unique_id"] for row in existing}

    new_jobs = deduplicate_batch(filtered, seen_ids)
    log.info(f"New jobs: {len(new_jobs)}")

    # ── 6. Fuzzy dedup + batch insert ─────────────────────
    non_dupes = await adb.fuzzy_dedup_batch(new_jobs)
    fuzzy_dupes = len(new_jobs) - len(non_dupes)
    log.info(f"Fuzzy dedup: {fuzzy_dupes} duplicates removed, {len(non_dupes)} remaining")

    inserted_rows = await adb.insert_jobs_batch(non_dupes)
    # Build (Job, db_id) list for enqueueing deliveries
    now = datetime.now(timezone.utc)
    uid_to_job = {job.unique_id: job for job in non_dupes}
    inserted_jobs = []
    for row in inserted_rows:
        job = uid_to_job[row["unique_id"]]
        if not job.created_at:
            job.created_at = now  # fallback for posted_display when posted_at is None
        inserted_jobs.append((job, row["id"]))
    log.info(f"Inserted: {len(inserted_jobs)} jobs")

    # ── 7. Enqueue deliveries (never send here) ─────────────
    delivery_stats = {"group_topic_queued": 0, "subscriber_dm_queued": 0}
    if inserted_jobs:
        if is_seed:
            log.info(f"Seed mode: marking {len(inserted_jobs)} jobs as skipped deliveries")
        delivery_stats = await asyncio.to_thread(
            enqueue_job_deliveries, inserted_jobs, is_seed=is_seed
        )
        log.info(
            f"Enqueued deliveries: {delivery_stats['group_topic_queued']} group-topic, "
            f"{delivery_stats['subscriber_dm_queued']} subscriber-DM"
        )
    else:
        log.info("No new jobs to enqueue")

    # ── 8. Finish run tracking ──────────────────────────────
    await adb.finish_run(
        run_id,
        jobs_fetched=len(all_jobs),
        jobs_filtered=len(filtered),
        jobs_new=len(new_jobs),
        jobs_sent=len(inserted_jobs),
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
    log.info(
        f"Ingestion run complete in {elapsed:.1f}s. "
        f"Fetched={len(all_jobs)} Filtered={len(filtered)} New={len(new_jobs)} "
        f"QueuedGroup={delivery_stats.get('group_topic_queued', 0)} "
        f"QueuedDM={delivery_stats.get('subscriber_dm_queued', 0)}"
    )


if __name__ == "__main__":
    asyncio.run(main())
