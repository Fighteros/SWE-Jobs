"""
Integration test for migration 007_job_deliveries.sql.

Skipped unless TEST_DATABASE_URL points at a disposable Postgres database.
Example:
    TEST_DATABASE_URL=postgres://postgres@localhost:5432/migrations_test \
        pytest tests/test_migration_007.py -v
"""

import os
import pathlib

import pytest

pytest.importorskip("psycopg2")
import psycopg2
from psycopg2.extras import RealDictCursor


TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DB_URL, reason="TEST_DATABASE_URL not set"
)

MIGRATIONS_DIR = pathlib.Path(__file__).parent.parent / "supabase" / "migrations"
MIGRATIONS_TO_APPLY = [
    "001_init.sql",
    "002_applications_and_blacklist.sql",
    "003_add_posted_at.sql",
    "004_support_messages.sql",
    "005_user_alerts.sql",
    "006_job_apply_fields.sql",
    "007_job_deliveries.sql",
]


@pytest.fixture
def fresh_db():
    """Drop and recreate the public schema, then apply migrations 001..007."""
    conn = psycopg2.connect(TEST_DB_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
    for name in MIGRATIONS_TO_APPLY:
        with conn.cursor() as cur:
            cur.execute((MIGRATIONS_DIR / name).read_text())
    yield conn
    conn.close()


def test_job_deliveries_table_and_indexes_exist(fresh_db):
    conn = fresh_db
    with conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = 'job_deliveries'"""
        )
        assert cur.fetchone()[0] == 1

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """SELECT indexname FROM pg_indexes
               WHERE schemaname = 'public' AND tablename = 'job_deliveries'"""
        )
        index_names = {row["indexname"] for row in cur.fetchall()}

    assert "idx_job_deliveries_pending_due" in index_names
    assert "idx_job_deliveries_status" in index_names
    assert "idx_job_deliveries_job_id" in index_names
    assert "idx_job_deliveries_recipient" in index_names
    assert "idx_job_deliveries_processing" in index_names


def test_backfills_group_topic_records_for_unsent_jobs(fresh_db):
    conn = fresh_db
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO jobs (unique_id, title, company, location, url, source, topics)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            ("https://example.com/1", "Dev", "Co", "Remote", "https://example.com/1", "remotive", ["backend", "frontend"]),
        )
        job_id = cur.fetchone()[0]

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM job_deliveries WHERE job_id = %s ORDER BY recipient_key",
            (job_id,),
        )
        rows = cur.fetchall()

    assert len(rows) == 2
    assert {row["recipient_key"] for row in rows} == {"backend", "frontend"}
    assert all(row["status"] == "pending" for row in rows)
    assert all(row["delivery_type"] == "group_topic" for row in rows)


def test_skips_unsent_jobs_with_no_topics(fresh_db):
    conn = fresh_db
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO jobs (unique_id, title, company, location, url, source, topics)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            ("https://example.com/2", "Dev", "Co", "Remote", "https://example.com/2", "remotive", []),
        )
        job_id = cur.fetchone()[0]

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM job_deliveries WHERE job_id = %s", (job_id,))
        rows = cur.fetchall()

    assert len(rows) == 1
    assert rows[0]["status"] == "skipped"
    assert rows[0]["dead_letter_reason"] == "no topics assigned"


def test_does_not_backfill_sent_jobs(fresh_db):
    conn = fresh_db
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO jobs (unique_id, title, company, location, url, source, topics, sent_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, now()) RETURNING id""",
            ("https://example.com/3", "Dev", "Co", "Remote", "https://example.com/3", "remotive", ["backend"]),
        )
        job_id = cur.fetchone()[0]

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM job_deliveries WHERE job_id = %s", (job_id,))
        assert cur.fetchone()[0] == 0


def test_unique_constraint_on_job_delivery_recipient(fresh_db):
    conn = fresh_db
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO jobs (unique_id, title, company, location, url, source, topics)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            ("https://example.com/4", "Dev", "Co", "Remote", "https://example.com/4", "remotive", ["backend"]),
        )
        job_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO job_deliveries (job_id, delivery_type, recipient_key)
               VALUES (%s, %s, %s)""",
            (job_id, "group_topic", "backend"),
        )
        with pytest.raises(Exception):
            cur.execute(
                """INSERT INTO job_deliveries (job_id, delivery_type, recipient_key)
                   VALUES (%s, %s, %s)""",
                (job_id, "group_topic", "backend"),
            )
