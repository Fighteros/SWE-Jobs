# Wuzzuf access

Wuzzuf sits behind Cloudflare. Plain HTTP clients (requests, and Scrapling's
plain `Fetcher`) get HTTP 403 and a "Just a moment" page from datacenter IPs.

## What the code does now

`sources/http_utils.get_protected_html()`:

1. Tries Scrapling's `Fetcher` (Chrome TLS impersonation). This is fast but is
   normally challenged.
2. On 403/503 or a challenge page, retries in one shared Scrapling
   `StealthySession` with `solve_cloudflare=True` (patchright browser, managed
   Turnstile solver). The session is reused for every Wuzzuf page in a run and
   closed at exit.

Verified from a fresh sandbox: the plain Fetcher returned 403; the
StealthySession returned HTTP 200 with job cards, about 9 seconds per page
after a roughly 15 second start.

## Caveats

- Cloudflare scores IP reputation. A residential or less-flagged IP passes more
  easily than a cloud server. If the server IP is still blocked, set a proxy on
  the session (Scrapling accepts `proxy=`) rather than adding another scraper.
- Browser deps come from `scrapling install` in the Dockerfile.
