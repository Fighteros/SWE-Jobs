"""
Integration tests for core/delivery_queue.py against a real Postgres database.

Run with:
    TEST_DATABASE_URL=postgres://postgres@localhost:5432/delivery_test \
        pytest tests/test_delivery_queue_integration.py -v
"""

import os
import pathlib
import threading
import time
from urllib.parse import urlparse

import pytest

pytest.importorskip("psycopg2")
import psycopg2
from psycopg2.extras import RealDictCursor

from core import db
from core import config as core_config
from core.delivery_queue import (
    DELIVERY_TYPE_GROUP_TOPIC,
    DELIVERY_TYPE_SUBSCRIBER_DM,
    STATUS_PENDING,
    STATUS_PROCESSING,
    STATUS_SENT,
    STATUS_DEAD_LETTER,
    STATUS_SKIPPED,
    enqueue_job_deliveries,
    claim_pending_deliveries,
    mark_delivery_sent,
    mark_delivery_failed,
    recover_stale_deliveries,
    replay_dead_letter,
    get_delivery_stats,
    backfill_unsent_jobs,
)
from core.models import Job


TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")

MIGRATIONS_DIR = pathlib.Path(__file__).parent.parent / "supabase" / "migrations"
MIGRATIONS = [
    "001_init.sql",
    "002_applications_and_blacklist.sql",
    "003_add_posted_at.sql",
    "004_support_messages.sql",
    "005_user_alerts.sql",
    "006_job_apply_fields.sql",
    "007_job_deliveries.sql",
]


def _parse_db_url(url: str):
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "dbname": parsed.path.lstrip("/") or "postgres",
        "user": parsed.username or "postgres",
        "password": parsed.password or "",
    }


@pytest.fixture(scope="function")
def fresh_db():
    """Drop public schema, apply all migrations, and patch core.db to use the test DB."""
    conn = psycopg2.connect(TEST_DB_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
    for name in MIGRATIONS:
        with conn.cursor() as cur:
            cur.execute((MIGRATIONS_DIR / name).read_text())

    # Patch core.db to use the test database and reset its pool.
    cfg = _parse_db_url(TEST_DB_URL)
    original = {
        "SUPABASE_DB_HOST": db.SUPABASE_DB_HOST,
        "SUPABASE_DB_PORT": db.SUPABASE_DB_PORT,
        "SUPABASE_DB_NAME": db.SUPABASE_DB_NAME,
        "SUPABASE_DB_USER": db.SUPABASE_DB_USER,
        "SUPABASE_DB_PASSWORD": db.SUPABASE_DB_PASSWORD,
        "SUPABASE_DB_SSLMODE": db.SUPABASE_DB_SSLMODE,
    }
    db.SUPABASE_DB_HOST = cfg["host"]
    db.SUPABASE_DB_PORT = cfg["port"]
    db.SUPABASE_DB_NAME = cfg["dbname"]
    db.SUPABASE_DB_USER = cfg["user"]
    db.SUPABASE_DB_PASSWORD = cfg["password"]
    db.SUPABASE_DB_SSLMODE = "disable"
    db.close_pool()
    db._pool = None

    yield conn

    # Restore original config.
    for key, value in original.items():
        setattr(db, key, value)
    db.close_pool()
    db._pool = None
    conn.close()


def _insert_job(conn, unique_id="https://example.com/1", topics=None, sent_at=None):
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO jobs (unique_id, title, company, location, url, source, topics, sent_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (unique_id, "Dev", "Co", "Remote", unique_id, "remotive", topics or ["backend"], sent_at),
        )
        return cur.fetchone()[0]


def _insert_user(conn, telegram_id=42, notify_dm=True):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (telegram_id, username, notify_dm) VALUES (%s, %s, %s) RETURNING id",
            (telegram_id, "test", notify_dm),
        )
        return cur.fetchone()[0]


def _insert_alert(conn, user_id, topics=None):
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO user_alerts
               (user_id, position, topics, seniority, locations, sources, keywords, min_salary, dm_enabled)
               VALUES (%s, 1, %s, '{}', '{}', '{}', '{}', NULL, TRUE)""",
            (user_id, topics or ["backend"]),
        )


def _count_by_status(conn, status=None):
    with conn.cursor() as cur:
        if status:
            cur.execute("SELECT COUNT(*) FROM job_deliveries WHERE status = %s", (status,))
        else:
            cur.execute("SELECT COUNT(*) FROM job_deliveries")
        return cur.fetchone()[0]


class TestEnqueueAndClaim:
    def test_enqueue_creates_group_topic_records(self, fresh_db):
        conn = fresh_db
        job_id = _insert_job(conn)
        job = Job(title="Dev", company="Co", location="Remote", url="https://example.com/1", source="remotive", topics=["backend"])

        stats = enqueue_job_deliveries([(job, job_id)])

        assert stats["group_topic_queued"] == 1
        assert stats["subscriber_dm_queued"] == 0
        assert _count_by_status(conn, STATUS_PENDING) == 1

    def test_enqueue_creates_subscriber_dm_records(self, fresh_db):
        conn = fresh_db
        job_id = _insert_job(conn)
        user_id = _insert_user(conn)
        _insert_alert(conn, user_id, topics=["backend"])
        job = Job(title="Dev", company="Co", location="Remote", url="https://example.com/1", source="remotive", topics=["backend"])

        stats = enqueue_job_deliveries([(job, job_id)])

        assert stats["group_topic_queued"] == 1
        assert stats["subscriber_dm_queued"] == 1

    def test_unique_records_prevent_duplicates(self, fresh_db):
        conn = fresh_db
        job_id = _insert_job(conn)
        job = Job(title="Dev", company="Co", location="Remote", url="https://example.com/1", source="remotive", topics=["backend"])

        enqueue_job_deliveries([(job, job_id)])
        stats = enqueue_job_deliveries([(job, job_id)])

        assert stats["group_topic_queued"] == 0
        assert _count_by_status(conn) == 1

    def test_claim_returns_pending_records(self, fresh_db):
        conn = fresh_db
        job_id = _insert_job(conn)
        job = Job(title="Dev", company="Co", location="Remote", url="https://example.com/1", source="remotive", topics=["backend"])
        enqueue_job_deliveries([(job, job_id)])

        claimed = claim_pending_deliveries(10, worker_id="w1")

        assert len(claimed) == 1
        assert claimed[0]["status"] == STATUS_PROCESSING
        assert claimed[0]["worker_id"] == "w1"
        assert claimed[0]["attempts"] == 1

    def test_second_claim_returns_empty(self, fresh_db):
        conn = fresh_db
        job_id = _insert_job(conn)
        job = Job(title="Dev", company="Co", location="Remote", url="https://example.com/1", source="remotive", topics=["backend"])
        enqueue_job_deliveries([(job, job_id)])

        first = claim_pending_deliveries(10, worker_id="w1")
        second = claim_pending_deliveries(10, worker_id="w2")

        assert len(first) == 1
        assert len(second) == 0

    def test_for_update_skip_locked_allows_concurrent_claimers(self, fresh_db):
        """Two transactions claiming at the same time must not grab the same row."""
        conn = fresh_db
        job_id = _insert_job(conn)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO job_deliveries (job_id, delivery_type, recipient_key, status, next_attempt_at)
                   VALUES (%s, %s, %s, %s, now())""",
                (job_id, DELIVERY_TYPE_GROUP_TOPIC, "backend", STATUS_PENDING),
            )

        results = {"t1": [], "t2": []}
        barrier = threading.Barrier(2)

        def claimer(key):
            # Each thread uses its own connection so the row lock is real.
            t_conn = psycopg2.connect(TEST_DB_URL)
            t_conn.autocommit = False
            with t_conn.cursor(cursor_factory=RealDictCursor) as cur:
                barrier.wait()
                cur.execute(
                    """UPDATE job_deliveries
                       SET status = %s, processing_started_at = now(), worker_id = %s, attempts = attempts + 1
                       WHERE id IN (
                           SELECT id FROM job_deliveries
                           WHERE status = %s AND next_attempt_at <= now()
                           ORDER BY next_attempt_at, id
                           FOR UPDATE SKIP LOCKED
                           LIMIT 1
                       )
                       RETURNING *""",
                    (STATUS_PROCESSING, key, STATUS_PENDING),
                )
                rows = cur.fetchall()
                t_conn.commit()
                results[key] = [dict(r) for r in rows]
            t_conn.close()

        t1 = threading.Thread(target=claimer, args=("worker-1",))
        t2 = threading.Thread(target=claimer, args=("worker-2",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        total_claimed = len(results["t1"]) + len(results["t2"])
        assert total_claimed == 1, "exactly one worker should claim the single row"


class TestRetryAndDeadLetter:
    def test_retryable_failure_backoffs(self, fresh_db):
        conn = fresh_db
        job_id = _insert_job(conn)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO job_deliveries (job_id, delivery_type, recipient_key, status, next_attempt_at, attempts)
                   VALUES (%s, %s, %s, %s, now(), 0)""",
                (job_id, DELIVERY_TYPE_GROUP_TOPIC, "backend", STATUS_PENDING),
            )

        # Claim first to set attempts=1, then fail retryable.
        claim_pending_deliveries(10, worker_id="w1")
        rows = claim_pending_deliveries(10, worker_id="w1")
        delivery_id = rows[0]["id"]
        mark_delivery_failed(delivery_id, "network error", retryable=True, max_attempts=5, retry_base_seconds=30)

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM job_deliveries WHERE id = %s", (delivery_id,))
            row = dict(cur.fetchone())

        assert row["status"] == STATUS_PENDING
        assert row["attempts"] == 1
        assert row["next_attempt_at"] is not None

    def test_permanent_failure_dead_letters(self, fresh_db):
        conn = fresh_db
        job_id = _insert_job(conn)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO job_deliveries (job_id, delivery_type, recipient_key, status, next_attempt_at, attempts)
                   VALUES (%s, %s, %s, %s, now(), 1)""",
                (job_id, DELIVERY_TYPE_GROUP_TOPIC, "backend", STATUS_PENDING),
            )

        rows = claim_pending_deliveries(10, worker_id="w1")
        delivery_id = rows[0]["id"]
        mark_delivery_failed(delivery_id, "bot was blocked", retryable=False, max_attempts=5, retry_base_seconds=30)

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM job_deliveries WHERE id = %s", (delivery_id,))
            row = dict(cur.fetchone())

        assert row["status"] == STATUS_DEAD_LETTER
        assert row["dead_letter_reason"] == "permanent_failure"

    def test_exhausted_retries_dead_letters(self, fresh_db):
        conn = fresh_db
        job_id = _insert_job(conn)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO job_deliveries (job_id, delivery_type, recipient_key, status, next_attempt_at, attempts)
                   VALUES (%s, %s, %s, %s, now(), 4)""",
                (job_id, DELIVERY_TYPE_GROUP_TOPIC, "backend", STATUS_PENDING),
            )

        rows = claim_pending_deliveries(10, worker_id="w1")
        delivery_id = rows[0]["id"]
        mark_delivery_failed(delivery_id, "network error", retryable=True, max_attempts=5, retry_base_seconds=30)

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM job_deliveries WHERE id = %s", (delivery_id,))
            row = dict(cur.fetchone())

        assert row["status"] == STATUS_DEAD_LETTER
        assert row["dead_letter_reason"] == "retry_exhausted"

    def test_replay_dead_letter(self, fresh_db):
        conn = fresh_db
        job_id = _insert_job(conn)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO job_deliveries (job_id, delivery_type, recipient_key, status, dead_letter_reason)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (job_id, DELIVERY_TYPE_GROUP_TOPIC, "backend", STATUS_DEAD_LETTER, "test"),
            )
            delivery_id = cur.fetchone()[0]

        ok = replay_dead_letter(delivery_id)
        assert ok is True

        with conn.cursor() as cur:
            cur.execute("SELECT status FROM job_deliveries WHERE id = %s", (delivery_id,))
            assert cur.fetchone()[0] == STATUS_PENDING


class TestStaleRecovery:
    def test_stale_processing_returns_to_pending(self, fresh_db):
        conn = fresh_db
        job_id = _insert_job(conn)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO job_deliveries
                   (job_id, delivery_type, recipient_key, status, processing_started_at, attempts)
                   VALUES (%s, %s, %s, %s, now() - INTERVAL '20 minutes', 1)""",
                (job_id, DELIVERY_TYPE_GROUP_TOPIC, "backend", STATUS_PROCESSING),
            )

        stats = recover_stale_deliveries(lease_seconds=600, max_attempts=5)

        assert stats["recovered"] == 1
        assert _count_by_status(conn, STATUS_PENDING) == 1

    def test_stale_processing_dead_letters_when_exhausted(self, fresh_db):
        conn = fresh_db
        job_id = _insert_job(conn)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO job_deliveries
                   (job_id, delivery_type, recipient_key, status, processing_started_at, attempts)
                   VALUES (%s, %s, %s, %s, now() - INTERVAL '20 minutes', 5)""",
                (job_id, DELIVERY_TYPE_GROUP_TOPIC, "backend", STATUS_PROCESSING),
            )

        stats = recover_stale_deliveries(lease_seconds=600, max_attempts=5)

        assert stats["dead_lettered"] == 1
        assert _count_by_status(conn, STATUS_DEAD_LETTER) == 1


class TestBackfill:
    def test_backfill_unsent_jobs(self, fresh_db):
        conn = fresh_db
        job_id = _insert_job(conn, unique_id="https://example.com/unsent", sent_at=None)

        stats = backfill_unsent_jobs()

        assert stats["group_topic_backfilled"] >= 1
        assert _count_by_status(conn) >= 1

    def test_backfill_does_not_touch_sent_jobs(self, fresh_db):
        conn = fresh_db
        _insert_job(conn, unique_id="https://example.com/sent", sent_at="2020-01-01")

        stats = backfill_unsent_jobs()

        assert stats["group_topic_backfilled"] == 0
        assert stats["subscriber_dm_backfilled"] == 0


class TestStats:
    def test_get_delivery_stats(self, fresh_db):
        conn = fresh_db
        job_id = _insert_job(conn)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO job_deliveries (job_id, delivery_type, recipient_key, status)
                   VALUES (%s, %s, %s, %s)""",
                (job_id, DELIVERY_TYPE_GROUP_TOPIC, "backend", STATUS_PENDING),
            )
            cur.execute(
                """INSERT INTO job_deliveries (job_id, delivery_type, recipient_key, status)
                   VALUES (%s, %s, %s, %s)""",
                (job_id, DELIVERY_TYPE_SUBSCRIBER_DM, "42", STATUS_SENT),
            )

        stats = get_delivery_stats()

        assert stats["pending"] == 1
        assert stats["sent"] == 1
        assert stats["group_topic"]["pending"] == 1
        assert stats["subscriber_dm"]["sent"] == 1
