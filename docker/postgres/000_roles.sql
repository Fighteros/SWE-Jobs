-- =============================================================================
-- Compatibility roles for the self-hosted Postgres container.
--
-- Historical migrations (001_init.sql etc.) reference predefined roles
-- (anon, authenticated, service_role) in GRANT/POLICY statements. Vanilla
-- Postgres has none of them, so those statements abort the migration unless
-- the roles exist first. After migration 008 strips all data privileges,
-- these roles remain as NOLOGIN placeholders with no access to business data.
--
-- The application connects as the superuser (POSTGRES_USER) and therefore
-- bypasses Row Level Security entirely. The numeric `000` prefix guarantees
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
