# Egypt-only Salaries via egytech.fyi — Design

**Status:** Draft
**Date:** 2026-04-25
**Branch:** `claude/zealous-bohr-8ce1d1`

## Problem

Salary data in this app is currently parsed out of free-text job postings (`core/salary_parser.py`) and aggregated globally — mixing currencies, periods, and countries. The `/api/stats/salary` endpoint, the Salary dashboard page, the `/salary` bot command, and per-job salary chips all draw from this noisy pool. The user wants salaries to be **Egypt-only** and use **egytech.fyi** as the source of truth — a community-driven Egyptian tech compensation survey (~2,100 responses, April 2024) exposed via a public API at `https://api.egytech.fyi`.

## Decisions

| Decision | Choice |
|---|---|
| Strategy | **Replace** posting-derived salary aggregations entirely with egytech.fyi data |
| Data fetch | **Live proxy with 24h in-memory cache** |
| Filters exposed | **Role + seniority + years-of-experience range** |
| Default | **Exclude** relocated and remote-abroad participants |
| Per-job card salary | **Hide unless** the job is Egypt-based AND maps to an egytech (title, level) combo |

## Architecture

Two new modules:

### `core/egytech.py` — HTTP client
- `get_stats(title: str, level: str | None = None, yoe_from: int | None = None, yoe_to: int | None = None) -> dict | None` — GETs `https://api.egytech.fyi/stats` with `include_relocated=false` and `include_remote_abroad=false` always pinned.
- Returns `{ totalCount, median, p20Compensation, p75Compensation, p90Compensation, buckets }` on success, `None` on 404 or network failure.
- 24h in-memory TTL cache: `dict[(title, level, yoe_from, yoe_to), (timestamp, response)]`.
- Failures log a warning. Callers handle `None` (render empty state, never 500).

### `core/egytech_mapping.py` — enum translation

```python
SENIORITY_TO_LEVEL = {
    "intern":    "intern",
    "junior":    "junior",
    "mid":       "mid_level",
    "senior":    "senior",
    "lead":      "team_lead",
    "executive": "c_level",
}

TOPIC_TO_TITLE = {
    "backend":       "backend",
    "frontend":      "frontend",
    "fullstack":     "fullstack",
    "mobile":        "mobile",
    "devops":        "devops_sre_platform",
    "qa":            "testing",
    "cybersecurity": "security",
    # gamedev, blockchain, erp, internships, general → no mapping (return None)
}
```

- `parse_role_query(text: str) -> str | None` — for the bot/dashboard's free-text role input. Lowercases input and matches against title aliases (`"python"`, `"java"`, `"node"` → `backend`; `"react"`, `"vue"`, `"angular"` → `frontend`; etc.). Unrecognized → `None`.

**Why two modules:** The HTTP client is pure transport; the mapping table grows over time as we add aliases or as egytech adds new titles. Separating them keeps the client tiny and the mapping easy to extend.

**Why in-memory cache:** Dataset is static between annual surveys. Cardinality is bounded (~7 mapped titles × 6 mapped levels × ~5 YoE buckets ≈ 200 combos worst case). Per-worker dict is enough; no Redis dependency.

## Components Changed

### 1. `/api/stats/salary` (api/routes_stats.py) — rewritten

**New query params:** `role` (free-text), `seniority` (enum), `yoe_from` (int), `yoe_to` (int).
**New response shape:**

```json
{
  "currency": "EGP",
  "period": "monthly",
  "source": "egytech.fyi April 2024 survey",
  "stats": {
    "sample_size": 152,
    "median": 33800,
    "p20": 21200,
    "p75": 44000,
    "p90": 63000
  },
  "buckets": [{"label": "20-25K", "count": 19}, ...],
  "filters": {"role": "backend", "seniority": "mid", "yoe_from": null, "yoe_to": null},
  "matched": true
}
```

If role doesn't map or egytech returns no data: `matched: false`, `stats: null`.

This is a **breaking change** in response shape. Acceptable — the dashboard is the only known consumer.

### 2. Salary dashboard page (`dashboard/src/pages/Salary.tsx`) — rewritten

- Header: "Egyptian Tech Salaries — Source: egytech.fyi (April 2024 survey)".
- Filters row: role dropdown (egytech's 23 titles), seniority dropdown (our 6 levels), YoE range slider 0–20.
- Stat cards: sample size · median (EGP/mo) · p20–p75 range · p90.
- Chart: distribution histogram from `buckets[]`. (Replaces the by-seniority bar chart; revisit if needed — would require N parallel API calls, cheap with cache.)
- Empty state when `matched: false`: "No data for this combination — try a broader filter."
- All amounts displayed with `EGP` prefix and `/mo` suffix.
- Update `dashboard/src/types.ts` to match new response shape.

### 3. `/salary` bot command (`bot/commands.py`) — rewritten

Usage: `/salary <role> [seniority] [yoe]`. `<role>` is required. `[seniority]` is one of our 6 levels. `[yoe]` is a single integer; when supplied, the API call uses `yoe_from_included = yoe` and `yoe_to_excluded = yoe + 1` (filter to that exact YoE). Output:

```
💰 backend / mid · n=152
Median: EGP 33,800/mo
P20–P75: EGP 21,200 – 44,000/mo
P90: EGP 63,000/mo
Source: egytech.fyi April 2024
```

Args parsed positionally. Unmapped role → "No data for X. Try: backend, frontend, fullstack, mobile, devops, qa, security, ..."

### 4. Per-job card salary (`dashboard/src/components/JobCard.tsx`, `bot/sender.py`)

- Always hide `salary_raw`, `salary_min`, `salary_max`.
- For Egypt-based jobs (`country == "EG"`): if `(TOPIC_TO_TITLE[primary_topic], SENIORITY_TO_LEVEL[seniority])` resolves AND `get_stats(...)` returns data → render `Market: EGP 21k–44k/mo` (p20–p75 rounded to 1k).
- Else: no salary line.
- Listing endpoint server-side enriches each Egypt job with a `market_salary` field via the same cache. Cache hits dominate after warmup.

### 5. Enrichment pipeline (`core/enrichment.py`) — simplified

- Remove the `parse_salary` step (lines 78-83).
- Stop importing `core.salary_parser`.
- Delete `core/salary_parser.py` and `tests/test_salary_parser.py`.

### 6. Job model & DB

- **Keep** `salary_min`, `salary_max`, `salary_currency`, `salary_raw` columns. Stop populating them. No migration. Reversible if needed; drop in a follow-up once stable.

### 7. Subscription "min salary" filter (`bot/commands.py`, `bot/notifications.py`)

Drop entirely:
- Remove the min-salary step from the multi-step `/subscribe` flow.
- Remove `min_salary` from the notification matcher.
- Remove the `Min salary: $X/year` line in `/mysubs` output (currently `bot/commands.py:125`).
- The `users.subscriptions` JSONB keeps the field for back-compat — we just stop reading/writing it. Existing users' saved values become no-ops.

### 8. Telegram job message (`bot/sender.py`)

Currently includes posting-derived salary inline. Switch to:
- Egypt jobs with matched egytech reference → "Market: EGP 21k–44k/mo".
- Else: omit the salary line entirely.
- Reuses `core.egytech.get_stats` (same cache as the API/dashboard).

## Data Flow

```
[ Job listing request ] → [ /api/jobs/search ]
                             ↓
                          For each Egypt job:
                             ↓
                          (topic, seniority) → mapping → (title, level)
                             ↓
                          core.egytech.get_stats(title, level)  [cache lookup → API on miss]
                             ↓
                          attach market_salary field

[ Salary page filter change ] → [ /api/stats/salary?role=backend&seniority=mid ]
                                   ↓
                                mapping → (title, level)
                                   ↓
                                core.egytech.get_stats(title, level)
                                   ↓
                                return stats + buckets

[ /salary <role> [seniority] [yoe] ] → bot command → mapping → get_stats → render text
```

## Error Handling

| Failure | Behavior |
|---|---|
| egytech 404 (no participants for combo) | `get_stats` returns `None`. **Cached** (real "no data" answer). UI shows empty state. |
| egytech network error / timeout | Logged at WARNING. `get_stats` returns `None`. **Not cached** — next call retries. UI shows empty state. |
| Unmapped role/topic | `mapping` returns `None`. Skip API call entirely. UI shows empty state. |
| Job has no `country` or `country != "EG"` | No market lookup. No salary line on card. |
| Job has no `seniority` | Skip — return `None`. We don't fabricate data. |

The 404-vs-network distinction matters: per-job lookups for valid combos that happen to have zero participants (e.g. some niche title+level) shouldn't pound the API. Network errors must remain retryable.

## Testing

| Test | Type |
|---|---|
| `tests/test_egytech_client.py` | Unit. Mock HTTP. Verify URL construction (incl. pinned `include_relocated=false&include_remote_abroad=false`), cache hit on repeat call, `None` on 404 and on network error. |
| `tests/test_egytech_mapping.py` | Unit. Verify each entry in `SENIORITY_TO_LEVEL` and `TOPIC_TO_TITLE` maps; verify unmapped topics (`gamedev`, `blockchain`, `erp`) return `None`; verify `parse_role_query` aliases. |
| `tests/test_egytech_integration.py` | Integration, marked `@pytest.mark.integration`, skipped by default. Hits the live API once with `title=backend&level=mid_level` and asserts `median > 0`. |
| Updated: `tests/test_enrichment.py` | Verify the salary parsing step is gone — old tests asserting `salary_min` gets populated must be removed/updated. |
| Deleted: `tests/test_salary_parser.py` | Module deleted. |

## Caveats

- Dataset is from April 2024. Until egytech publishes a new survey, all numbers are static. Surface this date everywhere salaries are shown.
- All values are **monthly EGP**. UI must label `/mo` to avoid the impression of yearly.
- Per-job market line adds 1 cache lookup per job rendered. Cache cardinality is small (~50 combos in practice), so warmup is fast and steady-state is ~100% hit rate.
- `core.egytech.get_stats` returning `None` is the dominant signal — every consumer must handle it.
