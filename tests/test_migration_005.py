"""
Integration test for migration 005_user_alerts.sql.

Skipped unless TEST_DATABASE_URL points at a disposable Postgres database.
Example:
    TEST_DATABASE_URL=postgres://postgres@localhost:5432/migrations_test \
        pytest tests/test_migration_005.py -v

The test creates a clean schema, applies migrations 001..005, seeds two
users (one with subscriptions, one with empty), and asserts the resulting
user_alerts rows.
"""
import os
import pathlib
import json

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
]


@pytest.fixture
def fresh_db():
    """Drop and recreate the public schema, then apply migrations 001..005."""
    conn = psycopg2.connect(TEST_DB_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
    yield conn
    conn.close()


def _apply_migrations_through_004(conn):
    """Apply 001..004 only — leaves users.subscriptions populated for the test."""
    with conn.cursor() as cur:
        for name in MIGRATIONS_TO_APPLY[:-1]:
            sql = (MIGRATIONS_DIR / name).read_text()
            cur.execute(sql)


def _apply_migration_005(conn):
    with conn.cursor() as cur:
        sql = (MIGRATIONS_DIR / "005_user_alerts.sql").read_text()
        cur.execute(sql)


def test_user_with_subscription_gets_one_alert(fresh_db):
    conn = fresh_db
    _apply_migrations_through_004(conn)

    sub = {
        "topics": ["backend", "devops"],
        "seniority": ["senior"],
        "locations": ["remote", "EG"],
        "sources": ["linkedin"],
        "keywords": ["python"],
        "min_salary": 80000,
    }
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (telegram_id, username, subscriptions) VALUES (%s, %s, %s) RETURNING id",
            (12345, "alice", json.dumps(sub)),
        )
        user_id = cur.fetchone()[0]

    _apply_migration_005(conn)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM user_alerts WHERE user_id = %s ORDER BY position", (user_id,))
        rows = cur.fetchall()

    assert len(rows) == 1
    row = rows[0]
    assert row["position"] == 1
    assert sorted(row["topics"]) == ["backend", "devops"]
    assert row["seniority"] == ["senior"]
    assert sorted(row["locations"]) == ["EG", "remote"]
    assert row["sources"] == ["linkedin"]
    assert row["keywords"] == ["python"]
    assert row["min_salary"] == 80000
    assert row["dm_enabled"] is True


def test_user_with_empty_subscriptions_produces_no_alert(fresh_db):
    conn = fresh_db
    _apply_migrations_through_004(conn)

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (telegram_id, username, subscriptions) VALUES (%s, %s, %s) RETURNING id",
            (54321, "bob", json.dumps({})),
        )
        user_id = cur.fetchone()[0]

    _apply_migration_005(conn)

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM user_alerts WHERE user_id = %s", (user_id,))
        count = cur.fetchone()[0]

    assert count == 0
