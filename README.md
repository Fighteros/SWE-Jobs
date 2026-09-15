# SWE-Jobs v2

A production-grade job aggregation platform that collects software engineering and tech roles from **30+ sources**, enriches them with salary, seniority, and location data, and delivers them through **21 specialized Telegram topics** plus personalized DM alerts. The stack runs self-hosted via Docker Compose with a FastAPI backend, React dashboard, and supervised Telegram bot polling.

## Features

- **30+ job sources** — remote boards, regional boards, ATS job boards, and social/job-network scrapers
- **21 Telegram topics** — tech roles, geo-specific channels, and non-tech business roles
- **Smart routing** — each job is auto-routed to all matching topics
- **Weighted keyword filtering** — include/exclude keyword scoring with configurable threshold
- **Geo-intelligence** — Egypt & Saudi Arabia get all local jobs; rest of world gets remote-only
- **Fuzzy deduplication** — PostgreSQL `pg_trgm` similarity catches near-duplicates
- **Circuit breaker** — per-source retry, 3-strike circuit open, DB-persisted state
- **Salary & seniority enrichment** — free-text salary extraction and role-level classification
- **Personalized DM alerts** — subscribers get notified based on topics, seniority, keywords, sources, location, and salary
- **Interactive Telegram bot** — search, subscribe, save, apply tracking, streaks, blacklist, salary insights, and support
- **Web dashboard** — React + Vite + Tailwind + Recharts with search, stats, salary, and trends
- **REST API** — FastAPI backend with rate limiting and full-text search
- **Self-hosted deployment** — Docker Compose stack with private PostgreSQL
- **Admin monitoring** — zero-job alerts, slow-run alerts, circuit-breaker health, daily digest, support messages, broadcast

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Docker Compose host (VPS)                                  │
│                                                             │
│  ┌─────────────┐   ┌───────────────────────────────────┐   │
│  │ PostgreSQL  │   │  backend service (server.py)      │   │
│  │   (db)      │◄──┤  ├── FastAPI /api                 │   │
│  └─────────────┘   │  ├── Telegram polling supervisor   │   │
│         ▲          │  └── Scheduled fetch loop (5 min)  │   │
│         │          └───────────────────────────────────┘   │
│         │                          │                        │
│         │                          ▼                        │
│         │          ┌───────────────────────────────┐        │
│         └──────────┤  main.py pipeline             │        │
│                    │  fetch → enrich → filter      │        │
│                    │  → dedup → insert → send      │        │
│                    │  → notify → track → monitor   │        │
│                    └───────────────────────────────┘        │
│                                    │                        │
│                                    ▼                        │
│                           Telegram group/topics             │
│                           + subscriber DMs                  │
└─────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                           React dashboard (optional)
                           talks to FastAPI /api
```

## Sources

Sources that require API keys are skipped silently if the key is absent.

### Remote / Global Boards

| # | Source | Type | Coverage |
|---|--------|------|----------|
| 1 | Remotive | API | Remote worldwide |
| 2 | Himalayas | API | Remote worldwide |
| 3 | Jobicy | API | Remote worldwide |
| 4 | RemoteOK | JSON Feed | Remote worldwide |
| 5 | Arbeitnow | API | Europe + Remote |
| 6 | We Work Remotely | RSS (5 feeds) | Remote worldwide |
| 7 | Working Nomads | API/RSS | Remote worldwide |
| 8 | Findwork.dev | API | Software dev remote |
| 9 | DevITjobs | API | Remote dev/IT |

### Aggregators / Job Networks

| # | Source | Type | Coverage |
|---|--------|------|----------|
| 10 | JSearch / RapidAPI | API | LinkedIn + Indeed + Glassdoor |
| 11 | LinkedIn | Guest API | Egypt + Saudi + Remote worldwide |
| 12 | LinkedIn Posts | Playwright scraper | Hiring posts (cookies required) |
| 13 | Indeed | Playwright scraper | Multi-country |
| 14 | Glassdoor | Playwright scraper | Multi-country |
| 15 | X (Twitter) | API/scraper | Hiring posts (cookies/token required) |

### Regional / Country-Specific

| # | Source | Type | Coverage |
|---|--------|------|----------|
| 16 | Adzuna | API | GB, US, DE, etc. |
| 17 | Jooble | API | Egypt + Saudi + Remote |
| 18 | Reed.co.uk | API | UK + Remote |
| 19 | USAJobs | API | US Government IT |
| 20 | Wuzzuf | Playwright scraper | Egypt |
| 21 | Bayt | Playwright scraper | Middle East |
| 22 | NaukriGulf | Playwright scraper | Gulf |
| 23 | Dubizzle | Playwright scraper | UAE |
| 24 | GulfTalent | Playwright scraper | Gulf |

### ATS Job Boards

| # | Source | Type | Coverage |
|---|--------|------|----------|
| 25 | Greenhouse | Board scraper | Companies on Greenhouse |
| 26 | Lever | Board scraper | Companies on Lever |
| 27 | Workable | Board scraper | Companies on Workable |
| 28 | Workable Jobs | Board scraper | Workable public job board |
| 29 | Recruitee | Board scraper | Companies on Recruitee |
| 30 | Ashby | Board scraper | Companies on Ashby |
| 31 | SmartRecruiters | Board scraper | Companies on SmartRecruiters |
| 32 | The Muse | API | Software Engineering |

## Telegram Topics (21)

A job can be routed to multiple topics. Topic IDs are configured via environment variables.

| Topic | What goes there |
|-------|----------------|
| 💻 All Jobs | Everything |
| ⚙️ Backend | Backend, Full-Stack, API, Django, Node.js, Python, Java, Go, Rust |
| 🎨 Frontend | Frontend, React, Angular, Vue, TypeScript, CSS |
| 📱 Mobile | Flutter, React Native, iOS, Android, Swift, Kotlin |
| 🚀 DevOps & Cloud | DevOps, SRE, Kubernetes, Docker, AWS, Azure, GCP |
| 🧪 QA & Testing | QA, SDET, Selenium, Cypress, Playwright |
| 🤖 AI/ML & Data Science | ML Engineer, Data Scientist, NLP, LLM, Deep Learning |
| 🔒 Cybersecurity | Security, Penetration Testing, SOC, InfoSec |
| 🎮 Game Development | Unity, Unreal, Godot, Gameplay Programming |
| ⛓️ Blockchain & Web3 | Solidity, Smart Contracts, DeFi, Web3 |
| 🔄 Full Stack | Full-stack / fullstack roles |
| 🇪🇬 Egypt Jobs | All jobs located in Egypt |
| 🇸🇦 Saudi Jobs | All jobs located in Saudi Arabia |
| 🎓 Internships | Intern, Trainee, Entry Level, Fresh Grad |
| 🏢 ERP & Accounting | Odoo, SAP, Salesforce, Oracle, Dynamics, NetSuite |
| 📣 Marketing & Sales | Marketing, Growth, Sales, Business Development |
| 👥 HR & Recruiting | HR, People Ops, Recruiting, Talent Acquisition |
| 💰 Finance & Accounting | Finance, Accountant, Analyst, Bookkeeping |
| 🗂️ Admin & Operations | Admin, Operations, Logistics, Virtual Assistant |
| 🎧 Customer Support | Customer Support, Technical Support, Help Desk |
| 📋 Product & Project Mgmt | Product Manager, Project Manager, Scrum Master |

## Bot Commands

| Command | Description |
| :--- | :--- |
| `/start` | Welcome + deep-link subscription |
| `/subscribe` | Create a personalized DM alert |
| `/unsubscribe` | Remove an alert or all alerts |
| `/mysubs` | View/edit alerts and DM toggle |
| `/search <query>` | Search jobs from the last 14 days |
| `/saved` | View bookmarked jobs |
| `/applied` | View application history |
| `/streak` | Check daily application streak |
| `/blacklist` | Block companies or keywords |
| `/stats` | Bot and job statistics |
| `/top` | Top jobs this week by engagement |
| `/salary <role>` | Egyptian salary insights via egytech.fyi |
| `/status` | Source/circuit-breaker health |
| `/contact` | Send feedback to the admin |
| `/help` | Show command reference |

**Admin only:** `/messages`, `/broadcast`

## Quick Start

### Self-Hosted (Recommended)

Requires a Linux VPS with Docker. See [docs/SELF_HOSTING.md](docs/SELF_HOSTING.md) for the full guide.

```bash
git clone https://github.com/YOUR_USERNAME/SWE-Jobs.git
cd SWE-Jobs

# Create .env from the example and fill in your credentials
cp .env.example .env
# Edit .env (database, Telegram token, topic IDs, API keys)

# Build and start the stack
docker compose up -d --build
```

On first boot, the custom PostgreSQL image applies every migration in `supabase/migrations/` automatically. The backend service runs FastAPI on port `8000` and the scheduled fetch loop alongside supervised Telegram bot polling.

### Local Development

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Install Playwright browsers if you use scrapers
playwright install chromium

# Configure environment
cp .env.example .env
# Edit .env

# Run migrations against your database
# (e.g. psql -h localhost -U postgres -d postgres -f supabase/migrations/001_init.sql)

# Run the full backend (API + bot + scheduler)
python server.py

# Or run a one-off pipeline
python main.py
```

### Dashboard (optional)

```bash
cd dashboard
npm install
npm run dev     # http://localhost:5173
```

The dashboard talks to the FastAPI backend. Set `VITE_API_BASE` to point at it.

## Project Structure

```
SWE-Jobs/
├── main.py                     # One-off pipeline entry point
├── server.py                   # FastAPI + bot polling + scheduler
├── requirements.txt            # Python dependencies
├── requirements-dev.txt        # Dev/test dependencies
├── .env.example                # Environment variable template
├── USER_GUIDE.md               # End-user Telegram guide
├── docker-compose.yml          # Self-hosted stack
├── Dockerfile                  # Backend container
│
├── core/                       # Core business logic
│   ├── config.py               # Environment & settings
│   ├── models.py               # Job dataclass
│   ├── keywords.py             # Include/exclude keyword lists
│   ├── channels.py             # 21 topic definitions + routing
│   ├── geo.py                  # Geo-filter rules
│   ├── db.py                   # PostgreSQL sync access layer
│   ├── db_async.py             # Async PostgreSQL access layer
│   ├── filtering.py            # Keyword scoring + geo-filter
│   ├── enrichment.py           # Salary, seniority, country, topics
│   ├── dedup.py                # URL exact + fuzzy deduplication
│   ├── seniority.py            # Seniority level detection
│   ├── country_detector.py     # Location -> country code
│   ├── circuit_breaker.py      # Per-source retry + circuit breaker
│   ├── monitoring.py           # Alerts + daily digest
│   ├── egytech.py              # egytech.fyi salary client
│   ├── egytech_mapping.py      # Role mapping for egytech.fyi
│   └── logging_config.py       # Structured JSON logging
│
├── sources/                    # Job source fetchers (30+)
│   ├── __init__.py             # ALL_FETCHERS registry
│   ├── http_utils.py           # Shared HTTP helpers
│   ├── playwright_utils.py     # Shared Playwright helpers
│   ├── remotive.py             # Remotive API
│   ├── himalayas.py            # Himalayas API
│   ├── jobicy.py               # Jobicy API
│   ├── remoteok.py             # RemoteOK JSON Feed
│   ├── arbeitnow.py            # Arbeitnow API
│   ├── wwr.py                  # We Work Remotely RSS
│   ├── workingnomads.py        # Working Nomads API/RSS
│   ├── jsearch.py              # JSearch/RapidAPI
│   ├── linkedin.py             # LinkedIn Guest API
│   ├── linkedin_posts.py       # LinkedIn hiring posts scraper
│   ├── adzuna.py               # Adzuna API
│   ├── themuse.py              # The Muse API
│   ├── findwork.py             # Findwork.dev API
│   ├── jooble.py               # Jooble API
│   ├── reed.py                 # Reed.co.uk API
│   ├── usajobs.py              # USAJobs API
│   ├── devitjobs.py            # DevITjobs API
│   ├── greenhouse.py           # Greenhouse board scraper
│   ├── lever.py                # Lever board scraper
│   ├── workable.py             # Workable board scraper
│   ├── workable_jobs.py        # Workable public jobs board
│   ├── recruitee.py            # Recruitee board scraper
│   ├── ashby.py                # Ashby board scraper
│   ├── smartrecruiters.py      # SmartRecruiters board scraper
│   ├── wuzzuf.py               # Wuzzuf scraper
│   ├── glassdoor.py            # Glassdoor scraper
│   ├── bayt.py                 # Bayt scraper
│   ├── naukrigulf.py           # NaukriGulf scraper
│   ├── dubizzle.py             # Dubizzle scraper
│   ├── gulftalent.py           # GulfTalent scraper
│   ├── x_jobs.py               # X/Twitter hiring posts
│   ├── indeed.py               # Indeed scraper
│   └── ...
│
├── bot/                        # Telegram bot
│   ├── app.py                  # Bot application setup
│   ├── polling.py              # Supervised polling + recovery
│   ├── commands.py             # Command handlers
│   ├── callbacks.py            # Inline button handlers
│   ├── keyboards.py            # Inline keyboard layouts
│   ├── sender.py               # Job formatting + multi-topic sending
│   └── notifications.py        # Personalized DM alerts
│
├── api/                        # REST API (FastAPI)
│   ├── app.py                  # App factory + CORS
│   ├── middleware.py           # Rate limiting
│   ├── routes_jobs.py          # /api/jobs/search
│   └── routes_stats.py         # /api/stats, /api/salary, /api/trends
│
├── dashboard/                  # Web frontend (React 19 + Vite + Tailwind)
│   └── src/
│       ├── pages/              # Home, Stats, Salary, Trends
│       ├── components/         # FilterBar, JobCard, Layout
│       ├── api.ts              # Backend client
│       └── types.ts            # TypeScript types
│
├── supabase/migrations/        # Database migrations
│   ├── 001_init.sql
│   ├── 002_applications_and_blacklist.sql
│   ├── 003_add_posted_at.sql
│   ├── 004_support_messages.sql
│   ├── 005_user_alerts.sql
│   └── 006_job_apply_fields.sql
│
├── tests/                      # Test suite
│   ├── test_models.py
│   ├── test_db.py
│   ├── test_filtering.py
│   ├── test_enrichment.py
│   ├── test_dedup.py
│   ├── test_seniority.py
│   ├── test_country_detector.py
│   ├── test_circuit_breaker.py
│   ├── test_notifications.py
│   ├── test_streak.py
│   ├── test_user_alerts.py
│   ├── test_egytech_*.py
│   └── ...
│
├── scripts/                    # Utility scripts
│
├── .github/workflows/
│   ├── job_bot.yml             # Disabled — one-off pipeline (manual only)
│   ├── deploy_backend.yml      # Auto-deploy backend on push
│   ├── deploy_dashboard.yml    # Dashboard → GitHub Pages
│   └── archive_jobs.yml        # Periodic job archival
│
└── docs/                       # Documentation
    ├── CONFIGURATION.md        # All environment variables
    ├── ARCHITECTURE.md         # System design deep-dive
    ├── ADDING_SOURCES.md       # Guide to adding new job sources
    ├── SELF_HOSTING.md         # VPS + Docker Compose guide
    └── CHANGELOG_V2.md         # V1 → V2 changes
```

## Configuration

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for all environment variables, API keys, Telegram setup, and topic configuration.

Key files:
- `.env.example` — copy to `.env` and fill in values
- `docker-compose.yml` — self-hosted stack
- `docs/SELF_HOSTING.md` — full VPS setup guide

## Documentation

| Document | Description |
|----------|-------------|
| [Configuration](docs/CONFIGURATION.md) | Environment variables, API keys, Telegram setup |
| [Architecture](docs/ARCHITECTURE.md) | System design, pipeline, database schema |
| [Adding Sources](docs/ADDING_SOURCES.md) | Step-by-step guide to add a new job source |
| [Self-Hosting](docs/SELF_HOSTING.md) | VPS + Docker Compose deployment |
| [User Guide](USER_GUIDE.md) | End-user Telegram bot guide |
| [Changelog V2](docs/CHANGELOG_V2.md) | What changed from v1 to v2 |

## Running Tests

```bash
python -m pytest tests/ -v
```

## License

MIT
