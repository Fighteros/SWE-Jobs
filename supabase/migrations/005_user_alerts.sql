-- =============================================================================
-- Migration 005: user_alerts — multiple alerts per user
-- Replaces users.subscriptions (single JSONB) with a list of alert rows.
-- This migration creates the new table and copies existing data.
-- The users.subscriptions column is dropped in a follow-up migration (006)
-- after one safe deploy cycle.
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_alerts (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL,
    topics        TEXT[]  NOT NULL DEFAULT '{}',
    seniority     TEXT[]  NOT NULL DEFAULT '{}',
    locations     TEXT[]  NOT NULL DEFAULT '{}',
    sources       TEXT[]  NOT NULL DEFAULT '{}',
    keywords      TEXT[]  NOT NULL DEFAULT '{}',
    min_salary    INTEGER,
    dm_enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, position)
);

CREATE INDEX IF NOT EXISTS idx_user_alerts_user_id ON user_alerts (user_id);

-- Auto-update updated_at on UPDATE (uses helper from migration 001)
CREATE TRIGGER user_alerts_updated_at
    BEFORE UPDATE ON user_alerts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

ALTER TABLE user_alerts ENABLE ROW LEVEL SECURITY;

-- Data migration: copy each user's existing subscriptions JSONB into a row.
-- Per-alert dm_enabled defaults to TRUE; users.notify_dm remains the global
-- kill switch and is independent.
-- Idempotency guard: skip users who already have a position=1 alert.
-- Safe-cast guard: ignore non-numeric min_salary strings rather than aborting.
INSERT INTO user_alerts (user_id, position, topics, seniority, locations, sources, keywords, min_salary, dm_enabled)
SELECT
    u.id,
    1,
    COALESCE(ARRAY(SELECT jsonb_array_elements_text(u.subscriptions->'topics')),    '{}'),
    COALESCE(ARRAY(SELECT jsonb_array_elements_text(u.subscriptions->'seniority')), '{}'),
    COALESCE(ARRAY(SELECT jsonb_array_elements_text(u.subscriptions->'locations')), '{}'),
    COALESCE(ARRAY(SELECT jsonb_array_elements_text(u.subscriptions->'sources')),   '{}'),
    COALESCE(ARRAY(SELECT jsonb_array_elements_text(u.subscriptions->'keywords')),  '{}'),
    NULLIF(
        CASE WHEN (u.subscriptions->>'min_salary') ~ '^\d+$'
             THEN (u.subscriptions->>'min_salary')::int
             ELSE NULL
        END,
        0
    ),
    TRUE
FROM users u
WHERE u.subscriptions IS NOT NULL
  AND u.subscriptions <> '{}'::jsonb
  AND NOT EXISTS (
      SELECT 1 FROM user_alerts ua
      WHERE ua.user_id = u.id AND ua.position = 1
  );
