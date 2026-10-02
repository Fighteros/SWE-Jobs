"""
Integration test for migration 009_admin_security_schema.sql.

Skipped unless TEST_DATABASE_URL points at a disposable Postgres database.
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
    "009_admin_security_schema.sql",
]


@pytest.fixture
def fresh_db():
    conn = psycopg2.connect(TEST_DB_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
        cur.execute("DROP SCHEMA IF EXISTS security CASCADE;")
    roles_sql = (pathlib.Path(__file__).parent.parent / "docker" / "postgres" / "000_roles.sql").read_text()
    with conn.cursor() as cur:
        cur.execute(roles_sql)
    for name in MIGRATIONS_TO_APPLY:
        with conn.cursor() as cur:
            cur.execute((MIGRATIONS_DIR / name).read_text())
    yield conn
    conn.close()


def test_security_schema_exists(fresh_db):
    with fresh_db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = 'security'"
        )
        assert cur.fetchone()[0] == 1


def test_admin_accounts_table_exists(fresh_db):
    with fresh_db.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) FROM information_schema.tables
               WHERE table_schema = 'security' AND table_name = 'admin_accounts'"""
        )
        assert cur.fetchone()[0] == 1


def test_all_security_tables_exist(fresh_db):
    expected = [
        "admin_accounts", "admin_roles", "admin_permissions",
        "admin_role_permissions", "admin_account_roles",
        "admin_refresh_sessions", "admin_totp_credentials",
        "admin_recovery_codes", "admin_action_tokens",
        "admin_audit_events", "admin_idempotency_records",
    ]
    with fresh_db.cursor() as cur:
        cur.execute(
            """SELECT table_name FROM information_schema.tables
               WHERE table_schema = 'security'"""
        )
        tables = {row[0] for row in cur.fetchall()}
    for t in expected:
        assert t in tables, f"Missing table: security.{t}"


def test_admin_accounts_uuid_pk(fresh_db):
    with fresh_db.cursor() as cur:
        cur.execute(
            """SELECT data_type FROM information_schema.columns
               WHERE table_schema = 'security' AND table_name = 'admin_accounts'
               AND column_name = 'id'"""
        )
        assert cur.fetchone()[0] == "uuid"


def test_super_admin_role_seeded(fresh_db):
    with fresh_db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM security.admin_roles WHERE name = 'super_admin'"
        )
        assert cur.fetchone()[0] == 1


def test_super_admin_has_all_permissions(fresh_db):
    with fresh_db.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) FROM security.admin_role_permissions rp
               JOIN security.admin_roles r ON rp.role_id = r.id
               WHERE r.name = 'super_admin'"""
        )
        count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM security.admin_permissions")
        total = cur.fetchone()[0]
        assert count == total, f"super_admin has {count}/{total} permissions"


def test_read_only_role_seeded(fresh_db):
    with fresh_db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM security.admin_roles WHERE name = 'read_only'"
        )
        assert cur.fetchone()[0] == 1


def test_read_only_has_only_read_permissions(fresh_db):
    with fresh_db.cursor() as cur:
        cur.execute(
            """SELECT p.key FROM security.admin_role_permissions rp
               JOIN security.admin_roles r ON rp.role_id = r.id
               JOIN security.admin_permissions p ON rp.permission_id = p.id
               WHERE r.name = 'read_only'"""
        )
        keys = [row[0] for row in cur.fetchall()]
        assert all(k.endswith(".read") for k in keys), f"Non-read permission in read_only: {keys}"


def test_admin_accounts_status_check(fresh_db):
    with fresh_db.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) FROM information_schema.check_constraints
               WHERE constraint_schema = 'security'
               AND check_clause LIKE '%invited%'"""
        )
        assert cur.fetchone()[0] >= 1


def test_all_permission_keys_seeded(fresh_db):
    expected_keys = [
        "dashboard.read", "jobs.read", "jobs.manage", "jobs.archive", "jobs.delete",
        "telegram-users.read", "telegram-users.manage",
        "runs.read", "runs.trigger", "runs.cancel",
        "sources.read", "sources.manage", "sources.probe",
        "deliveries.read", "deliveries.replay", "deliveries.cancel",
        "support.read", "support.reply", "support.manage",
        "broadcasts.read", "broadcasts.create", "broadcasts.dispatch",
        "settings.read", "settings.manage",
        "admins.read", "admins.manage",
        "roles.manage",
        "audit.read", "audit.export",
        "system.destructive",
    ]
    with fresh_db.cursor() as cur:
        cur.execute("SELECT key FROM security.admin_permissions")
        keys = {row[0] for row in cur.fetchall()}
    for k in expected_keys:
        assert k in keys, f"Missing permission: {k}"


def test_rls_enabled_on_all_security_tables(fresh_db):
    tables = [
        "admin_accounts", "admin_roles", "admin_permissions",
        "admin_role_permissions", "admin_account_roles",
        "admin_refresh_sessions", "admin_totp_credentials",
        "admin_recovery_codes", "admin_action_tokens",
        "admin_audit_events", "admin_idempotency_records",
    ]
    with fresh_db.cursor() as cur:
        for t in tables:
            cur.execute(
                "SELECT relrowsecurity FROM pg_class WHERE relname = %s AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'security')",
                (t,),
            )
            assert cur.fetchone()[0] is True, f"RLS not enabled on security.{t}"
