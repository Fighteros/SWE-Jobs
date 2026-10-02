-- =============================================================================
-- Migration 008: Remove anonymous browser access to business data
--
-- The admin dashboard no longer connects to Supabase directly. All browser data
-- access goes through the FastAPI backend. This migration removes the anonymous
-- grants and policies that were needed for the old direct-Supabase dashboard.
--
-- This is a forward-only migration. It does NOT rewrite historical migrations.
-- =============================================================================

-- =============================================================================
-- 1. Drop the anon SELECT policy on jobs
-- =============================================================================
DROP POLICY IF EXISTS jobs_anon_select ON jobs;

-- =============================================================================
-- 2. Revoke any remaining anon grants on jobs
-- =============================================================================
REVOKE SELECT ON jobs FROM anon;

-- =============================================================================
-- 3. Revoke anon grants on the bot_runs_public view and drop the view
-- =============================================================================
REVOKE SELECT ON bot_runs_public FROM anon;
DROP VIEW IF EXISTS bot_runs_public;

-- =============================================================================
-- 4. Verify no anonymous business-data grants or policies remain
-- =============================================================================
-- Assert: no policies targeting the anon role on any business-data table.
DO $$
DECLARE
    orphan_policy RECORD;
BEGIN
    FOR orphan_policy IN
        SELECT schemaname, tablename, policyname
        FROM pg_policies
        WHERE roles = '{anon}'
          AND tablename IN (
              'jobs', 'users', 'user_saved_jobs', 'bot_runs', 'source_health',
              'job_feedback', 'jobs_archive', 'job_deliveries',
              'user_applications', 'user_alerts', 'support_messages'
          )
    LOOP
        RAISE EXCEPTION
            'Orphan anon policy remains: %.% policy "%"',
            orphan_policy.schemaname, orphan_policy.tablename,
            orphan_policy.policyname;
    END LOOP;
END
$$;

-- Assert: no table privileges granted to anon on business-data tables.
-- (We check information_schema.role_table_grants for SELECT/INSERT/UPDATE/DELETE.)
DO $$
DECLARE
    orphan_grant RECORD;
BEGIN
    FOR orphan_grant IN
        SELECT table_name, privilege_type
        FROM information_schema.role_table_grants
        WHERE grantee = 'anon'
          AND table_schema = 'public'
          AND privilege_type IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
          AND table_name IN (
              'jobs', 'users', 'user_saved_jobs', 'bot_runs', 'source_health',
              'job_feedback', 'jobs_archive', 'job_deliveries',
              'user_applications', 'user_alerts', 'support_messages'
          )
    LOOP
        RAISE EXCEPTION
            'Orphan anon grant remains: % -> %',
            orphan_grant.table_name, orphan_grant.privilege_type;
    END LOOP;
END
$$;
