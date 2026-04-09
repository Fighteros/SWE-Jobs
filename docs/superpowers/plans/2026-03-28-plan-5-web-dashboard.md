# Plan 5: Web Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a public React dashboard showing live job feed with filters, statistics charts, salary insights, and skill trends — plus the FastAPI backend endpoints powering it.

**Architecture:** React + Tailwind CSS SPA on GitHub Pages. Data from two sources: (1) Supabase PostgREST API for simple queries (job feed, filtered lists) and (2) custom FastAPI endpoints for complex aggregations (salary stats, trends). Rate-limited via slowapi.

**Tech Stack:** React 18, TypeScript, Tailwind CSS, Recharts, Vite, FastAPI, slowapi

**Spec:** `docs/superpowers/specs/2026-03-28-v2-redesign-design.md` (Section 4)

**Depends on:** Plan 1 (core/db.py, schema), Plan 2 (enrichment)
**Blocks:** Plan 6 (integration)

---

## File Structure

```
api/
├── __init__.py
├── app.py              # FastAPI app factory with CORS and rate limiting
├── routes_jobs.py      # GET /api/jobs/search
├── routes_stats.py     # GET /api/stats/summary, salary, trends
└── middleware.py        # Rate limiting config (slowapi)
dashboard/
├── package.json
├── tsconfig.json
├── vite.config.ts
├── index.html
├── tailwind.config.js
├── postcss.config.js
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── api.ts           # Supabase client + custom API client
│   ├── types.ts         # TypeScript interfaces
│   ├── pages/
│   │   ├── Home.tsx     # Job feed with filters
│   │   ├── Stats.tsx    # Charts and numbers
│   │   ├── Salary.tsx   # Salary insights
│   │   └── Trends.tsx   # Skill trends
│   └── components/
│       ├── Layout.tsx   # Nav bar + page container
│       ├── JobCard.tsx  # Single job card
│       ├── FilterBar.tsx # Topic, seniority, salary, remote filters
│       └── Charts.tsx   # Reusable chart wrappers
.github/workflows/
├── deploy_dashboard.yml # Build + deploy to GitHub Pages
server.py                # FastAPI + bot polling entry point
requirements.txt         # Updated with fastapi, uvicorn, slowapi
```

---

### Task 1: FastAPI Application Setup

**Files:**
- Create: `api/__init__.py`
- Create: `api/app.py`
- Create: `api/middleware.py`
- Modify: `requirements.txt` — add `fastapi>=0.110.0`, `uvicorn>=0.27.0`, `slowapi>=0.1.9`

- [ ] **Step 1: Update requirements.txt**

Add to `requirements.txt`:
```
fastapi>=0.110.0
uvicorn>=0.27.0
slowapi>=0.1.9
```

- [ ] **Step 2: Write api/__init__.py**

```python
# api/__init__.py
```

- [ ] **Step 3: Write api/middleware.py**

```python
# api/middleware.py
"""Rate limiting configuration using slowapi."""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
```

- [ ] **Step 4: Write api/app.py**

```python
# api/app.py
"""
FastAPI application factory.
Serves the dashboard API endpoints with CORS and rate limiting.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.middleware import limiter


def create_app() -> FastAPI:
    app = FastAPI(title="SWE-Jobs API", version="2.0.0")

    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # CORS — allow dashboard origin
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Tighten to GitHub Pages URL in production
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    # Register routes
    from api.routes_jobs import router as jobs_router
    from api.routes_stats import router as stats_router
    app.include_router(jobs_router, prefix="/api/jobs")
    app.include_router(stats_router, prefix="/api/stats")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app
```

- [ ] **Step 5: Commit**

```bash
git add api/__init__.py api/app.py api/middleware.py requirements.txt
git commit -m "feat: add FastAPI app with CORS and rate limiting"
```

---

### Task 2: API Routes — Jobs Search

**Files:**
- Create: `api/routes_jobs.py`

- [ ] **Step 1: Write api/routes_jobs.py**

```python
# api/routes_jobs.py
"""Job search and listing endpoints."""

from fastapi import APIRouter, Query, Request
from typing import Optional
from api.middleware import limiter
from core import db

router = APIRouter()


@router.get("/search")
@limiter.limit("30/minute")
async def search_jobs(
    request: Request,
    q: Optional[str] = Query(None, description="Search query"),
    topic: Optional[str] = Query(None, description="Filter by topic"),
    seniority: Optional[str] = Query(None, description="Filter by seniority"),
    min_salary: Optional[int] = Query(None, description="Minimum salary (yearly)"),
    remote: Optional[bool] = Query(None, description="Remote only"),
    country: Optional[str] = Query(None, description="Country ISO code"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=50, description="Items per page"),
):
    """Search and filter jobs."""
    conditions = ["sent_at IS NOT NULL"]
    params = []
    param_idx = 1

    if q:
        conditions.append(f"(title ILIKE ${param_idx} OR ${param_idx + 1} = ANY(tags))")
        params.extend([f"%{q}%", q.lower()])
        param_idx += 2

    if topic:
        conditions.append(f"${param_idx} = ANY(topics)")
        params.append(topic)
        param_idx += 1

    if seniority:
        conditions.append(f"seniority = ${param_idx}")
        params.append(seniority)
        param_idx += 1

    if min_salary:
        conditions.append(f"salary_max >= ${param_idx}")
        params.append(min_salary)
        param_idx += 1

    if remote:
        conditions.append("is_remote = TRUE")

    if country:
        conditions.append(f"country = ${param_idx}")
        params.append(country)
        param_idx += 1

    where = " AND ".join(conditions)
    offset = (page - 1) * per_page

    # Use psycopg2 %s style params (not $N - that's asyncpg)
    # Rebuild with %s placeholders
    conditions_sql = ["sent_at IS NOT NULL"]
    params_sql = []

    if q:
        conditions_sql.append("(title ILIKE %s OR %s = ANY(tags))")
        params_sql.extend([f"%{q}%", q.lower()])
    if topic:
        conditions_sql.append("%s = ANY(topics)")
        params_sql.append(topic)
    if seniority:
        conditions_sql.append("seniority = %s")
        params_sql.append(seniority)
    if min_salary:
        conditions_sql.append("salary_max >= %s")
        params_sql.append(min_salary)
    if remote:
        conditions_sql.append("is_remote = TRUE")
    if country:
        conditions_sql.append("country = %s")
        params_sql.append(country)

    where_sql = " AND ".join(conditions_sql)

    # Count total
    count_row = db._fetchone(
        f"SELECT COUNT(*) as total FROM jobs WHERE {where_sql}",
        tuple(params_sql),
    )
    total = count_row["total"] if count_row else 0

    # Fetch page
    rows = db._fetchall(
        f"""SELECT id, title, company, location, url, source, original_source,
                   salary_raw, salary_min, salary_max, salary_currency,
                   job_type, seniority, is_remote, country, tags, topics, created_at
            FROM jobs WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s""",
        tuple(params_sql) + (per_page, offset),
    )

    return {
        "jobs": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total else 0,
    }
```

- [ ] **Step 2: Commit**

```bash
git add api/routes_jobs.py
git commit -m "feat: add job search API endpoint with filters and pagination"
```

---

### Task 3: API Routes — Stats

**Files:**
- Create: `api/routes_stats.py`

- [ ] **Step 1: Write api/routes_stats.py**

```python
# api/routes_stats.py
"""Statistics, salary insights, and trend endpoints."""

from fastapi import APIRouter, Query, Request
from typing import Optional
from api.middleware import limiter
from core import db

router = APIRouter()


@router.get("/summary")
@limiter.limit("30/minute")
async def stats_summary(request: Request):
    """Aggregated stats for the dashboard home page."""
    today = db._fetchone(
        "SELECT COUNT(*) as count FROM jobs WHERE created_at > now() - make_interval(days := 1)"
    )
    week = db._fetchone(
        "SELECT COUNT(*) as count FROM jobs WHERE created_at > now() - make_interval(days := 7)"
    )
    total = db._fetchone("SELECT COUNT(*) as count FROM jobs")

    by_source = db._fetchall(
        """SELECT source, COUNT(*) as count FROM jobs
           WHERE created_at > now() - make_interval(days := 7)
           GROUP BY source ORDER BY count DESC"""
    )

    by_topic = db._fetchall(
        """SELECT unnest(topics) as topic, COUNT(*) as count FROM jobs
           WHERE created_at > now() - make_interval(days := 7)
           GROUP BY topic ORDER BY count DESC"""
    )

    top_companies = db._fetchall(
        """SELECT company, COUNT(*) as count FROM jobs
           WHERE created_at > now() - make_interval(days := 7)
             AND company != ''
           GROUP BY company ORDER BY count DESC LIMIT 10"""
    )

    return {
        "jobs_today": today["count"] if today else 0,
        "jobs_week": week["count"] if week else 0,
        "jobs_total": total["count"] if total else 0,
        "by_source": by_source,
        "by_topic": by_topic,
        "top_companies": top_companies,
    }


@router.get("/salary")
@limiter.limit("20/minute")
async def salary_stats(
    request: Request,
    role: Optional[str] = Query(None, description="Role keyword (e.g. backend, python)"),
    country: Optional[str] = Query(None, description="Country ISO code"),
    seniority: Optional[str] = Query(None, description="Seniority level"),
):
    """Salary breakdown by role, country, and seniority."""
    conditions = ["salary_min IS NOT NULL", "created_at > now() - make_interval(days := 30)"]
    params = []

    if role:
        conditions.append("title ILIKE %s")
        params.append(f"%{role}%")
    if country:
        conditions.append("country = %s")
        params.append(country)
    if seniority:
        conditions.append("seniority = %s")
        params.append(seniority)

    where = " AND ".join(conditions)

    overall = db._fetchone(
        f"""SELECT
              COUNT(*) as sample_size,
              ROUND(AVG(salary_min)) as avg_min,
              ROUND(AVG(salary_max)) as avg_max,
              MIN(salary_min) as lowest,
              MAX(salary_max) as highest,
              ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY salary_min)) as median_min
            FROM jobs WHERE {where}""",
        tuple(params),
    )

    by_seniority = db._fetchall(
        f"""SELECT seniority,
              COUNT(*) as count,
              ROUND(AVG(salary_min)) as avg_min,
              ROUND(AVG(salary_max)) as avg_max
            FROM jobs WHERE {where}
            GROUP BY seniority ORDER BY avg_min DESC""",
        tuple(params),
    )

    return {
        "overall": overall,
        "by_seniority": by_seniority,
        "filters": {"role": role, "country": country, "seniority": seniority},
    }


@router.get("/trends")
@limiter.limit("20/minute")
async def skill_trends(
    request: Request,
    period: str = Query("7d", description="Period: 7d, 14d, 30d"),
):
    """Skill trends with week-over-week change."""
    days = {"7d": 7, "14d": 14, "30d": 30}.get(period, 7)
    half = days // 2

    # Current period
    current = db._fetchall(
        """SELECT unnest(tags) as skill, COUNT(*) as count
           FROM jobs WHERE created_at > now() - make_interval(days := %s)
           GROUP BY skill ORDER BY count DESC LIMIT 20""",
        (days,),
    )

    # Previous period (for comparison)
    previous = db._fetchall(
        """SELECT unnest(tags) as skill, COUNT(*) as count
           FROM jobs WHERE created_at BETWEEN
             now() - make_interval(days := %s)
             AND now() - make_interval(days := %s)
           GROUP BY skill ORDER BY count DESC LIMIT 20""",
        (days * 2, days),
    )

    prev_map = {r["skill"]: r["count"] for r in previous}
    trends = []
    for row in current:
        skill = row["skill"]
        current_count = row["count"]
        prev_count = prev_map.get(skill, 0)
        change = ((current_count - prev_count) / max(prev_count, 1)) * 100
        trends.append({
            "skill": skill,
            "count": current_count,
            "previous_count": prev_count,
            "change_percent": round(change, 1),
        })

    return {"period": period, "trends": trends}
```

- [ ] **Step 2: Commit**

```bash
git add api/routes_stats.py
git commit -m "feat: add stats API endpoints (summary, salary, trends)"
```

---

### Task 4: Server Entry Point

**Files:**
- Create: `server.py`

- [ ] **Step 1: Write server.py**

```python
# server.py
"""
FastAPI server + Telegram bot polling entry point.
Both run in the same asyncio event loop.
"""

import asyncio
import logging
import uvicorn

from core.logging_config import setup_logging
from api.app import create_app

setup_logging()
log = logging.getLogger(__name__)

app = create_app()


@app.on_event("startup")
async def startup():
    """Start the Telegram bot polling alongside FastAPI."""
    try:
        from bot.app import start_polling
        asyncio.create_task(start_polling())
        log.info("Bot polling started alongside FastAPI")
    except Exception as e:
        log.warning(f"Bot polling failed to start: {e} (API still running)")


@app.on_event("shutdown")
async def shutdown():
    """Stop bot and close DB pool."""
    try:
        from bot.app import stop_polling
        await stop_polling()
    except Exception:
        pass
    try:
        from core.db import close_pool
        close_pool()
    except Exception:
        pass


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
```

- [ ] **Step 2: Commit**

```bash
git add server.py
git commit -m "feat: add server entry point with FastAPI + bot polling"
```

---

### Task 5: React Dashboard Scaffold

**Files:**
- Create: `dashboard/` with Vite + React + TypeScript + Tailwind

- [ ] **Step 1: Scaffold the project**

Run:
```bash
cd G:/projects/SWE-Jobs && npm create vite@latest dashboard -- --template react-ts
cd G:/projects/SWE-Jobs/dashboard && npm install
npm install -D tailwindcss @tailwindcss/vite
npm install react-router-dom recharts @supabase/supabase-js
```

- [ ] **Step 2: Configure Tailwind**

Update `dashboard/vite.config.ts`:
```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/SWE-Jobs/',  // GitHub Pages base path
})
```

Replace `dashboard/src/index.css`:
```css
@import "tailwindcss";
```

- [ ] **Step 3: Commit scaffold**

```bash
git add dashboard/
git commit -m "feat: scaffold React dashboard with Vite, TypeScript, Tailwind"
```

---

### Task 6: Dashboard Types and API Client

**Files:**
- Create: `dashboard/src/types.ts`
- Create: `dashboard/src/api.ts`

- [ ] **Step 1: Write types.ts**

```typescript
// dashboard/src/types.ts

export interface Job {
  id: number;
  title: string;
  company: string;
  location: string;
  url: string;
  source: string;
  original_source: string;
  salary_raw: string;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string;
  job_type: string;
  seniority: string;
  is_remote: boolean;
  country: string;
  tags: string[];
  topics: string[];
  created_at: string;
}

export interface JobSearchResponse {
  jobs: Job[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

export interface StatsSummary {
  jobs_today: number;
  jobs_week: number;
  jobs_total: number;
  by_source: { source: string; count: number }[];
  by_topic: { topic: string; count: number }[];
  top_companies: { company: string; count: number }[];
}

export interface SalaryStats {
  overall: {
    sample_size: number;
    avg_min: number;
    avg_max: number;
    lowest: number;
    highest: number;
    median_min: number;
  };
  by_seniority: {
    seniority: string;
    count: number;
    avg_min: number;
    avg_max: number;
  }[];
  filters: { role: string | null; country: string | null; seniority: string | null };
}

export interface TrendItem {
  skill: string;
  count: number;
  previous_count: number;
  change_percent: number;
}

export interface TrendsResponse {
  period: string;
  trends: TrendItem[];
}
```

- [ ] **Step 2: Write api.ts**

```typescript
// dashboard/src/api.ts

import { createClient } from '@supabase/supabase-js';
import type { JobSearchResponse, StatsSummary, SalaryStats, TrendsResponse } from './types';

// Supabase client (read-only via anon key)
const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL || '';
const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY || '';
export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

// Custom API base (FastAPI on Render/Railway)
const API_BASE = import.meta.env.VITE_API_BASE || '';

async function fetchApi<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(`${API_BASE}${path}`);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v) url.searchParams.set(k, v);
    });
  }
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export const api = {
  searchJobs: (params: Record<string, string>) =>
    fetchApi<JobSearchResponse>('/api/jobs/search', params),

  getStatsSummary: () =>
    fetchApi<StatsSummary>('/api/stats/summary'),

  getSalaryStats: (params: Record<string, string>) =>
    fetchApi<SalaryStats>('/api/stats/salary', params),

  getTrends: (period: string = '7d') =>
    fetchApi<TrendsResponse>('/api/stats/trends', { period }),
};
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/types.ts dashboard/src/api.ts
git commit -m "feat: add TypeScript types and API client for dashboard"
```

---

### Task 7: Dashboard Components and Pages

**Files:**
- Create: `dashboard/src/components/Layout.tsx`
- Create: `dashboard/src/components/JobCard.tsx`
- Create: `dashboard/src/components/FilterBar.tsx`
- Create: `dashboard/src/pages/Home.tsx`
- Create: `dashboard/src/pages/Stats.tsx`
- Create: `dashboard/src/pages/Salary.tsx`
- Create: `dashboard/src/pages/Trends.tsx`
- Modify: `dashboard/src/App.tsx`
- Modify: `dashboard/src/main.tsx`

This is a large task. The implementation agent should build each component one at a time, verifying the dev server compiles after each. The components follow standard React patterns — the spec and types.ts define the data shape, the agent builds the UI.

Key guidelines for the implementation agent:
- Use Tailwind utility classes only
- Use Recharts for all charts (BarChart, PieChart, LineChart)
- Each page fetches its own data via `api.ts` on mount
- FilterBar uses URL search params for state (shareable filter URLs)
- JobCard shows: emoji, title, company, location, salary (if available), seniority badge, remote badge, source, apply link
- Layout has a top nav with links to Home, Stats, Salary, Trends

- [ ] **Step 1: Write Layout.tsx**

```typescript
// dashboard/src/components/Layout.tsx
import { Link, Outlet, useLocation } from 'react-router-dom';

const NAV_ITEMS = [
  { path: '/', label: 'Jobs' },
  { path: '/stats', label: 'Stats' },
  { path: '/salary', label: 'Salary' },
  { path: '/trends', label: 'Trends' },
];

export default function Layout() {
  const location = useLocation();
  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white border-b border-gray-200 px-4 py-3">
        <div className="max-w-6xl mx-auto flex items-center gap-6">
          <span className="text-lg font-bold text-gray-900">SWE Jobs</span>
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={`text-sm ${
                location.pathname === item.path
                  ? 'text-blue-600 font-medium'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              {item.label}
            </Link>
          ))}
        </div>
      </nav>
      <main className="max-w-6xl mx-auto p-4">
        <Outlet />
      </main>
    </div>
  );
}
```

- [ ] **Step 2: Write JobCard.tsx**

```typescript
// dashboard/src/components/JobCard.tsx
import type { Job } from '../types';

const SENIORITY_COLORS: Record<string, string> = {
  intern: 'bg-purple-100 text-purple-700',
  junior: 'bg-green-100 text-green-700',
  mid: 'bg-blue-100 text-blue-700',
  senior: 'bg-orange-100 text-orange-700',
  lead: 'bg-red-100 text-red-700',
  executive: 'bg-gray-800 text-white',
};

export default function JobCard({ job }: { job: Job }) {
  const salaryDisplay = job.salary_min && job.salary_max
    ? `${job.salary_currency || '$'}${job.salary_min.toLocaleString()} - ${job.salary_max.toLocaleString()}`
    : job.salary_raw || null;

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md transition-shadow">
      <div className="flex justify-between items-start">
        <div className="flex-1">
          <h3 className="font-semibold text-gray-900">{job.title}</h3>
          <p className="text-sm text-gray-600">{job.company || 'Unknown'}</p>
        </div>
        <span className={`text-xs px-2 py-1 rounded-full ${SENIORITY_COLORS[job.seniority] || SENIORITY_COLORS.mid}`}>
          {job.seniority}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-xs text-gray-500">
        <span>📍 {job.location || 'Not specified'}</span>
        {job.is_remote && <span className="text-green-600">🌍 Remote</span>}
        {salaryDisplay && <span className="text-green-700 font-medium">💰 {salaryDisplay}</span>}
        <span>📡 {job.original_source || job.source}</span>
      </div>
      {job.tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {job.tags.slice(0, 5).map((tag) => (
            <span key={tag} className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">
              {tag}
            </span>
          ))}
        </div>
      )}
      <div className="mt-3">
        <a
          href={job.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm text-blue-600 hover:text-blue-800 font-medium"
        >
          Apply →
        </a>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Write FilterBar.tsx, Home.tsx, Stats.tsx, Salary.tsx, Trends.tsx**

These follow the same patterns. The implementation agent should build each page using the types and API client. Key points:
- **Home.tsx**: fetches via `api.searchJobs()`, renders `FilterBar` + list of `JobCard`, pagination buttons
- **Stats.tsx**: fetches `api.getStatsSummary()`, renders stat cards (today/week/total) + Recharts BarChart (by source) + PieChart (by topic) + company list
- **Salary.tsx**: fetches `api.getSalaryStats()`, renders filter dropdowns + Recharts BarChart (avg salary by seniority)
- **Trends.tsx**: fetches `api.getTrends()`, renders Recharts BarChart with green/red bars for positive/negative change

- [ ] **Step 4: Write App.tsx with routes**

```typescript
// dashboard/src/App.tsx
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Home from './pages/Home';
import Stats from './pages/Stats';
import Salary from './pages/Salary';
import Trends from './pages/Trends';

export default function App() {
  return (
    <BrowserRouter basename="/SWE-Jobs">
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Home />} />
          <Route path="/stats" element={<Stats />} />
          <Route path="/salary" element={<Salary />} />
          <Route path="/trends" element={<Trends />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
```

- [ ] **Step 5: Verify build**

Run: `cd G:/projects/SWE-Jobs/dashboard && npm run build`
Expected: Build succeeds with no TypeScript errors

- [ ] **Step 6: Commit**

```bash
git add dashboard/
git commit -m "feat: add dashboard pages (home, stats, salary, trends) with components"
```

---

### Task 8: GitHub Pages Deployment Workflow

**Files:**
- Create: `.github/workflows/deploy_dashboard.yml`

- [ ] **Step 1: Write the workflow**

```yaml
# .github/workflows/deploy_dashboard.yml
name: Deploy Dashboard to GitHub Pages

on:
  push:
    branches: [main]
    paths: ['dashboard/**']
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}

    steps:
      - uses: actions/checkout@v4

      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
          cache-dependency-path: dashboard/package-lock.json

      - name: Install dependencies
        run: cd dashboard && npm ci

      - name: Build
        run: cd dashboard && npm run build
        env:
          VITE_SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          VITE_SUPABASE_ANON_KEY: ${{ secrets.SUPABASE_ANON_KEY }}
          VITE_API_BASE: ${{ secrets.API_BASE_URL }}

      - name: Setup Pages
        uses: actions/configure-pages@v4

      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: dashboard/dist

      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/deploy_dashboard.yml
git commit -m "feat: add GitHub Pages deployment workflow for dashboard"
```

---

### Task 9: Final Verification

- [ ] **Step 1: Verify API imports**

Run:
```bash
cd G:/projects/SWE-Jobs && python -c "
from api.app import create_app
app = create_app()
print(f'Routes: {[r.path for r in app.routes]}')
print('API OK')
"
```
Expected: Lists routes including `/api/jobs/search`, `/api/stats/summary`, etc.

- [ ] **Step 2: Verify dashboard builds**

Run: `cd G:/projects/SWE-Jobs/dashboard && npm run build`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat: complete Plan 5 — web dashboard and FastAPI endpoints"
```

---

## Summary

After completing this plan:

- **FastAPI backend** with rate-limited endpoints for search, stats, salary, and trends
- **React dashboard** with 4 pages: job feed, statistics, salary insights, skill trends
- **Supabase integration** — dashboard reads directly from PostgREST for simple queries
- **GitHub Pages deployment** — automatic on push to main
- **Server entry point** — FastAPI + bot polling in single process

**Next:** Plan 6 (Migration & Integration) wires everything together.
