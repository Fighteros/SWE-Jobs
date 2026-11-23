# Wuzzuf collection diagnosis

## Verified on 2026-11-23

- Deploy #57 completed successfully for `adce3d8`; its log reported backend healthy at 12:03:17 UTC. This clears the earlier container-build blocker, but `/health` is not a per-source ingestion test.
- The fork and upstream both fetch public category pages with `requests`. The histories have diverged, so merging upstream wholesale is not a targeted Wuzzuf repair.
- A direct request from the investigation environment received HTTP 403 and a Cloudflare interstitial. Plain headless Playwright received the same challenge. An interactive browser could display the category. These results do not establish the response seen by the production server.
- A captured public category page contained 20 listings. Before this change the parser returned 19, skipping an `/internship/` URL. It also read only the work-type/workplace block as tags, losing later skills and the SSR keyword list. Skill loss can change filtering scores and routing.
- HTTP failures returned an empty list without raising. The existing retry/circuit-breaker wrapper then recorded a successful source fetch. Challenge pages served as HTTP 200 had the same problem.

## What this change does

Collect internship links, retain card and SSR skills, and report an entirely failed Wuzzuf fetch as a source error. Explicit zero-result pages still return a normal empty list. Partial results are retained with a warning.

This does **not** bypass Cloudflare or establish that live production ingestion is restored. Adding plain Playwright as a fallback would not be a verified fix, so it is not included. No browser session, cookies, login, or external proxy is required or added by this PR.

## Production verification after review

Use the existing server access to inspect recent backend logs for `Wuzzuf`, `wuzzuf`, `403`, `access challenge`, `partial results`, and `collection failed`. Compare source-health records and new Wuzzuf jobs over a collection cycle. Do not infer source health only from a successful deploy or a healthy HTTP endpoint.

If the server is challenged too, a supported access route that works from that server is still needed. Repeated HTTP/headless retries are not a demonstrated solution. Keep the circuit breaker enabled rather than treating the block as zero available jobs.

## Validation

- Regression tests cover internships, card skills, SSR keywords, empty-result validation, challenges, transport failures, partial results, and circuit-breaker failure recording.
- The corrected parser returned all 20 listings from the captured category, including its internship, with skill metadata.
- Tests ran on Linux x86_64 / Python 3.10, not on the production aarch64 container. The production network response and end-to-end ingestion remain unverified.

Sources:

- https://github.com/Fighteros/SWE-Jobs/actions/runs/45170482423
- https://github.com/Fighteros/SWE-Jobs/actions/runs/45170482423/job/137678393786
- https://github.com/Fighteros/SWE-Jobs
- https://github.com/AbdullahSoudi/SWE-Jobs
- https://wuzzuf.net/a/Software-Development-Jobs-in-Egypt
