-- =============================================================================
-- Supabase-compatible roles for a self-hosted Postgres container.
--
-- Supabase ships predefined roles (anon, authenticated, service_role) that the
-- schema migrations reference (e.g. `CREATE POLICY ... TO anon` and
-- `GRANT ... TO anon` in 001_init.sql). Vanilla Postgres has none of them, so
-- those statements abort the migration unless the roles exist first.
--
-- The application connects as the superuser (POSTGRES_USER) and therefore
-- bypasses Row Level Security entirely; these roles only need to EXIST so the
-- GRANT/POLICY statements apply cleanly. The numeric `000` prefix guarantees
-- this file runs before 001_init.sql (initdb scripts run in lexical order).
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role NOLOGIN BYPASSRLS;
    END IF;
END
$$;
