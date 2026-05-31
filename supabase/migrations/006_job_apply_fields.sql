-- =============================================================================
-- Migration 006: apply-method fields on jobs
--
-- These columns exist on the deployed (production) jobs table but were added by a
-- feature whose migration never landed in main. They are recreated here so the
-- container schema matches production and the full jobs data imports without loss.
-- main's pipeline does not write these columns yet (they stay NULL for new rows);
-- IF NOT EXISTS keeps this safe if that feature later merges with its own migration.
-- =============================================================================

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS apply_method TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS ats_provider TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS apply_email  TEXT;
