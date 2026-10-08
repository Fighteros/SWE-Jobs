-- =============================================================================
-- Migration 003: Add posted_at column to jobs and jobs_archive
-- Stores the actual posting date from the source (vs created_at = DB insert time)
-- =============================================================================

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS posted_at TIMESTAMPTZ;
ALTER TABLE jobs_archive ADD COLUMN IF NOT EXISTS posted_at TIMESTAMPTZ;
