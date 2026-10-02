# Dashboard Deployment (Vercel)

> Status: **Milestone 1 — documentation in place; deployment not yet wired to Vercel.**
> The dashboard is currently built as a generic SPA. This guide describes the target
> Vercel deployment and the exact configuration required.

## Architecture

- **Frontend** — React + Vite SPA, deployed to Vercel.
- **Backend** — FastAPI, deployed separately (self-hosted VPS or another host).
- Both may be hosted by different providers but should share the same registrable
  domain so the refresh cookie can be scoped to the registrable domain.

Recommended production domains:

- Dashboard: `https://admin.example.com`
- API: `https://api.example.com`

## Vercel Project Settings

| Setting | Value |
|--------|-------|
| Framework preset | Vite |
| Root directory | `dashboard` |
| Build command | `npm run build` |
| Output directory | `dist` |
| Install command | `npm ci` |
| Node.js version | 22 LTS (set in Vercel Project → Settings → General) |

## Frontend Environment Variables (Vercel)

All `VITE_*` variables are **public** and embedded in the build. Never put JWT
keys, passwords, database credentials, TOTP encryption keys, service-role keys,
or any other secret in a Vercel variable.

| Variable | Required | Example | Notes |
|----------|----------|---------|-------|
| `VITE_API_BASE` | yes | `https://api.example.com` | Exact origin of the FastAPI backend. No trailing slash. |
| `VITE_APP_ENV` | yes | `production` | Environment label surfaced in the UI. Use `production` / `staging`. |
| `VITE_RELEASE_SHA` | no | `${vercel.gitCommitSha}` | Commit SHA for diagnostics. |

## Backend CORS (exact allowlist)

FastAPI must use an exact `DASHBOARD_ORIGINS` allowlist with credentials.
**Never use wildcard credentialed CORS.** In production set:

```
DASHBOARD_ORIGINS=https://admin.example.com
```

For staging:

```
DASHBOARD_ORIGINS=https://admin.staging.example.com,https://admin-preview-*.vercel.app
```

The backend must set `allow_credentials=True`, `allow_methods` per route, and
`allow_headers` per need. Preflight (`OPTIONS`) must be allowed without auth.

## Refresh-Cookie Behavior (target)

- Refresh JWTs are stored in a **Secure, HttpOnly** cookie scoped to the API
  domain (`Domain=.example.com` so the dashboard origin can send it).
- `SameSite=Lax` (or `None` with `Secure` if cross-site is unavoidable).
- The cookie is only sent to the API origin; the SPA never reads it.
- Refresh and logout endpoints require cookie credentials (`credentials: "include"`
  on the fetch) and CSRF protection (e.g., double-submit token or same-origin check).

## SPA Rewrites (Vercel)

Vercel serves a Vite SPA from `dist`. Client-side routes must fall back to
`index.html` for deep links. Add a `vercel.json` rewrite (Milestone 6 will add the
file; the contract is documented here):

```json
{
  "rewrites": [{ "source": "/(.*)", "destination": "/index.html" }]
}
```

## Security Headers (target)

Recommended headers to add via `vercel.json` headers (added in a later milestone):

| Header | Value |
|--------|-------|
| `Content-Security-Policy` | `default-src 'self'; connect-src 'self' https://api.example.com; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'` |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | `geolocation=(), microphone=(), camera=()` |

`VITE_API_BASE` must appear verbatim in the CSP `connect-src`. Never use `*`.

## Cache Policy

- `dist/assets/*` (hashed filenames) — immutable, `Cache-Control: public, max-age=31536000, immutable`.
- `index.html` — `Cache-Control: no-cache` (always revalidate).
- The Vite default build emits hashed asset names, so assets are safe to cache
  long; only `index.html` must revalidate.

## Deployment Order

1. Deploy backend changes (migrations, CORS, auth) first.
2. Verify `/livez` and CORS preflight against the dashboard origin.
3. Deploy the dashboard to Vercel.
4. Run smoke tests (below).

## Smoke Tests

After deploy:

1. `curl -i https://api.example.com/livez` → `200`.
2. `curl -i -X OPTIONS https://api.example.com/api/v1/auth/login \
     -H 'Origin: https://admin.example.com' \
     -H 'Access-Control-Request-Method: POST'` → `204` with
     `Access-Control-Allow-Origin: https://admin.example.com` and
     `Access-Control-Allow-Credentials: true`.
3. Open `https://admin.example.com/jobs` (deep link) → SPA loads, no 404.
4. Open browser devtools → Network: confirm no request to Supabase, all data
   requests go to `https://api.example.com`.
5. Confirm no `VITE_SUPABASE_*` variables remain in the build output
   (`grep -ri supabase dist/` returns nothing).

## Rollback

- Vercel: use the automatic Git rollback (redeploy a previous commit) or
  "Promote to Production" on a prior deployment.
- Backend: redeploy the previous image/tag; run the **down** portion of any new
  migration if it shipped one (each migration's changelog entry documents its
  rollback).

## Troubleshooting

### CORS errors in the browser
- Confirm `DASHBOARD_ORIGINS` includes the exact dashboard origin (scheme + host
  + port). No trailing slash.
- Confirm `allow_credentials=True` and that the request sends credentials where
  required.
- Preflight failures: ensure `OPTIONS` is allowed without auth.

### Cookies not sent / refresh fails
- Cookie must be `Secure` + `HttpOnly`, `SameSite=Lax` (or `None`+`Secure`),
  and `Domain` must cover the dashboard origin's registrable domain.
- The SPA fetch must use `credentials: "include"`.
- Cross-site without `SameSite=None; Secure` silently drops the cookie.

### CSRF errors
- Refresh/logout must include a CSRF token (double-submit or same-origin). A
  missing or mismatched token is rejected with `403`.

### JWT expiry / 401 loops
- Access tokens are short-lived (~10 min). The SPA must use the refresh cookie to
  obtain a new access token on `401`, then retry the original request once.
- A failed refresh (revoked family, expired session) must clear auth state and
  redirect to login.

### Deep-link 404s
- SPA rewrites must send all non-asset paths to `index.html`. Confirm
  `vercel.json` rewrites. Assets (`/assets/*`) must NOT be rewritten.

## See Also

- [ADMIN_DASHBOARD.md](ADMIN_DASHBOARD.md) — overall design and milestone roadmap.
- [ADMIN_OPERATIONS.md](ADMIN_OPERATIONS.md) — operational runbooks.
- `dashboard/.env.example` — frontend variable reference.
