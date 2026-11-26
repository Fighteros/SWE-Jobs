# Sources added with the Scrapling migration

These job sources were not in the repo before. Each one was fetched live while
building this branch (counts from one run on Nov 26, 2026).

| Source key | Site | Access | Key needed | Live check |
|---|---|---|---|---|
| `hackernews` | Hacker News "Ask HN: Who is hiring?" (Algolia API) | JSON API | No | 208 postings from the Nov 2026 thread |
| `jobscollider` | Remote First Jobs (jobscollider.com API) | JSON API, 4 categories x 2 pages | No | 800 remote jobs |
| `landingjobs` | Landing.jobs (European tech jobs) | JSON API | No | 62 jobs |
| `jobspresso` | Jobspresso (curated remote jobs) | RSS | No | 20 jobs |
| `nodesk` | NoDesk (remote jobs) | RSS | No | 10 jobs |
| `careerjet` | Careerjet (Egypt, UAE, Saudi, UK, US) | JSON API v4 | Yes: `CAREERJET_API_KEY` | Not run live, needs a key |

`careerjet` already had a display name and icon in `core/channels.py` but no
fetcher. It is skipped silently while `CAREERJET_API_KEY` is empty.

## Notes

- Remote First Jobs asks API users to credit it and link to its own page. The
  job URL is its page and the source label credits it. Do not repost its jobs
  to LinkedIn or Google Jobs. The API delays jobs by 24 hours.
- Careerjet requires a Referer, the end user's IP and user agent on each call.
  Set `CAREERJET_REFERER` (your publisher site URL) and optionally
  `CAREERJET_USER_IP` if the defaults do not match your publisher account.
- Jobspresso, NoDesk and Remote First Jobs list non-engineering roles too. The
  existing title and seniority filters decide what is posted.
- All fetchers go through `sources/http_utils.py` (Scrapling). None needs a
  browser.

## Checked and left out

- Remote.co RSS: HTTP 403 (Akamai "Access Denied") from a plain fetch.
- RemoteYeah: no public API endpoint found.
- Egypt boards (Akhtaboot, Jobzella, Tanqeeb): pages respond, but need HTML
  parsers. Not added yet.
