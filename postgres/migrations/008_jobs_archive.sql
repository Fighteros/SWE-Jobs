-- =============================================================================
-- Migration 008: jobs_archive for existing databases
--
-- The jobs_archive table was added to 001_init.sql in commit 3e59ff3, but the
-- Postgres image only applies postgres/migrations/ when it initializes an
-- EMPTY data volume. Databases created before that commit therefore never got
-- the table, and the weekly archive job fails with
-- `relation "jobs_archive" does not exist`.
--
-- This migration is idempotent (IF NOT EXISTS everywhere) and safe to apply
-- to any database. The archive workflow applies it automatically before each
-- run; it is included here for manual/initial application as well.
--
-- The column list intentionally ends with posted_at, apply_method,
-- ats_provider, apply_email — the same trailing columns and order the
-- production `jobs` table has after migrations 003 and 006 — so that
-- `INSERT INTO jobs_archive SELECT * FROM jobs ...` stays valid. Prefer an
-- explicit column list in new SQL regardless.
-- =============================================================================

CREATE TABLE IF NOT EXISTS jobs_archive (
    id                   SERIAL PRIMARY KEY,
    unique_id            TEXT UNIQUE NOT NULL,
    title                TEXT NOT NULL,
    company              TEXT DEFAULT '',
    location             TEXT DEFAULT '',
    url                  TEXT NOT NULL,
    source               TEXT NOT NULL,
    original_source      TEXT DEFAULT '',
    salary_raw           TEXT DEFAULT '',
    salary_min           INTEGER,
    salary_max           INTEGER,
    salary_currency      TEXT DEFAULT '',
    job_type             TEXT DEFAULT '',
    seniority            TEXT DEFAULT 'mid',
    is_remote            BOOLEAN DEFAULT FALSE,
    country              TEXT DEFAULT '',
    tags                 TEXT[] DEFAULT '{}',
    topics               TEXT[] DEFAULT '{}',
    created_at           TIMESTAMPTZ DEFAULT now(),
    updated_at           TIMESTAMPTZ DEFAULT now(),
    sent_at              TIMESTAMPTZ,
    telegram_message_ids JSONB DEFAULT '{}'
);

-- Columns added to jobs by later migrations; keep jobs_archive in lockstep.
ALTER TABLE jobs_archive ADD COLUMN IF NOT EXISTS posted_at TIMESTAMPTZ;
ALTER TABLE jobs_archive ADD COLUMN IF NOT EXISTS apply_method TEXT;
ALTER TABLE jobs_archive ADD COLUMN IF NOT EXISTS ats_provider TEXT;
ALTER TABLE jobs_archive ADD COLUMN IF NOT EXISTS apply_email  TEXT;

-- Only B-tree indexes on jobs_archive (no GIN / trgm)
CREATE INDEX IF NOT EXISTS jobs_archive_created_at_idx ON jobs_archive (created_at);
CREATE INDEX IF NOT EXISTS jobs_archive_unique_id_idx  ON jobs_archive (unique_id);

ALTER TABLE jobs_archive ENABLE ROW LEVEL SECURITY;
