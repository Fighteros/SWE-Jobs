-- =============================================================================
-- Migration 007: Durable job-delivery queue
--
-- Decouples job ingestion from Telegram delivery. Each (job, delivery_type,
-- recipient) tuple becomes a durable, independently trackable delivery record.
--
--   delivery_type: 'group_topic' | 'subscriber_dm'
--   status:        'pending' | 'processing' | 'sent' | 'dead_letter' | 'skipped'
--
-- The migration also backfills group_topic records for jobs that were inserted
-- but never sent because of the old 50-job-per-run cap. Subscriber-DM backfill
-- is performed by scripts/backfill_job_deliveries.py because alert matching is
-- easier to keep correct in Python.
-- =============================================================================

-- =============================================================================
-- TABLE: job_deliveries
-- =============================================================================
CREATE TABLE IF NOT EXISTS job_deliveries (
    id                      SERIAL PRIMARY KEY,
    job_id                  INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    delivery_type           TEXT NOT NULL CHECK (delivery_type IN ('group_topic', 'subscriber_dm')),
    recipient_key           TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'sent', 'dead_letter', 'skipped')),
    attempts                INTEGER NOT NULL DEFAULT 0,
    last_error              TEXT,
    next_attempt_at         TIMESTAMPTZ DEFAULT now(),
    processing_started_at   TIMESTAMPTZ,
    worker_id               TEXT,
    message_id              BIGINT,
    dead_letter_reason      TEXT,
    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now(),
    sent_at                 TIMESTAMPTZ,
    failed_at               TIMESTAMPTZ,
    UNIQUE (job_id, delivery_type, recipient_key)
);

-- =============================================================================
-- Indexes for queue operations and lookups
-- =============================================================================
CREATE INDEX IF NOT EXISTS idx_job_deliveries_pending_due
    ON job_deliveries (status, next_attempt_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_job_deliveries_status
    ON job_deliveries (status);

CREATE INDEX IF NOT EXISTS idx_job_deliveries_job_id
    ON job_deliveries (job_id);

CREATE INDEX IF NOT EXISTS idx_job_deliveries_recipient
    ON job_deliveries (recipient_key);

CREATE INDEX IF NOT EXISTS idx_job_deliveries_processing
    ON job_deliveries (status, processing_started_at)
    WHERE status = 'processing';

CREATE INDEX IF NOT EXISTS idx_job_deliveries_worker_id
    ON job_deliveries (worker_id)
    WHERE worker_id IS NOT NULL;

-- =============================================================================
-- Trigger: auto-update updated_at on UPDATE
-- =============================================================================
CREATE TRIGGER job_deliveries_updated_at
    BEFORE UPDATE ON job_deliveries
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- Row Level Security
-- =============================================================================
ALTER TABLE job_deliveries ENABLE ROW LEVEL SECURITY;

-- =============================================================================
-- Backfill: group_topic records for unsent jobs
-- =============================================================================
-- One pending delivery per topic for every job that was inserted but not sent.
INSERT INTO job_deliveries (
    job_id,
    delivery_type,
    recipient_key,
    status,
    next_attempt_at
)
SELECT
    id,
    'group_topic',
    topic,
    'pending',
    now()
FROM jobs,
     unnest(topics) AS topic
WHERE sent_at IS NULL
  AND topics IS NOT NULL
  AND array_length(topics, 1) > 0
ON CONFLICT (job_id, delivery_type, recipient_key) DO NOTHING;

-- Jobs with no topics cannot be sent to a group topic; mark them skipped.
INSERT INTO job_deliveries (
    job_id,
    delivery_type,
    recipient_key,
    status,
    dead_letter_reason
)
SELECT
    id,
    'group_topic',
    '',
    'skipped',
    'no topics assigned'
FROM jobs
WHERE sent_at IS NULL
  AND (topics IS NULL OR array_length(topics, 1) IS NULL OR array_length(topics, 1) = 0)
ON CONFLICT (job_id, delivery_type, recipient_key) DO NOTHING;
