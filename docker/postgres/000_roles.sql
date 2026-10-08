-- =============================================================================
-- Compatibility roles used by database policies and grants.
--
-- The schema migrations reference anon, authenticated, and service_role. Vanilla
-- PostgreSQL does not create these roles, so initialize them before migrations.
--
-- The application connects as the database owner and therefore
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
