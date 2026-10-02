# Admin Operations

> Status: **Milestone 1 — scaffolding only.** Operational runbooks for auth, RBAC,
> invite, TOTP recovery, and audit are placeholders until the relevant milestones
> ship. Each milestone that introduces an operable surface will fill its section
> here in the same change.

## Current State (Milestone 1)

No admin authentication, RBAC, or admin operations exist yet. The only operable
changes in this milestone are:

- Removing direct Supabase browser access from the dashboard.
- Removing anonymous database grants via migration `008_remove_anon_access.sql`.
- Removing GitHub Pages routing assumptions so the SPA deploys to a root origin
  (Vercel).

## Applying Migration 008 (existing databases)

The Postgres container runs init scripts only on the first boot of an empty
`pgdata` volume. Apply new migrations manually:

```bash
docker compose exec -T db psql -U postgres -d postgres -f - < supabase/migrations/008_remove_anon_access.sql
```

This migration:
- drops the `jobs_anon_select` policy,
- revokes any remaining `anon` grants on `jobs`,
- revokes `anon` grants on `bot_runs_public`,
- drops the `bot_runs_public` view (no backend consumer remains),
- asserts no anonymous business-data grants/policies remain.

Rollback: re-create the `bot_runs_public` view and re-grant `anon` SELECT if
anonymous browser access must be temporarily restored. This is **not**
recommended; prefer keeping the boundary closed.

## Future Runbooks (filled by later milestones)

- **Super-admin bootstrap** — idempotent local command (Milestone 4).
- **Inviting an admin** — one-time invitation tokens, TOTP enrollment (Milestone 5).
- **TOTP recovery** — recovery codes, forced re-enrollment (Milestone 5).
- **Role & permission changes** — granting/revoking, `authz_version` bump,
  refresh-token family revocation (Milestone 5).
- **Suspending / disabling an admin** — last-super-admin invariant (Milestone 5).
- **Audit export** — `audit.read` / `audit.export` (Milestones 8–10).
- **Broadcasts & destructive actions** — `system.destructive` gating (Milestone 10).

## Deployment Order Reminder

Always deploy backend changes before the dashboard. See
[DASHBOARD_DEPLOYMENT.md](DASHBOARD_DEPLOYMENT.md).
