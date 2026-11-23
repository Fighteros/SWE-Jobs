-- =============================================================================
-- Migration 009: circuit-breaker alert state on source_health
--
-- Records when the admin was last alerted about an open circuit breaker, so
-- monitoring alerts once when a circuit opens, at most once per cooldown
-- while it stays broken, and once when it recovers — instead of after every
-- ingestion run.
--
-- This migration is idempotent and safe to apply to any database:
--   docker compose exec -T db psql -U postgres -d postgres -f - < postgres/migrations/009_source_health_circuit_alerts.sql
--
-- The application also ensures this column lazily at runtime
-- (core.db.ensure_circuit_alert_schema), so existing databases are covered
-- even without applying this file manually.
-- =============================================================================

ALTER TABLE source_health ADD COLUMN IF NOT EXISTS circuit_open_alerted_at TIMESTAMPTZ;
