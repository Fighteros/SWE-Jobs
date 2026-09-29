"""
core/delivery_queue.py — Durable PostgreSQL job-delivery queue.

This module owns the schema and operations for the job_deliveries table.
It is intentionally synchronous (built on core.db) so it works both directly
and through core.db_async's thread-pool facade.

Responsibilities:
  - Enqueue group-topic and subscriber-DM deliveries for newly inserted jobs.
  - Claim due records with FOR UPDATE SKIP LOCKED.
  - Record send success / retryable failure / permanent failure / skip.
  - Recover records stuck in processing longer than the lease.
  - Replay dead-letter records on request.
  - Backfill existing unsent jobs into delivery records.
"""

import json
import logging
import os
import socket
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg2.extras
from psycopg2.extras import RealDictCursor

from core import db
from core.models import Job

logger = logging.getLogger(__name__)

# Delivery types and statuses mirrored from the migration for convenience.
DELIVERY_TYPE_GROUP_TOPIC = "group_topic"
DELIVERY_TYPE_SUBSCRIBER_DM = "subscriber_dm"

STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_SENT = "sent"
STATUS_DEAD_LETTER = "dead_letter"
STATUS_SKIPPED = "skipped"


def _worker_id(prefix: str = "worker") -> str:
    """Generate a reasonably unique worker ID for lease tracking."""
    return (
        f"{prefix}-{socket.gethostname()}-{os.getpid()}-"
        f"{threading.current_thread().ident or 0}-{uuid.uuid4().hex[:8]}"
    )


# =============================================================================
# Build delivery records (enqueue helpers)
# =============================================================================

def _matching_alert(job: Job, alerts: list[dict]) -> Optional[dict]:
    """Return the first alert that matches the job and has dm_enabled=True."""
    from core.subscription_matching import job_matches_alert

    for alert in alerts:
        if not alert.get("dm_enabled", True):
            continue
        if job_matches_alert(job, alert):
            return alert
    return None


def build_group_topic_deliveries(
    jobs_with_ids: list[tuple[Job, int]],
    is_seed: bool = False,
) -> list[dict]:
    """
    Build delivery rows for every matching topic of each job.

    Returns a list of dicts ready for bulk insertion.
    Jobs with no topics produce a single skipped row.
    """
    now = datetime.now(timezone.utc)
    rows = []
    for job, db_id in jobs_with_ids:
        if not job.topics:
            rows.append({
                "job_id": db_id,
                "delivery_type": DELIVERY_TYPE_GROUP_TOPIC,
                "recipient_key": "",
                "status": STATUS_SKIPPED,
                "dead_letter_reason": "no topics assigned",
                "next_attempt_at": now,
            })
            continue

        for topic_key in job.topics:
            rows.append({
                "job_id": db_id,
                "delivery_type": DELIVERY_TYPE_GROUP_TOPIC,
                "recipient_key": topic_key,
                "status": STATUS_SKIPPED if is_seed else STATUS_PENDING,
                "dead_letter_reason": "seed_mode" if is_seed else None,
                "next_attempt_at": now,
            })
    return rows


def build_subscriber_dm_deliveries(
    jobs_with_ids: list[tuple[Job, int]],
    is_seed: bool = False,
) -> list[dict]:
    """
    Build subscriber-DM delivery rows for each (job, subscriber) pair where the
    subscriber has at least one matching alert with dm_enabled=True and the job
    is not blacklisted.

    Uses queue-time snapshot semantics: decisions are made now and persisted;
    later alert edits do not rewrite already-created rows.
    """
    from core.subscription_matching import job_blocked_by_blacklist

    now = datetime.now(timezone.utc)
    rows = []

    if not jobs_with_ids:
        return rows

    users = db._fetchall(
        "SELECT id, telegram_id FROM users WHERE notify_dm = TRUE"
    )
    if not users:
        return rows

    user_cache = {}
    for user in users:
        alerts = db.get_user_alerts(user["id"])
        blacklist = db.get_blacklist(user["id"])
        user_cache[user["telegram_id"]] = {"user": user, "alerts": alerts, "blacklist": blacklist}

    for job, db_id in jobs_with_ids:
        for telegram_id, cache in user_cache.items():
            alert = _matching_alert(job, cache["alerts"])
            if alert is None:
                continue
            if job_blocked_by_blacklist(job, cache["blacklist"]):
                continue

            rows.append({
                "job_id": db_id,
                "delivery_type": DELIVERY_TYPE_SUBSCRIBER_DM,
                "recipient_key": str(telegram_id),
                "status": STATUS_SKIPPED if is_seed else STATUS_PENDING,
                "dead_letter_reason": "seed_mode" if is_seed else None,
                "next_attempt_at": now,
            })

    return rows


# =============================================================================
# Bulk insert
# =============================================================================

def _insert_delivery_rows(rows: list[dict]) -> int:
    """Bulk-insert delivery rows, ignoring duplicates. Returns inserted count."""
    if not rows:
        return 0

    columns = [
        "job_id",
        "delivery_type",
        "recipient_key",
        "status",
        "dead_letter_reason",
        "next_attempt_at",
    ]
    col_str = ", ".join(columns)
    template = "(" + ", ".join(f"%({c})s" for c in columns) + ")"
    sql = (
        f"INSERT INTO job_deliveries ({col_str}) VALUES %s "
        f"ON CONFLICT (job_id, delivery_type, recipient_key) DO NOTHING "
        f"RETURNING id"
    )

    with db._get_conn() as conn:
        with conn.cursor() as cur:
            result = psycopg2.extras.execute_values(
                cur, sql, rows,
                template=template,
                page_size=100,
                fetch=True,
            )
            return len(result) if result else 0


def enqueue_job_deliveries(
    jobs_with_ids: list[tuple[Job, int]],
    is_seed: bool = False,
) -> dict:
    """
    Create durable delivery records for a batch of newly inserted jobs.

    Returns counts of group_topic and subscriber_dm rows created.
    """
    group_rows = build_group_topic_deliveries(jobs_with_ids, is_seed=is_seed)
    dm_rows = build_subscriber_dm_deliveries(jobs_with_ids, is_seed=is_seed)

    group_inserted = _insert_delivery_rows(group_rows)
    dm_inserted = _insert_delivery_rows(dm_rows)

    logger.info(
        f"Enqueued deliveries: {group_inserted} group-topic, {dm_inserted} subscriber-DM"
    )
    return {
        "group_topic_queued": group_inserted,
        "subscriber_dm_queued": dm_inserted,
    }


# =============================================================================
# Claiming and release
# =============================================================================

def claim_pending_deliveries(
    batch_size: int,
    worker_id: Optional[str] = None,
    delivery_type: Optional[str] = None,
) -> list[dict]:
    """
    Atomically claim up to batch_size due pending records.

    Uses FOR UPDATE SKIP LOCKED so concurrent workers cannot claim the same row.
    Increments attempts on claim. Records that have already exhausted their
    retries are moved to dead_letter immediately instead of being claimed.
    """
    worker_id = worker_id or _worker_id()

    sql = """
        WITH claim AS (
            SELECT id
            FROM job_deliveries
            WHERE status = %s
              AND next_attempt_at <= now()
              AND attempts < %s
              AND (%s IS NULL OR delivery_type = %s)
            ORDER BY next_attempt_at ASC, id ASC
            FOR UPDATE SKIP LOCKED
            LIMIT %s
        )
        UPDATE job_deliveries jd
        SET
            status = %s,
            processing_started_at = now(),
            worker_id = %s,
            attempts = attempts + 1,
            updated_at = now()
        FROM claim
        WHERE jd.id = claim.id
        RETURNING jd.*
    """
    from core.config import DELIVERY_MAX_ATTEMPTS

    params = (
        STATUS_PENDING,
        DELIVERY_MAX_ATTEMPTS,
        delivery_type,
        delivery_type,
        batch_size,
        STATUS_PROCESSING,
        worker_id,
    )

    with db._get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [dict(r) for r in rows]


def mark_delivery_sent(delivery_id: int, message_id: Optional[int] = None) -> None:
    """Persist a successful delivery."""
    db._execute(
        """
        UPDATE job_deliveries
        SET status = %s,
            message_id = %s,
            sent_at = now(),
            processing_started_at = NULL,
            worker_id = NULL,
            last_error = NULL,
            updated_at = now()
        WHERE id = %s
        """,
        (STATUS_SENT, message_id, delivery_id),
    )


def mark_delivery_skipped(delivery_id: int, reason: str) -> None:
    """Mark a delivery as intentionally skipped (e.g. missing topic config)."""
    db._execute(
        """
        UPDATE job_deliveries
        SET status = %s,
            dead_letter_reason = %s,
            processing_started_at = NULL,
            worker_id = NULL,
            updated_at = now()
        WHERE id = %s
        """,
        (STATUS_SKIPPED, reason, delivery_id),
    )


def _next_attempt_at(attempts: int, retry_base_seconds: int) -> datetime:
    """Exponential backoff: base * 2^(attempts-1), capped at 24h."""

    if attempts < 1:
        return datetime.now(timezone.utc)

    delay = retry_base_seconds * (2 ** (attempts - 1))
    delay = min(delay, 86400)
    return datetime.now(timezone.utc) + timedelta(seconds=delay)


def release_delivery_to_pending(delivery_id: int) -> None:
    """
    Release a claimed record back to pending without penalising its attempt count.

    Used when a record cannot be processed right now for transient scheduling
    reasons (e.g. per-user DM rate limit reached this cycle) but should be
    retried on the next cycle.
    """
    db._execute(
        """
        UPDATE job_deliveries
        SET status = %s,
            next_attempt_at = now(),
            processing_started_at = NULL,
            worker_id = NULL,
            attempts = GREATEST(attempts - 1, 0),
            updated_at = now()
        WHERE id = %s
        """,
        (STATUS_PENDING, delivery_id),
    )


def update_job_aggregate_message_id(job_id: int, topic_key: str, message_id: int) -> None:
    """Append a topic message ID to jobs.telegram_message_ids (convenience aggregate)."""
    db._execute(
        """
        UPDATE jobs
        SET telegram_message_ids = COALESCE(telegram_message_ids, '{}'::jsonb) || %s::jsonb
        WHERE id = %s
        """,
        (json.dumps({topic_key: message_id}), job_id),
    )


def mark_delivery_failed(
    delivery_id: int,
    error: str,
    retryable: bool,
    max_attempts: Optional[int] = None,
    retry_base_seconds: Optional[int] = None,
) -> None:
    """
    Record a failed delivery attempt.

    If the error is retryable and attempts remain, return the record to pending
    with a backoff-delayed next_attempt_at. Otherwise move it to dead_letter.
    """
    from core.config import DELIVERY_MAX_ATTEMPTS, DELIVERY_RETRY_BASE_SECONDS

    max_attempts = max_attempts if max_attempts is not None else DELIVERY_MAX_ATTEMPTS
    retry_base_seconds = retry_base_seconds if retry_base_seconds is not None else DELIVERY_RETRY_BASE_SECONDS

    row = db._fetchone(
        "SELECT attempts FROM job_deliveries WHERE id = %s",
        (delivery_id,),
    )
    if row is None:
        logger.warning(f"mark_delivery_failed called for unknown delivery_id={delivery_id}")
        return

    attempts = row["attempts"]

    if retryable and attempts < max_attempts:
        next_at = _next_attempt_at(attempts, retry_base_seconds)
        db._execute(
            """
            UPDATE job_deliveries
            SET status = %s,
                next_attempt_at = %s,
                last_error = %s,
                processing_started_at = NULL,
                worker_id = NULL,
                updated_at = now()
            WHERE id = %s
            """,
            (STATUS_PENDING, next_at, _trim_error(error), delivery_id),
        )
    else:
        reason = "retry_exhausted" if retryable and attempts >= max_attempts else "permanent_failure"
        db._execute(
            """
            UPDATE job_deliveries
            SET status = %s,
                dead_letter_reason = %s,
                last_error = %s,
                failed_at = now(),
                processing_started_at = NULL,
                worker_id = NULL,
                updated_at = now()
            WHERE id = %s
            """,
            (STATUS_DEAD_LETTER, reason, _trim_error(error), delivery_id),
        )


def _trim_error(error: str, max_len: int = 1000) -> str:
    """Truncate an error string so it fits comfortably in last_error."""
    return (error or "")[:max_len]


# =============================================================================
# Stale-worker recovery
# =============================================================================

def recover_stale_deliveries(
    lease_seconds: Optional[int] = None,
    max_attempts: Optional[int] = None,
) -> dict:
    """
    Find records stuck in processing longer than the lease and either return
    them to pending (if retries remain) or move them to dead_letter.

    Returns a dict with counts.
    """
    from core.config import DELIVERY_PROCESSING_LEASE_SECONDS, DELIVERY_MAX_ATTEMPTS

    lease_seconds = lease_seconds if lease_seconds is not None else DELIVERY_PROCESSING_LEASE_SECONDS
    max_attempts = max_attempts if max_attempts is not None else DELIVERY_MAX_ATTEMPTS

    stale = db._fetchall(
        """
        SELECT id, attempts
        FROM job_deliveries
        WHERE status = %s
          AND processing_started_at < now() - make_interval(secs := %s)
        FOR UPDATE SKIP LOCKED
        """,
        (STATUS_PROCESSING, lease_seconds),
    )

    recovered = 0
    dead_lettered = 0

    for row in stale:
        delivery_id = row["id"]
        attempts = row["attempts"]
        if attempts < max_attempts:
            db._execute(
                """
                UPDATE job_deliveries
                SET status = %s,
                    next_attempt_at = now(),
                    processing_started_at = NULL,
                    worker_id = NULL,
                    last_error = %s,
                    updated_at = now()
                WHERE id = %s
                """,
                (STATUS_PENDING, f"stale processing lease expired after {lease_seconds}s", delivery_id),
            )
            recovered += 1
        else:
            db._execute(
                """
                UPDATE job_deliveries
                SET status = %s,
                    dead_letter_reason = %s,
                    last_error = %s,
                    failed_at = now(),
                    processing_started_at = NULL,
                    worker_id = NULL,
                    updated_at = now()
                WHERE id = %s
                """,
                (
                    STATUS_DEAD_LETTER,
                    "retry_exhausted_after_stale_recovery",
                    f"stale processing lease expired after {lease_seconds}s",
                    delivery_id,
                ),
            )
            dead_lettered += 1

    if recovered or dead_lettered:
        logger.info(
            f"Stale delivery recovery: {recovered} returned to pending, "
            f"{dead_lettered} moved to dead_letter"
        )
    return {"recovered": recovered, "dead_lettered": dead_lettered}


# =============================================================================
# Dead-letter replay
# =============================================================================

def replay_dead_letter(delivery_id: int) -> bool:
    """
    Move a dead-letter record back to pending for manual retry.
    Preserves last_error and failed_at history; clears dead_letter_reason.
    """
    row = db._execute(
        """
        UPDATE job_deliveries
        SET status = %s,
            next_attempt_at = now(),
            dead_letter_reason = NULL,
            processing_started_at = NULL,
            worker_id = NULL,
            updated_at = now()
        WHERE id = %s AND status = %s
        RETURNING id
        """,
        (STATUS_PENDING, delivery_id, STATUS_DEAD_LETTER),
    )
    return row is not None


# =============================================================================
# Statistics
# =============================================================================

def get_delivery_stats() -> dict:
    """Return aggregate queue statistics."""
    status_rows = db._fetchall(
        """
        SELECT status, delivery_type, COUNT(*) as count
        FROM job_deliveries
        GROUP BY status, delivery_type
        """
    )

    stats = {
        "pending": 0,
        "processing": 0,
        "sent": 0,
        "dead_letter": 0,
        "skipped": 0,
        "group_topic": {"pending": 0, "processing": 0, "sent": 0, "dead_letter": 0, "skipped": 0},
        "subscriber_dm": {"pending": 0, "processing": 0, "sent": 0, "dead_letter": 0, "skipped": 0},
    }

    for row in status_rows:
        status = row["status"]
        d_type = row["delivery_type"]
        count = row["count"]
        stats[status] = stats.get(status, 0) + count
        if d_type in stats:
            stats[d_type][status] = stats[d_type].get(status, 0) + count

    return stats


def get_pending_dm_count_for_user(telegram_id: str | int, window_seconds: int) -> int:
    """Count how many subscriber-DM deliveries are already sent to this user within the window."""
    row = db._fetchone(
        """
        SELECT COUNT(*) as count
        FROM job_deliveries
        WHERE delivery_type = %s
          AND recipient_key = %s
          AND status = %s
          AND sent_at > now() - make_interval(secs := %s)
        """,
        (DELIVERY_TYPE_SUBSCRIBER_DM, str(telegram_id), STATUS_SENT, window_seconds),
    )
    return row["count"] if row else 0


# =============================================================================
# Backfill existing unsent jobs
# =============================================================================

def backfill_unsent_jobs() -> dict:
    """
    Backfill delivery records for jobs that were inserted before this migration.

    Only jobs with sent_at IS NULL are touched. Sent jobs are intentionally not
    requeued. Group-topic records are created by the migration itself; this
    function fills any gaps and creates subscriber-DM records.
    """
    from core.models import Job

    group_inserted = 0
    dm_inserted = 0

    # Backfill group-topic records (migration does most, but this is idempotent).
    rows = db._fetchall(
        """
        SELECT id, topics
        FROM jobs
        WHERE sent_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM job_deliveries jd
              WHERE jd.job_id = jobs.id AND jd.delivery_type = %s
          )
        """,
        (DELIVERY_TYPE_GROUP_TOPIC,),
    )
    jobs_with_ids = []
    for row in rows:
        job = Job(
            title="",
            company="",
            location="",
            url="",
            source="",
            topics=row["topics"] or [],
        )
        jobs_with_ids.append((job, row["id"]))

    if jobs_with_ids:
        group_rows = build_group_topic_deliveries(jobs_with_ids, is_seed=False)
        group_inserted = _insert_delivery_rows(group_rows)

    # Backfill subscriber-DM records for jobs that have none yet.
    dm_rows = []
    dm_candidate_rows = db._fetchall(
        """
        SELECT j.*
        FROM jobs j
        WHERE j.sent_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM job_deliveries jd
              WHERE jd.job_id = j.id AND jd.delivery_type = %s
          )
        """,
        (DELIVERY_TYPE_SUBSCRIBER_DM,),
    )

    if dm_candidate_rows:
        candidates = [(Job.from_db_row(row), row["id"]) for row in dm_candidate_rows]
        dm_rows = build_subscriber_dm_deliveries(candidates, is_seed=False)
        dm_inserted = _insert_delivery_rows(dm_rows)

    logger.info(
        f"Backfilled unsent jobs: {group_inserted} group-topic, {dm_inserted} subscriber-DM"
    )
    return {
        "group_topic_backfilled": group_inserted,
        "subscriber_dm_backfilled": dm_inserted,
    }
