# ADR 0002: Dashboard API Origin Model

Date: 2026-10-02
Status: Accepted

## Context

The dashboard is deployed to Vercel; the FastAPI backend is deployed separately.
They may be hosted by different providers but should share the same registrable
domain so the refresh cookie can be scoped correctly. The current backend uses
wildcard CORS and the dashboard reads directly from Supabase.

## Decision

1. FastAPI becomes the **only** browser-accessible data path. Direct Supabase
   browser access is removed (no `@supabase/supabase-js`, no `VITE_SUPABASE_*`).
2. The dashboard is configured exclusively through `VITE_API_BASE`,
   `VITE_APP_ENV`, and `VITE_RELEASE_SHA`. These are public build variables.
3. FastAPI uses an exact `DASHBOARD_ORIGINS` allowlist with credentials. No
   wildcard credentialed CORS.
4. Refresh cookies are Secure + HttpOnly, scoped to the registrable domain
   (`Domain=.example.com`), `SameSite=Lax` (or `None`+`Secure` if cross-site is
   unavoidable).
5. GitHub Pages routing assumptions (`/SWE-Jobs/` basename) are removed; the SPA
   deploys to a root origin.

## Consequences

- All dashboard data requests go through FastAPI with `Authorization: Bearer`.
- Refresh/logout endpoints require cookie credentials and CSRF protection.
- CSP `connect-src` must list the exact API origin.
- Vercel SPA rewrites send non-asset paths to `index.html`.
