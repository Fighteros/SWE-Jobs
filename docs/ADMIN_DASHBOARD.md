# Admin Dashboard

> Status: **Milestone 1 — Baseline & Boundary (in progress).**
> Authentication, RBAC, and admin operations are planned for later milestones and
> are **not** implemented yet. This document describes the target design and the
> current state of the work.

## Purpose

A private, admin-only React/Vite dashboard connected to the existing FastAPI
backend. The dashboard is deployed to Vercel; the backend is deployed separately.
FastAPI becomes the **only** browser-accessible data path.

There are no ordinary web accounts in this release. Every web-login identity is an
administrator. Admin accounts are completely independent from the existing Telegram
users — they do not carry a `telegram_id` and web privileges are never derived from
`ADMIN_TELEGRAM_ID`.

## Milestone Roadmap

The work is split into ordered milestones. Each milestone must pass before the next
begins.

1. **Baseline & Boundary** — documentation, CI, dependency upgrades, remove direct
   Supabase browser access, remove anonymous database grants, remove GitHub Pages
   routing assumptions, add boundary tests. **No JWT work in this milestone.**
2. **Job lifecycle & queue safety** — fix publication state, archive behavior, queue
   replay, worker fencing, atomic enqueue, ingestion locking, durable broadcasts.
3. **Admin security schema** — `security.*` tables for accounts, roles, permissions,
   sessions, TOTP, recovery codes, action tokens, audit, idempotency.
4. **Super-admin bootstrap** — idempotent local command to seed the first super-admin.
5. **Auth core** — password (Argon2id), TOTP, JWT (Ed25519/EdDSA with key IDs/rotation),
   refresh rotation, CORS allowlist, CSRF, RBAC enforcement.
6. **Login/TOTP vertical slice** — dashboard login flow with MFA challenge.
7. **Protect business APIs** — require access JWT on every business endpoint.
8. **Read-only admin modules** — jobs, runs, sources, deliveries, support, audit.
9. **Safe mutations** — non-destructive write operations behind permissions.
10. **Broadcasts, bulk ops, settings, destructive actions** — last, behind `system.destructive`.
11. **Staging verification → production cutover.**

High-risk controls are intentionally withheld until the underlying queue/job
correctness issues are fixed.

## Authentication & Authorization (target, not yet implemented)

- Admin accounts stored in `security.admin_accounts` (dedicated table).
- Authorization uses reusable roles mapped to named permissions (no per-account
  overrides initially).
- The seeded super-admin is an `admin_accounts` row assigned the `super_admin` role
  (not a separate table).
- Passwords hashed with Argon2id; TOTP mandatory for all admin accounts.
- JWT auth: short-lived access tokens (in-memory only), rotating refresh tokens
  (Secure, HttpOnly, API-domain cookie). JWTs never in localStorage/sessionStorage/
  IndexedDB/URLs/logs.
- Asymmetric signing (Ed25519/EdDSA) with key IDs and rotation.
- Backend database remains the authority for account status, roles, permissions;
  JWT role claims alone never authorize privileged operations.
- Every role/account/security change creates an audit event; role changes revoke
  relevant refresh-token families and increment `authz_version`.

Account states: `invited → pending_totp → active → suspended | disabled`.

See the ADRs under `docs/adr/` for the authoritative decisions.

## Permission Keys (target)

`dashboard.read`, `jobs.read`, `jobs.manage`, `jobs.archive`, `jobs.delete`,
`telegram-users.read`, `telegram-users.manage`, `runs.read`, `runs.trigger`,
`runs.cancel`, `sources.read`, `sources.manage`, `sources.probe`,
`deliveries.read`, `deliveries.replay`, `deliveries.cancel`,
`support.read`, `support.reply`, `support.manage`,
`broadcasts.read`, `broadcasts.create`, `broadcasts.dispatch`,
`settings.read`, `settings.manage`, `admins.read`, `admins.manage`,
`roles.manage`, `audit.read`, `audit.export`, `system.destructive`.

## API Boundary (target)

Unauthenticated allowlist only: `POST /api/v1/auth/login`,
`POST /api/v1/auth/mfa/verify`, `POST /api/v1/auth/invitations/{token}/accept`,
`GET /livez`, and CORS preflight. Everything else denies by default. Business requests
use `Authorization: Bearer <access-jwt>`. Refresh-cookie endpoints require cookie
credentials and CSRF protection.

See [DASHBOARD_DEPLOYMENT.md](DASHBOARD_DEPLOYMENT.md) for deployment and
[ADMIN_OPERATIONS.md](ADMIN_OPERATIONS.md) for operational runbooks.
