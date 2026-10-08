-- =============================================================================
-- SWE-Jobs v2: Initial Schema Migration
-- =============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- =============================================================================
-- HELPER FUNCTION: auto-update updated_at
-- =============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- TABLE: jobs
-- =============================================================================

CREATE TABLE IF NOT EXISTS jobs (
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

-- Trigger: auto-update updated_at on jobs UPDATE
CREATE TRIGGER jobs_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Indexes on jobs
CREATE INDEX IF NOT EXISTS jobs_title_trgm_idx      ON jobs USING GIN (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS jobs_tags_gin_idx         ON jobs USING GIN (tags);
CREATE INDEX IF NOT EXISTS jobs_topics_gin_idx       ON jobs USING GIN (topics);
CREATE INDEX IF NOT EXISTS jobs_created_at_idx       ON jobs (created_at);
CREATE INDEX IF NOT EXISTS jobs_source_idx           ON jobs (source);
CREATE INDEX IF NOT EXISTS jobs_seniority_idx        ON jobs (seniority);
CREATE INDEX IF NOT EXISTS jobs_salary_min_idx       ON jobs (salary_min);
CREATE INDEX IF NOT EXISTS jobs_company_lower_idx    ON jobs (lower(company));

-- =============================================================================
-- TABLE: users
-- =============================================================================

CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    telegram_id   BIGINT UNIQUE NOT NULL,
    username      TEXT,
    subscriptions JSONB DEFAULT '{}',
    notify_dm     BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- =============================================================================
-- TABLE: user_saved_jobs
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_saved_jobs (
    id       SERIAL PRIMARY KEY,
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id   INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    saved_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, job_id)
);

CREATE INDEX IF NOT EXISTS user_saved_jobs_user_id_idx ON user_saved_jobs (user_id);
CREATE INDEX IF NOT EXISTS user_saved_jobs_job_id_idx  ON user_saved_jobs (job_id);

-- =============================================================================
-- TABLE: bot_runs
-- =============================================================================

CREATE TABLE IF NOT EXISTS bot_runs (
    id             SERIAL PRIMARY KEY,
    started_at     TIMESTAMPTZ DEFAULT now(),
    finished_at    TIMESTAMPTZ,
    jobs_fetched   INTEGER DEFAULT 0,
    jobs_filtered  INTEGER DEFAULT 0,
    jobs_new       INTEGER DEFAULT 0,
    jobs_sent      INTEGER DEFAULT 0,
    source_stats   JSONB DEFAULT '{}',
    errors         JSONB DEFAULT '{}'
);

-- =============================================================================
-- TABLE: source_health
-- =============================================================================

CREATE TABLE IF NOT EXISTS source_health (
    source                TEXT PRIMARY KEY,
    consecutive_failures  INTEGER DEFAULT 0,
    circuit_open_until    TIMESTAMPTZ,
    last_success_at       TIMESTAMPTZ,
    last_failure_at       TIMESTAMPTZ,
    last_error            TEXT
);

-- =============================================================================
-- TABLE: job_feedback
-- =============================================================================

CREATE TABLE IF NOT EXISTS job_feedback (
    id            SERIAL PRIMARY KEY,
    job_id        INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    feedback_type TEXT NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS job_feedback_job_id_idx  ON job_feedback (job_id);
CREATE INDEX IF NOT EXISTS job_feedback_user_id_idx ON job_feedback (user_id);

-- =============================================================================
-- TABLE: jobs_archive
-- (same schema as jobs but with fewer indexes)
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

-- Only B-tree indexes on jobs_archive (no GIN / trgm)
CREATE INDEX IF NOT EXISTS jobs_archive_created_at_idx ON jobs_archive (created_at);
CREATE INDEX IF NOT EXISTS jobs_archive_unique_id_idx  ON jobs_archive (unique_id);

-- =============================================================================
-- ROW LEVEL SECURITY
-- =============================================================================

ALTER TABLE jobs            ENABLE ROW LEVEL SECURITY;
ALTER TABLE users           ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_saved_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE bot_runs        ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_health   ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_feedback    ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs_archive    ENABLE ROW LEVEL SECURITY;

-- Anon can only SELECT jobs
CREATE POLICY jobs_anon_select
    ON jobs
    FOR SELECT
    TO anon
    USING (true);

-- =============================================================================
-- VIEW: bot_runs_public (excludes the errors column)
-- =============================================================================

CREATE OR REPLACE VIEW bot_runs_public AS
SELECT
    id,
    started_at,
    finished_at,
    jobs_fetched,
    jobs_filtered,
    jobs_new,
    jobs_sent,
    source_stats
FROM bot_runs;

GRANT SELECT ON bot_runs_public TO anon;
