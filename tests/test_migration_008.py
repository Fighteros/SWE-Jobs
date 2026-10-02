"""
Integration test for migration 008_remove_anon_access.sql.

Skipped unless TEST_DATABASE_URL points at a disposable Postgres database.
Example:
    TEST_DATABASE_URL=postgres://postgres@localhost:5432/migrations_test \
        pytest tests/test_migration_008.py -v
"""

import os
import pathlib

import pytest

pytest.importorskip("psycopg2")
import psycopg2

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
    "008_remove_anon_access.sql",
]

BUSINESS_TABLES = [
    "jobs", "users", "user_saved_jobs", "bot_runs", "source_health",
    "job_feedback", "jobs_archive", "job_deliveries",
    "user_applications", "user_alerts", "support_messages",
]


@pytest.fixture
def fresh_db():
    """Drop and recreate the public schema, apply 000_roles.sql then 001..008."""
    conn = psycopg2.connect(TEST_DB_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
    # Create Supabase-compatible roles (same as docker/postgres/000_roles.sql)
    roles_sql = (pathlib.Path(__file__).parent.parent / "docker" / "postgres" / "000_roles.sql").read_text()
    with conn.cursor() as cur:
        cur.execute(roles_sql)
    for name in MIGRATIONS_TO_APPLY:
        with conn.cursor() as cur:
            cur.execute((MIGRATIONS_DIR / name).read_text())
    yield conn
    conn.close()


def test_jobs_anon_select_policy_dropped(fresh_db):
    conn = fresh_db
    with conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) FROM pg_policies
               WHERE tablename = 'jobs' AND policyname = 'jobs_anon_select'"""
        )
        assert cur.fetchone()[0] == 0


def test_bot_runs_public_view_dropped(fresh_db):
    conn = fresh_db
    with conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) FROM information_schema.views
               WHERE table_schema = 'public' AND table_name = 'bot_runs_public'"""
        )
        assert cur.fetchone()[0] == 0


def test_no_anon_policies_on_business_tables(fresh_db):
    conn = fresh_db
    with conn.cursor() as cur:
        cur.execute(
            """SELECT tablename, policyname FROM pg_policies
               WHERE roles = '{anon}' AND schemaname = 'public'"""
        )
        rows = cur.fetchall()
        assert rows == [], f"anon policies remain: {rows}"


def test_no_anon_grants_on_business_tables(fresh_db):
    conn = fresh_db
    with conn.cursor() as cur:
        cur.execute(
            """SELECT table_name, privilege_type
               FROM information_schema.role_table_grants
               WHERE grantee = 'anon'
                 AND table_schema = 'public'
                 AND privilege_type IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE')"""
        )
        rows = cur.fetchall()
        assert rows == [], f"anon grants remain: {rows}"


def test_anon_role_still_exists_for_migration_compatibility(fresh_db):
    """The anon role must still exist (NOLOGIN, no data privileges) so
    historical migrations don't fail on re-apply."""
    conn = fresh_db
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM pg_roles WHERE rolname = 'anon'")
        assert cur.fetchone()[0] == 1
