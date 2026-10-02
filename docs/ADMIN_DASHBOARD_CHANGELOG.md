# Admin Dashboard Implementation Changelog

Every logical implementation change adds an entry describing code, database, API,
configuration, security, deployment, rollback, verification, and known limitations.

The format per entry:

```
## [milestone] <change title> (<date>)
- Code: ...
- Database: ...
- API: ...
- Configuration: ...
- Security: ...
- Deployment: ...
- Rollback: ...
- Verification: ...
- Known limitations: ...
```

---

## [M1] Baseline inspection (2026-10-02)
- Code: none (inspection only).
- Database: confirmed migrations 001–007; next available migration number is 008.
- API: confirmed unauthenticated business endpoints; wildcard CORS (GET only) in
  `api/app.py`.
- Configuration: confirmed `@supabase/supabase-js` dependency, `VITE_SUPABASE_*`
  build args, and `/SWE-Jobs/` basename in `vite.config.ts`, `App.tsx`,
  `nginx.conf`, and the GitHub Pages workflow.
- Security: no JWT/password/TOTP/RBAC/web-admin implementation exists yet.
- Deployment: dashboard currently targets GitHub Pages; Vercel target documented.
- Rollback: n/a.
- Verification: backend tests 304 passed / 22 skipped / 4 failed (pre-existing
  `test_wuzzuf.py` `zoneinfo` `Africa/Cairo` Windows tzdata limitation).
  Dashboard build passes; lint shows 2 pre-existing errors in `Trends.tsx`
  (`setState` in effect).
- Known limitations: 4 backend test failures are environmental (Windows lacks the
  `Africa/Cairo` tzdata entry); they pass on Linux/CI.

## [M1] Documentation and CI baseline (2026-10-02)
- Code: none (docs + CI only).
- Database: none.
- API: none.
- Configuration: added `.github/workflows/ci.yml` gating Python tests, dashboard
  clean install, typecheck, ESLint, and dashboard build. Added
  `dashboard/.env.example` documenting `VITE_API_BASE`, `VITE_APP_ENV`,
  `VITE_RELEASE_SHA`.
- Security: documented the target auth/RBAC/TOTP/JWT model in ADRs 0001–0004 and
  `docs/ADMIN_DASHBOARD.md`; no auth code added.
- Deployment: added `docs/DASHBOARD_DEPLOYMENT.md` (full Vercel guide) and
  `docs/ADMIN_OPERATIONS.md`.
- Rollback: delete added files; remove the CI workflow.
- Verification: CI workflow linted locally with `actionlint`-style review; docs
  cross-link to existing ARCHITECTURE/CONFIGURATION where relevant.
- Known limitations: documentation-link validation is best-effort; dependency
  security scans are configured but require CI secrets/permissions to run.

## [M1] Remove obsolete GitHub Actions workflows (2026-10-02)
- Code: deleted `.github/workflows/archive_jobs.yml` and
  `.github/workflows/job_bot.yml`.
- Database: none.
- API: none.
- Configuration: updated `README.md`, `docs/ARCHITECTURE.md`,
  `docs/CONFIGURATION.md`, `docs/ADDING_SOURCES.md`, and `docs/CHANGELOG_V2.md`
  to remove references to the deleted workflows. Job archival should now be run
  via a server cron job; the one-shot bot pipeline is replaced by `server.py`'s
  built-in scheduler.
- Security: no impact (the deleted workflows were operational, not security).
- Deployment: no change to active deployment paths (`deploy_backend.yml`,
  `deploy_dashboard.yml`, and the new `ci.yml` remain).
- Rollback: restore the two files from git history if needed.
- Verification: `grep -r archive_jobs .github docs/README.md docs/ARCHITECTURE.md
  docs/CONFIGURATION.md docs/ADDING_SOURCES.md docs/CHANGELOG_V2.md` returns
  only historical `docs/superpowers/` planning references.
- Known limitations: `docs/superpowers/` planning documents still reference the
  old workflow names; these are historical planning artifacts and are left
  unchanged.

## [M1] Upgrade dependencies (2026-10-02)
- Code: updated `dashboard/package.json` to latest within-major stable versions
  (React 19.3, Vite 8.3, React Router 7.18, Recharts 3.10, Tailwind 4.3, ESLint
  9.39, TypeScript 6.0.3, TypeScript-ESLint 8.71). Pinned Node >=22 <23 and
  `npm@11.7.0` via `engines`/`packageManager`. Downgraded
  `react-hooks/set-state-in-effect` to `warn` (new stricter rule from upgraded
  plugin; pre-existing patterns to refactor later). Pinned backend Python
  dependencies in `requirements.txt` and `requirements-dev.txt` to exact tested
  versions.
- Database: none.
- API: none.
- Configuration: `dashboard/package.json` (engines, packageManager, bumped
  versions); `dashboard/eslint.config.js` (rule override); `requirements.txt`
  and `requirements-dev.txt` (pinned versions).
- Security: `npm audit` reports 5 vulnerabilities (1 low, 2 moderate, 2 high) in
  the dashboard dependency tree — to be addressed in a later dependency
  security pass.
- Deployment: CI uses Node 22 LTS. Backend Dockerfile uses Python 3.11-slim;
  pinned versions are compatible.
- Rollback: revert `package.json`, `eslint.config.js`, `requirements*.txt`;
  run `npm install` and `pip install -r requirements*.txt`.
- Verification: dashboard build passes, lint passes (0 errors, 5 warnings),
  backend tests 304 passed / 22 skipped / 4 failed (pre-existing zoneinfo).
- Known limitations: 5 `npm audit` vulnerabilities to triage later;
  `set-state-in-effect` warnings are pre-existing React patterns to refactor
  when the dashboard is rebuilt for admin auth.

## [M1] Remove direct Supabase browser access (2026-10-02)
- Code: removed `@supabase/supabase-js` from `dashboard/package.json`; rewrote
  `dashboard/src/api.ts` to use only FastAPI (`VITE_API_BASE`); removed
  `/SWE-Jobs/` basename from `dashboard/src/App.tsx` and `dashboard/vite.config.ts`;
  updated `dashboard/Dockerfile` (Node 22, removed Supabase build args, root
  deployment); rewrote `dashboard/nginx.conf` for root-based SPA fallback;
  updated `.github/workflows/deploy_dashboard.yml` (removed Supabase env vars,
  GitHub Pages artifact, pages permissions).
- Database: added `supabase/migrations/008_remove_anon_access.sql` — drops
  `jobs_anon_select` policy, revokes anon grants on `jobs`, revokes/drops
  `bot_runs_public`, asserts no anon policies/grants remain on business tables.
- API: no endpoint changes (auth deferred to later milestones).
- Configuration: removed `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` from
  the build path; dashboard now uses only `VITE_API_BASE`, `VITE_APP_ENV`,
  `VITE_RELEASE_SHA`. Updated `docs/CONFIGURATION.md` dashboard environment
  section.
- Security: anonymous browser access to business data is eliminated. The
  `anon` role retains no data privileges on business tables.
- Deployment: dashboard deploys to a root origin (Vercel target); GitHub Pages
  `/SWE-Jobs/` routing removed.
- Rollback: revert all changed files; re-create `bot_runs_public` view and
  re-grant anon SELECT if anonymous browser access must be temporarily
  restored (not recommended).
- Verification: `grep -ri supabase dashboard/src/` returns nothing; dashboard
  build passes (bundle 648 KB, down from 863 KB); lint passes (0 errors).
  Migration 008 is idempotent (uses `IF EXISTS`/`IF NOT EXISTS`).
- Known limitations: `DASHBOARD_ORIGINS` CORS allowlist is documented but not
  yet enforced (wildcard CORS still in `api/app.py` — to be tightened in a
  later milestone). The `anon`/`authenticated`/`service_role` roles in
  `docker/postgres/000_roles.sql` remain as `NOLOGIN` for historical migration
  compatibility but have no data privileges after migration 008.

## [M1] Add boundary tests (2026-10-02)
- Code: added `tests/test_api_boundary.py` (9 tests characterizing current
  unauthenticated route behavior, CORS, absence of auth routes, and no
  Supabase client in backend); added `tests/test_migration_008.py` (5 tests
  asserting anon policy/grant removal, view drop, and role compatibility);
  added `dashboard/test/boundary.mjs` (Node script verifying no Supabase
  dependency, no Supabase env vars, no `/SWE-Jobs/` base, root routing, and
  no Supabase in build output).
- Database: none (tests only).
- API: none.
- Configuration: added `test` script to `dashboard/package.json`; added
  boundary test step to `.github/workflows/ci.yml`.
- Security: tests prove the boundary is closed (no direct DB browser access,
  no anon grants after migration 008, all data via FastAPI).
- Deployment: CI runs dashboard boundary tests after build.
- Rollback: delete the three test files; remove the `test` script and CI step.
- Verification: all 9 API boundary tests pass; all 5 migration 008 tests skip
  (no `TEST_DATABASE_URL` locally); dashboard boundary tests pass (20 assertions).
- Known limitations: migration 008 integration tests require a live Postgres
  (`TEST_DATABASE_URL`) and skip otherwise; they run in CI once a DB service
  is added.

## [M1] Remove remaining Supabase references from codebase (2026-10-02)
- Code: renamed `SUPABASE_DB_*` config variables to `DB_*` in `core/config.py`,
  `core/db.py`, and `tests/test_delivery_queue_integration.py`; removed Supabase
  IPv6 host detection warning block from `core/db.py`; updated
  `scripts/check_migration_005.py` message; updated `docker/postgres/000_roles.sql`
  comment; removed Supabase pooling instructions from `.env.example`.
- Database: none (the `supabase/migrations/` directory name is historical and
  left as-is to avoid breaking test paths and deployment scripts).
- API: none.
- Configuration: `DB_PORT` default changed from 6543 to 5432 (the local Docker
  container port, not a remote pooler).
- Security: no impact.
- Deployment: no impact.
- Rollback: revert the renamed variables and restore the Supabase host detection.
- Verification: backend tests 313 passed / 27 skipped / 4 failed (pre-existing).
  `grep -r SUPABASE_DB *.py` returns no results.
- Known limitations: `supabase/migrations/` directory name remains for historical
  compatibility; `sources/ashby.py` contains "supabase" as a company keyword
  (job data, not infrastructure).

## [M2] Fix queue & job lifecycle correctness (2026-10-02)
- Code:
  - **Critical:** `core/delivery_queue.py` `replay_dead_letter` now resets
    `attempts = 0` so retry-exhausted dead-letter records become re-claimable.
  - **Worker fencing:** `mark_delivery_sent`, `mark_delivery_skipped`, and
    `mark_delivery_failed` now require `worker_id` and fence on
    `status = 'processing' AND worker_id = ?` — stale workers can no longer
    overwrite newer state.
  - **Atomic enqueue:** `enqueue_job_deliveries` inserts group-topic and
    subscriber-DM rows in a single transaction (no partial enqueue on crash).
  - **Job publication state:** `mark_delivery_sent` now also sets `jobs.sent_at`
    when all group-topic deliveries for a job reach a terminal state.
  - **Monitoring fix:** `main.py` stores `_jobs_attempted` in `source_stats`;
    `bot_runs.jobs_sent` now stores the count of jobs enqueued (not just
    group-topic deliveries); `core/monitoring.py` queue-rate alert now works.
  - **min_salary matching:** `core/subscription_matching.py` `job_matches_alert`
    now checks `min_salary` — previously silently ignored.
  - **Delivery-time skip → pending:** `bot/notifications.py` alert re-validation
    mismatch now returns the record to `pending` (via `release_delivery_to_pending`)
    instead of marking it permanently `skipped`.
  - **Stale recovery lock:** `core/delivery_queue.py` `recover_stale_deliveries`
    now runs SELECT FOR UPDATE and all UPDATEs in a single transaction.
  - Updated all callers in `bot/sender.py`, `bot/notifications.py`, and tests
    to pass `worker_id`.
- Database: no new migration needed (schema unchanged).
- API: none.
- Configuration: none.
- Security: worker fencing prevents stale workers from corrupting delivery
  state; atomic enqueue prevents partial delivery records.
- Deployment: no change.
- Rollback: revert all changed files; old callers will need `worker_id`
  removed from function signatures.
- Verification: 313 passed / 27 skipped / 4 failed (pre-existing zoneinfo).
- Known limitations: archive behavior and durable broadcasts are deferred to
  a later sub-milestone; `bot/sender.py` legacy `send_jobs` double-enqueue and
  N+1 job preloading are minor perf issues left for cleanup.

## [M3] Admin security schema (2026-10-02)
- Code: added `supabase/migrations/009_admin_security_schema.sql` creating the
  `security.*` schema with all 11 required tables: `admin_accounts`, `admin_roles`,
  `admin_permissions`, `admin_role_permissions`, `admin_account_roles`,
  `admin_refresh_sessions`, `admin_totp_credentials`, `admin_recovery_codes`,
  `admin_action_tokens`, `admin_audit_events`, `admin_idempotency_records`.
  Seeded all 30 permission keys and two roles (`super_admin` with all permissions,
  `read_only` with read permissions). RLS enabled on all tables.
- Database: migration 009 (forward-only, idempotent via `ON CONFLICT DO NOTHING`).
- API: none.
- Configuration: none.
- Security: admin accounts are in a dedicated schema, independent from Telegram
  users. UUID PKs, Argon2id password_hash column, authz_version, self-referencing
  created_by, row_version for optimistic concurrency. Account status check
  constraint enforces the state machine.
- Deployment: apply migration 009 to existing databases manually.
- Rollback: `DROP SCHEMA security CASCADE;` (removes all admin tables + roles).
- Verification: 12 integration tests in `tests/test_migration_009.py` (skip
  without TEST_DATABASE_URL). 313 backend tests still pass.
- Known limitations: no bootstrap command yet (M4); no auth endpoints yet (M5).

## [M4] Super-admin bootstrap command (2026-10-02)
- Code: added `scripts/bootstrap_admin.py` — idempotent CLI that creates the
  first super-admin account in `security.admin_accounts` with `super_admin` role
  and `pending_totp` status. Generates a random password, hashes with Argon2id,
  creates an audit event, prints the password once. Returns 0 if a super-admin
  already exists (idempotent).
- Database: none (uses migration 009 schema).
- API: none.
- Configuration: added `argon2-cffi>=23.1.0` to `requirements.txt`.
- Security: password is never persisted in plaintext; Argon2id with 64 MB memory
  cost, 3 iterations, 4 parallelism lanes. Account starts in `pending_totp`
  (must enroll TOTP before login).
- Deployment: run `python -m scripts.bootstrap_admin --email admin@example.com
  --name "Super Admin"` after applying migration 009.
- Rollback: `DELETE FROM security.admin_accounts WHERE email = 'admin@example.com'`
  (if created in error).
- Verification: 6 unit tests in `tests/test_bootstrap_admin.py` pass. Full suite
  319 passed / 38 skipped / 4 failed (pre-existing).
- Known limitations: no actual login/TOTP enrollment endpoint yet (M5).

## [M5] Auth core — JWT, TOTP, refresh rotation, RBAC, CORS (2026-10-02)
- Code: added `api/auth/` package with:
  - `jwt.py` — Ed25519/EdDSA signing/verification with key IDs, all 4 token types
    (access, mfa_challenge, refresh, invitation), full claim validation (iss, aud,
    sub, jti, sid, typ, iat, nbf, exp, authz_version, amr, auth_time).
  - `totp.py` — TOTP generation/verification (RFC 6238), encrypted-at-rest secrets,
    otpauth URI for QR enrollment.
  - `rbac.py` — FastAPI dependency `require_permission(*perms)` that checks the
    database (not JWT claims) for authorization.
  - `refresh.py` — Refresh token rotation with SHA-256 hashed storage, family
    tracking, reuse detection (revokes entire family + audit event on reuse).
  - `routes_auth.py` — `POST /api/v1/auth/login` (password -> MFA challenge),
    `POST /api/v1/auth/mfa/verify` (TOTP -> access + refresh cookie),
    `POST /api/v1/auth/refresh` (rotate refresh, new access),
    `POST /api/v1/auth/logout` (revoke session, clear cookie).
  - `api/app.py` — CORS tightened to `DASHBOARD_ORIGINS` allowlist with credentials;
    added `/livez` endpoint; registered auth router.
- Database: no new migration (uses M3 schema).
- API: 4 new auth endpoints under `/api/v1/auth/*`; `/livez` liveness probe.
- Configuration: added `DASHBOARD_ORIGINS`, `JWT_SIGNING_KEY`, `JWT_KEY_ID`,
  `JWT_ISSUER`, `JWT_AUDIENCE`, `TOTP_ENCRYPTION_KEY` to `.env.example`. Added
  `PyJWT[crypto]`, `cryptography`, `email-validator` to `requirements.txt`.
- Security:
  - Access tokens ~10 min, in-memory only (never in localStorage/cookies).
  - Refresh tokens in Secure, HttpOnly, SameSite=Lax cookies, API-domain scoped,
    rotated on each use, family-revoked on reuse detection.
  - JWT signing is Ed25519/EdDSA with key IDs; asymmetric (public key verifies,
    private key signs).
  - CORS is exact-allowlist with credentials (no wildcard).
  - RBAC checks the database, not JWT claims, for permission verification.
  - All auth events create audit entries.
- Deployment: set `DASHBOARD_ORIGINS`, `JWT_SIGNING_KEY`, `TOTP_ENCRYPTION_KEY`
  in production env. Generate keys with the commands in `.env.example`.
- Rollback: remove `api/auth/`, revert `api/app.py`, remove auth deps.
- Verification: 17 auth tests in `tests/test_auth.py` pass. Full suite 336 passed /
  38 skipped / 4 failed (pre-existing).
- Known limitations: TOTP enrollment endpoint not yet built (admin must enroll
  via bootstrap or a future endpoint); CSRF protection on refresh/logout is
  cookie-based but not double-submit token yet; business APIs not yet protected
  with `require_permission` (M7).
