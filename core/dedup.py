"""
Fuzzy deduplication using three layers:
1. Exact URL match
2. Title + Company similarity (pg_trgm, when DB is available)
3. Batch-internal dedup

Designed to work with or without a database connection.
When DB is unavailable (e.g. unit tests), only URL and batch dedup run.
"""

import logging
from typing import Optional
from core.models import Job

log = logging.getLogger(__name__)


def normalize_url(url: str) -> str:
    """Normalize a URL for comparison: strip tracking params, trailing slash, lowercase."""
    if not url:
        return ""
    clean = url.split("?utm")[0].split("&utm")[0]
    clean = clean.rstrip("/").lower()
    return clean


def is_duplicate_url(url: str, seen_ids: set) -> bool:
    """Check if a normalized URL is in the seen set."""
    return normalize_url(url) in seen_ids


def deduplicate_batch(jobs: list[Job], seen_ids: set) -> list[Job]:
    """
    Deduplicate a batch of jobs against seen IDs and within the batch itself.
    Uses URL-based exact matching. Does NOT use DB (fuzzy dedup is separate).

    Args:
        jobs: List of jobs to deduplicate
        seen_ids: Set of already-seen unique_ids (normalized URLs or title|company hashes)

    Returns: List of new, unique jobs
    """
    new_jobs = []
    batch_ids = set()

    for job in jobs:
        uid = job.unique_id
        if uid in seen_ids:
            continue
        if uid in batch_ids:
            continue
        batch_ids.add(uid)
        new_jobs.append(job)

    log.info(f"Dedup: {len(jobs)} total -> {len(new_jobs)} new (batch)")
    return new_jobs


def fuzzy_dedup_against_db(job: Job, db_module=None) -> Optional[int]:
    """
    Check if a job is a fuzzy duplicate of an existing DB job.
    Uses pg_trgm similarity on title + exact company match.

    Args:
        job: The job to check
        db_module: The core.db module (passed to avoid circular imports)

    Returns: ID of the existing duplicate job, or None if no duplicate found.
    """
    if db_module is None:
        return None

    try:
        rows = db_module._fetchall(
            """SELECT id, title, company, salary_raw, tags
               FROM jobs
               WHERE created_at > now() - make_interval(days := 7)
                 AND lower(company) = lower(%s)
                 AND similarity(title, %s) > 0.7
               LIMIT 1""",
            (job.company, job.title),
        )
        if rows:
            existing = rows[0]
            log.debug(
                f"Fuzzy dupe found: '{job.title}' ~ '{existing['title']}' "
                f"(company: {job.company})"
            )
            return existing["id"]
    except Exception as e:
        log.warning(f"Fuzzy dedup query failed: {e}")

    return None


def should_replace_existing(new_job: Job, existing_row: dict) -> bool:
    """
    Determine if the new job has more data than the existing one.
    Used when a fuzzy duplicate is found to decide which version to keep.
    """
    score_new = 0
    score_existing = 0

    if new_job.salary_raw:
        score_new += 1
    if existing_row.get("salary_raw"):
        score_existing += 1

    if new_job.tags:
        score_new += len(new_job.tags)
    if existing_row.get("tags"):
        score_existing += len(existing_row["tags"])

    return score_new > score_existing
