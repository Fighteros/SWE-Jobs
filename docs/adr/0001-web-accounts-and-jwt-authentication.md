# ADR 0001: Web Accounts and JWT Authentication

Date: 2026-10-02
Status: Accepted

## Context

The existing `users` table holds Telegram users identified by `telegram_id`.
The dashboard currently has no web authentication and reads data directly from
Supabase with an anon key. We need a private, admin-only dashboard with no
ordinary web accounts in this release.

## Decision

1. Web login identities are administrators only — no public registration.
2. Admin accounts are stored in a dedicated `security.admin_accounts` table,
   completely independent from Telegram users.
3. Admin accounts carry **no** `telegram_id` and no Telegram-user foreign key.
4. Web privileges are **not** derived from `ADMIN_TELEGRAM_ID`.
5. Authentication uses JWT:
   - Short-lived access tokens (~10 min) stored only in React memory.
   - Rotating refresh tokens stored in a Secure, HttpOnly, API-domain cookie.
   - JWTs never in localStorage, sessionStorage, IndexedDB, URLs, or logs.
6. JWT signing uses an asymmetric algorithm (Ed25519/EdDSA) with key IDs and
   rotation support.
7. Passwords use Argon2id; TOTP is mandatory for all admin accounts.
8. The backend database remains the authority for account status, roles, and
   permissions; JWT role claims alone never authorize privileged operations.

## Consequences

- The `users` table is untouched for web auth purposes.
- A new `security.*` schema is introduced in a later milestone.
- Refresh-token rotation must be tracked server-side (token IDs/hashes, session
  families, revocation, reuse detection). Reusing an old refresh token revokes the
  whole family and creates an audit event.
- The frontend must not persist access tokens anywhere except memory.
