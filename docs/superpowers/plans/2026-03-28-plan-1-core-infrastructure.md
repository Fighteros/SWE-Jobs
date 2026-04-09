# Plan 1: Core Infrastructure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the JSON file storage with PostgreSQL (Supabase), restructure config into focused modules, and update the Job model with new fields — creating the foundation for all v2 features.

**Architecture:** Supabase PostgreSQL accessed via `psycopg2` through pgBouncer (port 6543). The existing `Job` dataclass gains new fields (salary_min, salary_max, seniority, country, etc.). Config splits into `core/config.py` (env vars), `core/keywords.py` (scoring), and `core/channels.py` (topics). The DB layer (`core/db.py`) provides simple functions for insert/query/update — no ORM.

**Tech Stack:** Python 3.11, psycopg2-binary, Supabase PostgreSQL, pytest

**Spec:** `docs/superpowers/specs/2026-03-28-v2-redesign-design.md` (Sections 1, 7)

**Depends on:** Nothing (this is the foundation)
**Blocks:** Plans 2-6

---

## File Structure

```
SWE-Jobs/
├── core/
│   ├── __init__.py          # Package init
│   ├── config.py            # Env vars, settings, timeouts (from old config.py)
│   ├── keywords.py          # INCLUDE_KEYWORDS, EXCLUDE_KEYWORDS, scoring weights
│   ├── channels.py          # CHANNELS dict, topic routing config, emoji map
│   ├── geo.py               # EGYPT_PATTERNS, SAUDI_PATTERNS, REMOTE_PATTERNS, ALLOWED_ONSITE_COUNTRIES
│   ├── db.py                # PostgreSQL connection pool + CRUD functions
│   └── models.py            # Updated Job dataclass + Pydantic models
├── supabase/
│   └── migrations/
│       └── 001_init.sql     # Full schema: jobs, users, user_saved_jobs, bot_runs, source_health, job_feedback + indexes + RLS
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # Shared fixtures (mock DB, sample jobs)
│   ├── test_models.py       # Job dataclass tests
│   └── test_db.py           # DB layer tests (mocked)
├── requirements.txt         # Updated with psycopg2-binary, python-dotenv (pydantic deferred to Plan 3)
└── .env.example             # Template for required env vars
```

**What stays unchanged:** `sources/` directory (all 15 fetchers), `sources/http_utils.py`. These will be updated in later plans to use the new models.

---

### Task 1: Create Supabase Migration SQL

**Files:**
- Create: `supabase/migrations/001_init.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- supabase/migrations/001_init.sql
-- SWE-Jobs v2 schema

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ─── Jobs ─────────────────────────────────────────────────
CREATE TABLE jobs (
    id              SERIAL PRIMARY KEY,
    unique_id       TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL,
    company         TEXT DEFAULT '',
    location        TEXT DEFAULT '',
    url             TEXT NOT NULL,
    source          TEXT NOT NULL,
    original_source TEXT DEFAULT '',
    salary_raw      TEXT DEFAULT '',
    salary_min      INTEGER,
    salary_max      INTEGER,
    salary_currency TEXT DEFAULT '',
    job_type        TEXT DEFAULT '',
    seniority       TEXT DEFAULT 'mid',
    is_remote       BOOLEAN DEFAULT FALSE,
    country         TEXT DEFAULT '',
    tags            TEXT[] DEFAULT '{}',
    topics          TEXT[] DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    sent_at         TIMESTAMPTZ,
    telegram_message_ids JSONB DEFAULT '{}'
);

-- Indexes
CREATE INDEX idx_jobs_title_trgm ON jobs USING GIN (title gin_trgm_ops);
CREATE INDEX idx_jobs_tags ON jobs USING GIN (tags);
CREATE INDEX idx_jobs_topics ON jobs USING GIN (topics);
CREATE INDEX idx_jobs_created_at ON jobs (created_at);
CREATE INDEX idx_jobs_source ON jobs (source);
CREATE INDEX idx_jobs_seniority ON jobs (seniority);
CREATE INDEX idx_jobs_salary_min ON jobs (salary_min);
CREATE INDEX idx_jobs_company_lower ON jobs (lower(company));

-- ─── Users ────────────────────────────────────────────────
CREATE TABLE users (
    id              SERIAL PRIMARY KEY,
    telegram_id     BIGINT UNIQUE NOT NULL,
    username        TEXT DEFAULT '',
    subscriptions   JSONB DEFAULT '{}',
    notify_dm       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ─── User Saved Jobs ──────────────────────────────────────
CREATE TABLE user_saved_jobs (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    job_id      INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    saved_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, job_id)
);

CREATE INDEX idx_user_saved_jobs_user ON user_saved_jobs (user_id);
CREATE INDEX idx_user_saved_jobs_job ON user_saved_jobs (job_id);

-- ─── Bot Runs ─────────────────────────────────────────────
CREATE TABLE bot_runs (
    id              SERIAL PRIMARY KEY,
    started_at      TIMESTAMPTZ DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    jobs_fetched    INTEGER DEFAULT 0,
    jobs_filtered   INTEGER DEFAULT 0,
    jobs_new        INTEGER DEFAULT 0,
    jobs_sent       INTEGER DEFAULT 0,
    source_stats    JSONB DEFAULT '{}',
    errors          JSONB DEFAULT '[]'
);

-- ─── Source Health ────────────────────────────────────────
CREATE TABLE source_health (
    source                  TEXT PRIMARY KEY,
    consecutive_failures    INTEGER DEFAULT 0,
    circuit_open_until      TIMESTAMPTZ,
    last_success_at         TIMESTAMPTZ,
    last_failure_at         TIMESTAMPTZ,
    last_error              TEXT DEFAULT ''
);

-- ─── Job Feedback ─────────────────────────────────────────
CREATE TABLE job_feedback (
    id              SERIAL PRIMARY KEY,
    job_id          INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
    feedback_type   TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_job_feedback_job ON job_feedback (job_id);
CREATE INDEX idx_job_feedback_user ON job_feedback (user_id);

-- ─── Row Level Security ──────────────────────────────────
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_saved_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE bot_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_health ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_feedback ENABLE ROW LEVEL SECURITY;

-- Anon (dashboard) can only read jobs
CREATE POLICY "anon_read_jobs" ON jobs
    FOR SELECT TO anon USING (true);

-- No anon access to users, user_saved_jobs, source_health, job_feedback
-- (RLS enabled + no policy = denied)

-- Public view for bot_runs (hides errors column which may contain sensitive data)
CREATE VIEW bot_runs_public AS
    SELECT id, started_at, finished_at, jobs_fetched, jobs_filtered,
           jobs_new, jobs_sent, source_stats
    FROM bot_runs;

-- Grant anon read on the public view
GRANT SELECT ON bot_runs_public TO anon;

-- Auto-update updated_at on jobs
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER jobs_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- ─── Jobs Archive ────────────────────────────────────────
-- Same schema as jobs but fewer indexes. Used for retention policy.
-- Jobs older than 7 days in active table are moved here weekly.
CREATE TABLE jobs_archive (
    id              INTEGER PRIMARY KEY,
    unique_id       TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL,
    company         TEXT DEFAULT '',
    location        TEXT DEFAULT '',
    url             TEXT NOT NULL,
    source          TEXT NOT NULL,
    original_source TEXT DEFAULT '',
    salary_raw      TEXT DEFAULT '',
    salary_min      INTEGER,
    salary_max      INTEGER,
    salary_currency TEXT DEFAULT '',
    job_type        TEXT DEFAULT '',
    seniority       TEXT DEFAULT 'mid',
    is_remote       BOOLEAN DEFAULT FALSE,
    country         TEXT DEFAULT '',
    tags            TEXT[] DEFAULT '{}',
    topics          TEXT[] DEFAULT '{}',
    created_at      TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ,
    sent_at         TIMESTAMPTZ,
    telegram_message_ids JSONB DEFAULT '{}'
);

-- Minimal indexes on archive (no expensive GIN/trgm indexes)
CREATE INDEX idx_jobs_archive_created_at ON jobs_archive (created_at);
CREATE INDEX idx_jobs_archive_unique_id ON jobs_archive (unique_id);
```

- [ ] **Step 2: Verify SQL syntax**

Run: `python -c "print('SQL file created successfully')" && wc -l supabase/migrations/001_init.sql`
Expected: File exists with ~120 lines

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/001_init.sql
git commit -m "feat: add v2 database schema migration"
```

---

### Task 2: Update requirements.txt and create .env.example

**Files:**
- Modify: `requirements.txt`
- Create: `.env.example`

- [ ] **Step 1: Update requirements.txt**

```
requests>=2.31.0
psycopg2-binary>=2.9.9
python-dotenv>=1.0.0
```

- [ ] **Step 2: Create .env.example**

```bash
# .env.example — Copy to .env and fill in values

# ─── Supabase PostgreSQL ───────────────────────────────────
SUPABASE_DB_HOST=db.xxxxxxxxxxxx.supabase.co
SUPABASE_DB_PORT=6543
SUPABASE_DB_NAME=postgres
SUPABASE_DB_USER=postgres
SUPABASE_DB_PASSWORD=your-db-password

# ─── Telegram ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_GROUP_ID=-100xxxxxxxxxx

# ─── Topic Thread IDs ─────────────────────────────────────
TOPIC_GENERAL=
TOPIC_BACKEND=
TOPIC_FRONTEND=
TOPIC_MOBILE=
TOPIC_DEVOPS=
TOPIC_QA=
TOPIC_AI_ML=
TOPIC_CYBERSECURITY=
TOPIC_GAMEDEV=
TOPIC_BLOCKCHAIN=
TOPIC_EGYPT=
TOPIC_SAUDI=
TOPIC_INTERNSHIPS=
TOPIC_ERP=

# ─── API Keys (optional — sources without keys are skipped) ─
RAPIDAPI_KEY=
ADZUNA_APP_ID=
ADZUNA_APP_KEY=
FINDWORK_API_KEY=
JOOBLE_API_KEY=
REED_API_KEY=
MUSE_API_KEY=

# ─── Admin ─────────────────────────────────────────────────
ADMIN_TELEGRAM_ID=
SEED_MODE=
```

- [ ] **Step 3: Add .env to .gitignore**

Create or append to `.gitignore`:
```
.env
__pycache__/
*.pyc
```

- [ ] **Step 4: Install dependencies locally**

Run: `pip install -r requirements.txt`
Expected: All packages install successfully

- [ ] **Step 5: Commit**

```bash
git add requirements.txt .env.example .gitignore
git commit -m "feat: add v2 dependencies and env template"
```

---

### Task 3: Create core/config.py — Environment Variables and Settings

**Files:**
- Create: `core/__init__.py`
- Create: `core/config.py`

- [ ] **Step 1: Create core package**

```python
# core/__init__.py
```

- [ ] **Step 2: Write core/config.py**

This file holds ONLY env vars and settings. Keywords, channels, and geo patterns move to their own files.

```python
"""
Environment variables and application settings.
All configuration that comes from env vars lives here.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── Supabase PostgreSQL ──────────────────────────────────
SUPABASE_DB_HOST = os.getenv("SUPABASE_DB_HOST", "")
SUPABASE_DB_PORT = int(os.getenv("SUPABASE_DB_PORT", "6543"))
SUPABASE_DB_NAME = os.getenv("SUPABASE_DB_NAME", "postgres")
SUPABASE_DB_USER = os.getenv("SUPABASE_DB_USER", "postgres")
SUPABASE_DB_PASSWORD = os.getenv("SUPABASE_DB_PASSWORD", "")

# ─── Telegram ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_GROUP_ID = os.getenv("TELEGRAM_GROUP_ID", "")
TELEGRAM_SEND_DELAY = 3  # seconds between messages

# ─── API Keys ─────────────────────────────────────────────
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")
FINDWORK_API_KEY = os.getenv("FINDWORK_API_KEY", "")
JOOBLE_API_KEY = os.getenv("JOOBLE_API_KEY", "")
REED_API_KEY = os.getenv("REED_API_KEY", "")
MUSE_API_KEY = os.getenv("MUSE_API_KEY", "")

# ─── Admin ────────────────────────────────────────────────
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID", "")

# ─── Misc Settings ────────────────────────────────────────
MAX_JOBS_PER_RUN = 50
REQUEST_TIMEOUT = 15  # seconds
SEED_MODE_ENV = "SEED_MODE"
SEEN_JOBS_FILE = "seen_jobs.json"  # Legacy, kept for migration
```

- [ ] **Step 3: Commit**

```bash
git add core/__init__.py core/config.py
git commit -m "feat: add core/config.py with env vars and settings"
```

---

### Task 4: Create core/keywords.py — Keyword Lists and Scoring Weights

**Files:**
- Create: `core/keywords.py`

- [ ] **Step 1: Write core/keywords.py**

Move `INCLUDE_KEYWORDS` and `EXCLUDE_KEYWORDS` from the old `config.py`. Add scoring weight constants.

```python
"""
Keyword lists for job filtering and scoring weights.
"""

# ─── Scoring Weights ──────────────────────────────────────
SCORE_EXACT_WORD = 10   # Whole word match in title (regex \b)
SCORE_TAG_MATCH = 8     # Exact match in tags array
SCORE_PARTIAL = 3       # Substring match (no word boundary)
SCORE_EXCLUDE = -20     # Exclude keyword found (instant reject)
SCORE_THRESHOLD = 10    # Minimum score to pass

# ─── Include Keywords ─────────────────────────────────────
# Job MUST score >= SCORE_THRESHOLD using these keywords
# Checked against title (word boundary) and tags (exact match)
INCLUDE_KEYWORDS = [
    # Software Engineering
    "software engineer", "software developer", "software development",
    "swe", "sde",
    # Backend
    "backend", "back-end", "back end",
    "server-side", "server side",
    "api developer", "api engineer",
    # Frontend
    "frontend", "front-end", "front end",
    "ui developer", "ui engineer",
    # Full-Stack
    "full-stack", "full stack", "fullstack",
    # DevOps / SRE / Cloud / Infra
    "devops", "dev ops", "dev-ops",
    "sre", "site reliability",
    "cloud engineer", "cloud developer", "cloud architect",
    "infrastructure engineer", "platform engineer",
    "kubernetes", "docker", "terraform",
    "aws engineer", "azure engineer", "gcp engineer",
    # QA / Testing
    "qa engineer", "qa developer", "quality assurance",
    "test engineer", "sdet", "software tester",
    "automation engineer", "test automation",
    "qa analyst", "qa lead", "qa manager",
    # Mobile
    "mobile developer", "mobile engineer", "mobile application",
    "ios developer", "ios engineer",
    "android developer", "android engineer",
    "flutter developer", "flutter engineer", "flutter",
    "react native developer", "react native engineer", "react native",
    "swift developer", "kotlin developer",
    "mobile app developer", "app developer",
    # Web Development
    "web developer", "web engineer", "webmaster",
    # AI / ML / Data Science
    "machine learning", "ml engineer", "ml developer",
    "ai engineer", "ai developer", "artificial intelligence",
    "deep learning", "nlp engineer", "computer vision",
    "data scientist", "data science",
    "data analyst", "data analytics",
    "data engineer", "etl developer", "data pipeline",
    "big data", "hadoop", "spark engineer",
    # Cybersecurity
    "security engineer", "appsec", "application security",
    "cybersecurity", "cyber security", "infosec",
    "penetration tester", "pen tester", "security analyst",
    "soc analyst", "security architect",
    # Database
    "database administrator", "dba",
    "database developer", "database engineer",
    "sql developer", "postgresql", "mongodb",
    # Blockchain / Web3
    "blockchain developer", "blockchain engineer",
    "smart contract", "solidity developer",
    "web3 developer", "web3 engineer",
    "crypto developer",
    # Game Development
    "game developer", "game engineer", "game programmer",
    "unity developer", "unreal developer",
    "game designer",
    # Embedded / IoT
    "embedded developer", "embedded engineer", "embedded software",
    "iot developer", "iot engineer",
    "firmware developer", "firmware engineer",
    # Systems / Low-level
    "systems engineer", "systems developer",
    "systems programmer", "kernel developer",
    "linux engineer", "os developer",
    # ERP / CRM
    "salesforce developer", "sap developer", "sap engineer",
    "erp developer", "crm developer",
    "dynamics developer", "odoo developer",
    "erp consultant", "erp engineer",
    "odoo engineer", "odoo consultant", "odoo",
    "sap consultant", "sap abap", "sap fiori", "sap hana", "sap basis",
    "salesforce engineer", "salesforce admin", "salesforce consultant",
    "dynamics consultant", "dynamics 365",
    "oracle developer", "oracle ebs", "oracle apps", "oracle dba",
    "netsuite developer", "netsuite consultant",
    "quickbooks developer",
    "crm engineer",
    "accounting software", "financial software",
    # Networking
    "network engineer", "network administrator",
    "network architect",
    # Programming Languages (as job titles)
    "python developer", "python engineer",
    "java developer", "java engineer",
    "javascript developer", "js developer",
    "typescript developer", "ts developer",
    "golang developer", "go developer", "go engineer",
    "rust developer", "rust engineer",
    "ruby developer", "ruby engineer", "rails developer",
    "php developer", "php engineer",
    "c# developer", ".net developer", "dotnet developer",
    "c++ developer", "cpp developer",
    "scala developer", "elixir developer",
    "perl developer", "r developer",
    # Frameworks (as job titles)
    "node.js developer", "nodejs developer", "node developer",
    "react developer", "react engineer", "next.js developer",
    "angular developer", "vue developer", "vue.js developer",
    "django developer", "flask developer", "fastapi",
    "spring developer", "spring boot",
    "laravel developer", "symfony developer",
    "express.js developer",
    # CMS / WordPress
    "wordpress developer", "shopify developer",
    "drupal developer", "magento developer",
    # Technical Leadership
    "tech lead", "technical lead", "engineering manager",
    "cto", "vp engineering", "head of engineering",
    "principal engineer", "staff engineer", "architect",
    # Teaching / Tutoring
    "coding instructor", "programming instructor",
    "coding tutor", "programming tutor",
    "coding teacher", "programming teacher",
    "bootcamp instructor", "technical instructor",
    "computer science instructor", "cs instructor",
    "technical trainer", "coding mentor",
    # Internships / Entry Level
    "intern", "internship", "trainee",
    "graduate program", "training program",
    "co-op", "apprentice", "apprenticeship",
    "working student", "student developer",
    # General (broad catch — filtered by EXCLUDE)
    "programmer", "developer", "engineer",
]

# ─── Exclude Keywords ─────────────────────────────────────
# Job is EXCLUDED if it contains any of these (instant reject)
EXCLUDE_KEYWORDS = [
    # Non-programming roles
    "graphic design", "ui/ux design", "ux design", "ux researcher",
    "product design", "visual design", "brand design", "interior design",
    "marketing", "sales", "account manager", "account executive",
    "recruiter", "talent acquisition", "hr manager", "human resources",
    "customer support", "customer service", "customer success",
    "content writer", "copywriter",
    "project manager", "program manager", "scrum master",
    "product manager", "product owner",
    "business analyst", "business development",
    "financial analyst", "accountant", "bookkeeper",
    "office manager", "administrative",
    "data entry", "virtual assistant",
    "social media manager", "community manager",
    "supply chain", "logistics",
    # Hardware / Non-software engineering
    "mechanical engineer", "electrical engineer", "civil engineer",
    "chemical engineer", "structural engineer",
    "hardware engineer", "pcb",
    # Medical / Other
    "medical coder", "billing coder", "clinical",
    "nurse", "physician", "pharmacist",
    "dental", "veterinary",
]
```

- [ ] **Step 2: Commit**

```bash
git add core/keywords.py
git commit -m "feat: add core/keywords.py with scoring weights and keyword lists"
```

---

### Task 5: Create core/channels.py — Topic Routing Config

**Files:**
- Create: `core/channels.py`

- [ ] **Step 1: Write core/channels.py**

Move `CHANNELS`, `EMOJI_MAP`, `SOURCE_DISPLAY`, and `get_topic_thread_id` from old `config.py`.

```python
"""
Telegram community topic definitions, emoji map, and source display names.
"""

import os

# ─── Community Topics ─────────────────────────────────────
CHANNELS = {
    "general": {
        "thread_env": "TOPIC_GENERAL",
        "name": "💻 All Jobs",
        "match": "ALL",
    },
    "backend": {
        "thread_env": "TOPIC_BACKEND",
        "name": "⚙️ Backend",
        "keywords": [
            "backend", "back-end", "back end", "server-side", "server side",
            "api developer", "api engineer",
            "full-stack", "full stack", "fullstack",
            "python developer", "python engineer",
            "java developer", "java engineer",
            "golang", "go developer", "go engineer",
            "rust developer", "rust engineer",
            "ruby developer", "rails developer",
            "php developer", "php engineer",
            "node.js developer", "nodejs developer", "node developer",
            "django", "flask", "fastapi", "spring", "laravel", "express",
            ".net developer", "dotnet developer", "c# developer",
        ],
    },
    "frontend": {
        "thread_env": "TOPIC_FRONTEND",
        "name": "🎨 Frontend",
        "keywords": [
            "frontend", "front-end", "front end",
            "ui developer", "ui engineer",
            "full-stack", "full stack", "fullstack",
            "react developer", "react engineer", "next.js",
            "angular developer", "vue developer", "vue.js",
            "javascript developer", "js developer",
            "typescript developer", "ts developer",
            "css", "tailwind", "svelte",
            "web developer", "web engineer",
        ],
    },
    "mobile": {
        "thread_env": "TOPIC_MOBILE",
        "name": "📱 Mobile",
        "keywords": [
            "mobile developer", "mobile engineer", "mobile application",
            "ios developer", "ios engineer",
            "android developer", "android engineer",
            "flutter developer", "flutter engineer", "flutter",
            "react native developer", "react native engineer", "react native",
            "swift developer", "kotlin developer",
            "mobile app developer", "app developer",
            "swiftui", "jetpack compose", "dart developer",
        ],
    },
    "devops": {
        "thread_env": "TOPIC_DEVOPS",
        "name": "🚀 DevOps & Cloud",
        "keywords": [
            "devops", "dev ops", "dev-ops",
            "sre", "site reliability",
            "cloud engineer", "cloud developer", "cloud architect",
            "infrastructure engineer", "platform engineer",
            "kubernetes", "docker", "terraform", "ansible",
            "aws engineer", "azure engineer", "gcp engineer",
            "ci/cd", "jenkins", "github actions",
            "linux engineer", "systems engineer", "systems administrator",
            "network engineer", "network administrator",
        ],
    },
    "qa": {
        "thread_env": "TOPIC_QA",
        "name": "🧪 QA & Testing",
        "keywords": [
            "qa engineer", "qa developer", "quality assurance",
            "test engineer", "sdet", "software tester",
            "automation engineer", "test automation",
            "qa analyst", "qa lead", "qa manager",
            "selenium", "cypress", "playwright",
            "manual testing", "performance testing",
            "load testing", "stress testing",
        ],
    },
    "ai_ml": {
        "thread_env": "TOPIC_AI_ML",
        "name": "🤖 AI/ML & Data Science",
        "keywords": [
            "machine learning", "ml engineer", "ml developer",
            "ai engineer", "ai developer", "artificial intelligence",
            "deep learning", "nlp engineer", "computer vision",
            "data scientist", "data science",
            "data analyst", "data analytics",
            "data engineer", "etl developer", "data pipeline",
            "big data", "hadoop", "spark engineer",
            "llm", "generative ai", "prompt engineer",
            "tensorflow", "pytorch", "hugging face",
        ],
    },
    "cybersecurity": {
        "thread_env": "TOPIC_CYBERSECURITY",
        "name": "🔒 Cybersecurity",
        "keywords": [
            "security engineer", "appsec", "application security",
            "cybersecurity", "cyber security", "infosec",
            "penetration tester", "pen tester", "security analyst",
            "soc analyst", "security architect",
            "vulnerability", "ethical hacker",
            "security operations", "threat",
        ],
    },
    "gamedev": {
        "thread_env": "TOPIC_GAMEDEV",
        "name": "🎮 Game Development",
        "keywords": [
            "game developer", "game engineer", "game programmer",
            "unity developer", "unreal developer",
            "game designer", "gameplay programmer",
            "game studio", "gaming",
            "godot", "cocos2d",
        ],
    },
    "blockchain": {
        "thread_env": "TOPIC_BLOCKCHAIN",
        "name": "⛓️ Blockchain & Web3",
        "keywords": [
            "blockchain developer", "blockchain engineer",
            "smart contract", "solidity developer", "solidity",
            "web3 developer", "web3 engineer", "web3",
            "crypto developer", "defi", "nft",
            "ethereum", "solana developer",
        ],
    },
    "egypt": {
        "thread_env": "TOPIC_EGYPT",
        "name": "🇪🇬 Egypt Jobs",
        "match": "GEO_EGYPT",
    },
    "saudi": {
        "thread_env": "TOPIC_SAUDI",
        "name": "🇸🇦 Saudi Jobs",
        "match": "GEO_SAUDI",
    },
    "internships": {
        "thread_env": "TOPIC_INTERNSHIPS",
        "name": "🎓 Internships",
        "keywords": [
            "intern", "internship", "trainee", "training program",
            "graduate program", "junior", "entry level", "entry-level",
            "fresh graduate", "fresh grad", "co-op",
            "apprentice", "apprenticeship",
            "working student", "student developer",
        ],
    },
    "erp": {
        "thread_env": "TOPIC_ERP",
        "name": "🏢 ERP & Accounting",
        "keywords": [
            "erp developer", "erp consultant", "erp engineer", "erp implementation",
            "odoo developer", "odoo engineer", "odoo consultant", "odoo implementation",
            "sap developer", "sap consultant", "sap engineer", "sap abap",
            "sap fiori", "sap hana", "sap basis", "sap functional",
            "salesforce developer", "salesforce engineer", "salesforce admin",
            "salesforce consultant",
            "dynamics developer", "dynamics consultant", "dynamics 365",
            "oracle ebs", "oracle apps", "oracle financials",
            "netsuite developer", "netsuite consultant", "netsuite admin",
            "quickbooks developer",
            "accounting software", "financial software",
            "crm developer", "crm consultant",
        ],
    },
}


def get_topic_thread_id(channel_key: str) -> int | None:
    """Get the topic thread_id from environment variable."""
    ch = CHANNELS.get(channel_key, {})
    env_var = ch.get("thread_env", "")
    val = os.getenv(env_var, "")
    if val:
        try:
            return int(val)
        except ValueError:
            return None
    return None


# ─── Emoji Map ────────────────────────────────────────────
EMOJI_MAP = {
    "backend": "⚙️", "back-end": "⚙️",
    "frontend": "🎨", "front-end": "🎨",
    "full-stack": "🔄", "fullstack": "🔄",
    "devops": "🚀", "sre": "🚀", "cloud": "☁️", "aws": "☁️", "azure": "☁️",
    "qa": "🧪", "test": "🧪", "quality": "🧪",
    "mobile": "📱", "ios": "🍎", "android": "🤖",
    "flutter": "🦋", "react native": "📱",
    "python": "🐍", "java": "☕",
    "javascript": "🟨", "typescript": "🔷",
    "react": "⚛️", "node": "🟩",
    "golang": "🐹", "rust": "🦀", "ruby": "💎", "php": "🐘",
    ".net": "🟣", "c#": "🟣", "c++": "🔵",
    "swift": "🍎", "kotlin": "🟠",
    "data engineer": "📊", "data scien": "📊",
    "machine learning": "🤖", "ml ": "🤖", "ai ": "🤖",
    "artificial intel": "🤖", "deep learning": "🧠",
    "blockchain": "⛓️", "web3": "⛓️", "solidity": "⛓️",
    "game dev": "🎮", "unity": "🎮", "unreal": "🎮",
    "security": "🔒", "cyber": "🔒", "penetration": "🔒",
    "embedded": "🔌", "iot": "🔌", "firmware": "🔌",
    "database": "🗄️", "dba": "🗄️", "sql": "🗄️",
    "wordpress": "📝", "shopify": "🛒",
    "salesforce": "☁️", "sap": "🏢",
    "network": "🌐",
    "instructor": "📚", "tutor": "📚", "teacher": "📚", "mentor": "📚",
    "senior": "👨‍💻", "junior": "🌱",
    "lead": "⭐", "principal": "⭐", "staff": "⭐",
    "intern": "🎓", "architect": "🏗️",
    "erp": "🏢", "odoo": "🏢", "dynamics": "🏢",
    "oracle": "🏢", "netsuite": "🏢", "accounting": "🏢",
    "remote": "🌍",
    "egypt": "🇪🇬", "مصر": "🇪🇬", "cairo": "🇪🇬",
    "saudi": "🇸🇦", "riyadh": "🇸🇦", "jeddah": "🇸🇦",
}

DEFAULT_EMOJI = "💻"

# ─── Source Display Names ─────────────────────────────────
SOURCE_DISPLAY = {
    "remotive": "Remotive",
    "himalayas": "Himalayas",
    "jobicy": "Jobicy",
    "remoteok": "RemoteOK",
    "arbeitnow": "Arbeitnow",
    "wwr": "We Work Remotely",
    "workingnomads": "Working Nomads",
    "jsearch": None,  # Uses original source
    "linkedin": "LinkedIn",
    "adzuna": "Adzuna",
    "themuse": "The Muse",
    "findwork": "Findwork",
    "jooble": "Jooble",
    "reed": "Reed",
    "careerjet": "Careerjet",
    "usajobs": "USAJobs",
}
```

- [ ] **Step 2: Commit**

```bash
git add core/channels.py
git commit -m "feat: add core/channels.py with topic routing, emoji map, source names"
```

---

### Task 6: Create core/geo.py — Geo Patterns

**Files:**
- Create: `core/geo.py`

- [ ] **Step 1: Write core/geo.py**

Move geo patterns from old `config.py`.

```python
"""
Geographic patterns for location detection and filtering.
"""

# ─── Allowed Onsite Countries ─────────────────────────────
# Jobs in these countries pass geo-filter regardless of remote/onsite
ALLOWED_ONSITE_COUNTRIES = {"egypt", "مصر", "saudi arabia", "saudi", "ksa", "السعودية"}

# ─── Egypt Patterns ───────────────────────────────────────
EGYPT_PATTERNS = {
    "egypt", "مصر", "cairo", "القاهرة", "alexandria", "الإسكندرية",
    "giza", "الجيزة", "minya", "المنيا", "mansoura", "المنصورة",
    "tanta", "طنطا", "aswan", "أسوان", "luxor", "الأقصر",
    "port said", "بورسعيد", "suez", "السويس", "ismailia", "الإسماعيلية",
    "fayoum", "الفيوم", "zagazig", "الزقازيق", "damanhur", "دمنهور",
    "beni suef", "بني سويف", "sohag", "سوهاج", "asyut", "أسيوط",
    "qena", "قنا", "hurghada", "الغردقة", "sharm el sheikh",
    "new cairo", "6th of october", "6 october", "smart village",
    "new capital", "العاصمة الإدارية", "nasr city", "مدينة نصر",
    "maadi", "المعادي", "heliopolis", "مصر الجديدة", "dokki", "الدقي",
    "mohandessin", "المهندسين",
}

# ─── Saudi Patterns ───────────────────────────────────────
SAUDI_PATTERNS = {
    "saudi arabia", "saudi", "ksa", "السعودية", "المملكة العربية السعودية",
    "riyadh", "الرياض", "jeddah", "جدة", "mecca", "مكة",
    "medina", "المدينة", "dammam", "الدمام", "khobar", "الخبر",
    "dhahran", "الظهران", "tabuk", "تبوك", "abha", "أبها",
    "taif", "الطائف", "jubail", "الجبيل", "yanbu", "ينبع",
    "neom", "نيوم", "qassim", "القصيم", "hail", "حائل",
    "jazan", "جازان", "najran", "نجران", "al kharj", "الخرج",
}

# ─── Remote Patterns ──────────────────────────────────────
REMOTE_PATTERNS = {
    "remote", "anywhere", "worldwide", "work from home", "wfh",
    "distributed", "global", "fully remote", "100% remote",
    "remote-friendly", "location independent", "عن بعد",
}

# ─── Remote-Only Sources ──────────────────────────────────
# These sources only list remote jobs, so they auto-pass geo filter
REMOTE_ONLY_SOURCES = {"remotive", "remoteok", "wwr", "workingnomads", "findwork", "reed"}
```

- [ ] **Step 2: Commit**

```bash
git add core/geo.py
git commit -m "feat: add core/geo.py with geographic patterns"
```

---

### Task 7: Create core/models.py — Updated Job Dataclass

**Files:**
- Create: `core/models.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write the test file first**

```python
# tests/__init__.py
```

```python
# tests/conftest.py
"""Shared test fixtures."""

import pytest
from core.models import Job


@pytest.fixture
def sample_job():
    """A typical job for testing."""
    return Job(
        title="Senior Python Developer",
        company="Acme Corp",
        location="Cairo, Egypt",
        url="https://example.com/jobs/123",
        source="remotive",
        salary_raw="$80,000 - $120,000",
        job_type="Full Time",
        tags=["python", "django", "backend"],
        is_remote=True,
    )


@pytest.fixture
def minimal_job():
    """A job with only required fields."""
    return Job(
        title="Developer",
        company="",
        location="",
        url="https://example.com/jobs/456",
        source="linkedin",
    )
```

```python
# tests/test_models.py
"""Tests for core.models.Job dataclass."""

from core.models import Job


class TestJobUniqueId:
    def test_unique_id_from_url(self):
        job = Job(title="Dev", company="Co", location="", url="https://example.com/jobs/1", source="test")
        assert job.unique_id == "https://example.com/jobs/1"

    def test_unique_id_strips_utm(self):
        job = Job(title="Dev", company="Co", location="", url="https://example.com/jobs/1?utm_source=email", source="test")
        assert job.unique_id == "https://example.com/jobs/1"

    def test_unique_id_strips_trailing_slash(self):
        job = Job(title="Dev", company="Co", location="", url="https://example.com/jobs/1/", source="test")
        assert job.unique_id == "https://example.com/jobs/1"

    def test_unique_id_lowercased(self):
        job = Job(title="Dev", company="Co", location="", url="https://Example.com/Jobs/1", source="test")
        assert job.unique_id == "https://example.com/jobs/1"

    def test_unique_id_fallback_to_title_company(self):
        job = Job(title="Dev", company="Co", location="", url="", source="test")
        assert job.unique_id == "dev|co"


class TestJobEmoji:
    def test_emoji_python(self):
        job = Job(title="Python Developer", company="", location="", url="http://x.com", source="test")
        assert job.emoji == "🐍"

    def test_emoji_default(self):
        job = Job(title="Something Unusual", company="", location="", url="http://x.com", source="test")
        assert job.emoji == "💻"


class TestJobDisplaySource:
    def test_display_source_known(self):
        job = Job(title="Dev", company="", location="", url="http://x.com", source="remotive")
        assert job.display_source == "Remotive"

    def test_display_source_original(self):
        job = Job(title="Dev", company="", location="", url="http://x.com", source="jsearch", original_source="LinkedIn")
        assert job.display_source == "LinkedIn"


class TestJobToDbRow:
    def test_to_db_row_contains_all_fields(self):
        job = Job(
            title="Dev", company="Co", location="Remote",
            url="http://x.com", source="test",
            salary_raw="$100k", salary_min=100000, salary_max=100000,
            salary_currency="USD", job_type="Full Time",
            seniority="senior", is_remote=True, country="US",
            tags=["python"], topics=["backend"],
        )
        row = job.to_db_row()
        assert row["title"] == "Dev"
        assert row["salary_min"] == 100000
        assert row["seniority"] == "senior"
        assert row["tags"] == ["python"]
        assert row["topics"] == ["backend"]
        assert "unique_id" in row


class TestJobFromDbRow:
    def test_from_db_row_roundtrip(self):
        original = Job(
            title="Dev", company="Co", location="Remote",
            url="http://x.com", source="test",
            tags=["python"], is_remote=True,
        )
        row = original.to_db_row()
        restored = Job.from_db_row(row)
        assert restored.title == original.title
        assert restored.source == original.source
        assert restored.tags == original.tags
        assert restored.is_remote == original.is_remote
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd G:/projects/SWE-Jobs && python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.models'`

- [ ] **Step 3: Write core/models.py**

```python
"""
Job data model with database serialization.
"""

from dataclasses import dataclass, field
from typing import Optional
from core.channels import EMOJI_MAP, DEFAULT_EMOJI, SOURCE_DISPLAY


def _flatten_tags(tags) -> str:
    """Safely flatten tags to a string, handling nested lists and non-string items."""
    if not tags:
        return ""
    flat = []
    for item in tags:
        if isinstance(item, list):
            flat.extend(str(i) for i in item)
        elif isinstance(item, dict):
            flat.append(str(item.get("name", item.get("label", ""))))
        else:
            flat.append(str(item))
    return " ".join(flat)


@dataclass
class Job:
    title: str
    company: str
    location: str
    url: str
    source: str
    salary_raw: str = ""
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: str = ""
    job_type: str = ""
    seniority: str = "mid"
    is_remote: bool = False
    country: str = ""
    tags: list = field(default_factory=list)
    topics: list = field(default_factory=list)
    original_source: str = ""
    telegram_message_ids: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.tags is None:
            self.tags = []

    @property
    def unique_id(self) -> str:
        """Generate a unique ID for dedup. Based on URL or title+company."""
        if self.url:
            clean = self.url.split("?utm")[0].split("&utm")[0]
            clean = clean.rstrip("/").lower()
            return clean
        return f"{self.title.lower().strip()}|{self.company.lower().strip()}"

    @property
    def display_source(self) -> str:
        """Get the display name for the source."""
        if self.original_source:
            return self.original_source
        return SOURCE_DISPLAY.get(self.source, self.source.title())

    @property
    def emoji(self) -> str:
        """Pick the best emoji based on title and location."""
        text = f"{self.title} {self.location} {_flatten_tags(self.tags)}".lower()
        for keyword, em in EMOJI_MAP.items():
            if keyword in text:
                return em
        return DEFAULT_EMOJI

    @property
    def salary_display(self) -> str:
        """Format salary for display."""
        if self.salary_raw:
            return self.salary_raw
        if self.salary_min and self.salary_max:
            if self.salary_min == self.salary_max:
                return f"{self.salary_currency} {self.salary_min:,}"
            return f"{self.salary_currency} {self.salary_min:,} - {self.salary_max:,}"
        if self.salary_min:
            return f"{self.salary_currency} {self.salary_min:,}+"
        return ""

    def to_db_row(self) -> dict:
        """Convert to a dict suitable for database insertion.
        JSONB fields are wrapped with psycopg2.extras.Json for proper serialization.
        """
        from psycopg2.extras import Json
        return {
            "unique_id": self.unique_id,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "url": self.url,
            "source": self.source,
            "original_source": self.original_source,
            "salary_raw": self.salary_raw,
            "salary_min": self.salary_min,
            "salary_max": self.salary_max,
            "salary_currency": self.salary_currency,
            "job_type": self.job_type,
            "seniority": self.seniority,
            "is_remote": self.is_remote,
            "country": self.country,
            "tags": self.tags,
            "topics": self.topics,
            "telegram_message_ids": Json(self.telegram_message_ids),
        }

    @classmethod
    def from_db_row(cls, row: dict) -> "Job":
        """Create a Job from a database row dict."""
        return cls(
            title=row.get("title", ""),
            company=row.get("company", ""),
            location=row.get("location", ""),
            url=row.get("url", ""),
            source=row.get("source", ""),
            original_source=row.get("original_source", ""),
            salary_raw=row.get("salary_raw", ""),
            salary_min=row.get("salary_min"),
            salary_max=row.get("salary_max"),
            salary_currency=row.get("salary_currency", ""),
            job_type=row.get("job_type", ""),
            seniority=row.get("seniority", "mid"),
            is_remote=row.get("is_remote", False),
            country=row.get("country", ""),
            tags=row.get("tags", []),
            topics=row.get("topics", []),
            telegram_message_ids=row.get("telegram_message_ids", {}),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd G:/projects/SWE-Jobs && python -m pytest tests/test_models.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add core/models.py tests/__init__.py tests/conftest.py tests/test_models.py
git commit -m "feat: add core/models.py with updated Job dataclass and tests"
```

---

### Task 8: Create core/db.py — Database Connection and CRUD

**Files:**
- Create: `core/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_db.py
"""Tests for core.db database layer (mocked — no real DB needed)."""

from unittest.mock import patch, MagicMock
from core.db import (
    insert_job,
    get_job_by_unique_id,
    get_unsent_jobs,
    mark_job_sent,
    job_exists,
    start_run,
    finish_run,
)
from core.models import Job


class TestInsertJob:
    @patch("core.db._execute")
    def test_insert_job_calls_execute(self, mock_exec):
        mock_exec.return_value = {"id": 1}
        job = Job(title="Dev", company="Co", location="", url="http://x.com", source="test")
        result = insert_job(job)
        assert mock_exec.called
        assert result == {"id": 1}

    @patch("core.db._execute")
    def test_insert_job_passes_all_fields(self, mock_exec):
        mock_exec.return_value = {"id": 1}
        job = Job(
            title="Dev", company="Co", location="Remote",
            url="http://x.com", source="test",
            salary_raw="$100k", salary_min=100000, salary_max=100000,
            salary_currency="USD", seniority="senior",
            tags=["python"], topics=["backend"],
        )
        insert_job(job)
        call_args = mock_exec.call_args
        sql = call_args[0][0]
        assert "INSERT INTO jobs" in sql


class TestJobExists:
    @patch("core.db._fetchone")
    def test_job_exists_true(self, mock_fetch):
        mock_fetch.return_value = {"id": 1}
        assert job_exists("http://x.com") is True

    @patch("core.db._fetchone")
    def test_job_exists_false(self, mock_fetch):
        mock_fetch.return_value = None
        assert job_exists("http://nonexistent.com") is False


class TestBotRuns:
    @patch("core.db._fetchone")
    def test_start_run_returns_id(self, mock_fetch):
        mock_fetch.return_value = {"id": 42}
        run_id = start_run()
        assert run_id == 42

    @patch("core.db._execute")
    def test_finish_run_updates(self, mock_exec):
        finish_run(42, jobs_fetched=100, jobs_filtered=50, jobs_new=10, jobs_sent=8,
                   source_stats={"remotive": 30}, errors=[])
        assert mock_exec.called
        sql = mock_exec.call_args[0][0]
        assert "UPDATE bot_runs" in sql
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd G:/projects/SWE-Jobs && python -m pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.db'`

- [ ] **Step 3: Write core/db.py**

```python
"""
PostgreSQL database layer.
Connects via Supabase pgBouncer. Provides CRUD functions for all tables.
No ORM — raw SQL with parameterized queries.
"""

import json
import logging
from contextlib import contextmanager
from typing import Optional

import psycopg2
import psycopg2.extras
from psycopg2.extras import Json
from psycopg2.pool import SimpleConnectionPool

from core.config import (
    SUPABASE_DB_HOST, SUPABASE_DB_PORT, SUPABASE_DB_NAME,
    SUPABASE_DB_USER, SUPABASE_DB_PASSWORD,
)

log = logging.getLogger(__name__)

# ─── Connection Pool ──────────────────────────────────────

_pool = None


def _get_pool() -> SimpleConnectionPool:
    """Lazy-init connection pool."""
    global _pool
    if _pool is None:
        if not SUPABASE_DB_HOST:
            raise RuntimeError("SUPABASE_DB_HOST not set. Check your .env file.")
        _pool = SimpleConnectionPool(
            minconn=1,
            maxconn=5,
            host=SUPABASE_DB_HOST,
            port=SUPABASE_DB_PORT,
            dbname=SUPABASE_DB_NAME,
            user=SUPABASE_DB_USER,
            password=SUPABASE_DB_PASSWORD,
            sslmode="require",
            options="-c search_path=public",
        )
        log.info(f"DB pool created: {SUPABASE_DB_HOST}:{SUPABASE_DB_PORT}")
    return _pool


@contextmanager
def _get_conn():
    """Get a connection from the pool, return it when done."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def close_pool():
    """Close all connections. Call on shutdown."""
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None


# ─── Low-Level Helpers ────────────────────────────────────

def _execute(sql: str, params: tuple = ()) -> dict | None:
    """Execute SQL, return first row if RETURNING, else None."""
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if cur.description:
                row = cur.fetchone()
                return dict(row) if row else None
            return None


def _fetchone(sql: str, params: tuple = ()) -> dict | None:
    """Fetch a single row."""
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None


def _fetchall(sql: str, params: tuple = ()) -> list[dict]:
    """Fetch all rows."""
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


# ─── Jobs CRUD ────────────────────────────────────────────

def insert_job(job) -> dict | None:
    """Insert a job. Returns the inserted row (with id) or None on conflict.
    NOTE: DO NOTHING will be upgraded to DO UPDATE in Plan 2 (fuzzy dedup).
    """
    row = job.to_db_row()
    sql = """
        INSERT INTO jobs (
            unique_id, title, company, location, url, source, original_source,
            salary_raw, salary_min, salary_max, salary_currency,
            job_type, seniority, is_remote, country, tags, topics,
            telegram_message_ids
        ) VALUES (
            %(unique_id)s, %(title)s, %(company)s, %(location)s, %(url)s,
            %(source)s, %(original_source)s,
            %(salary_raw)s, %(salary_min)s, %(salary_max)s, %(salary_currency)s,
            %(job_type)s, %(seniority)s, %(is_remote)s, %(country)s,
            %(tags)s, %(topics)s, %(telegram_message_ids)s
        )
        ON CONFLICT (unique_id) DO NOTHING
        RETURNING *
    """
    return _execute(sql, row)


def job_exists(unique_id: str) -> bool:
    """Check if a job with this unique_id already exists."""
    row = _fetchone("SELECT id FROM jobs WHERE unique_id = %s", (unique_id,))
    return row is not None


def get_job_by_unique_id(unique_id: str) -> dict | None:
    """Get a job by unique_id."""
    return _fetchone("SELECT * FROM jobs WHERE unique_id = %s", (unique_id,))


def get_unsent_jobs(limit: int = 50) -> list[dict]:
    """Get jobs that haven't been sent to Telegram yet."""
    return _fetchall(
        "SELECT * FROM jobs WHERE sent_at IS NULL ORDER BY created_at ASC LIMIT %s",
        (limit,),
    )


def mark_job_sent(job_id: int, telegram_message_ids: dict) -> None:
    """Mark a job as sent to Telegram."""
    _execute(
        "UPDATE jobs SET sent_at = now(), telegram_message_ids = %s WHERE id = %s",
        (json.dumps(telegram_message_ids), job_id),
    )


def get_recent_jobs_for_dedup(days: int = 7) -> list[dict]:
    """Get recent jobs for fuzzy dedup comparison."""
    return _fetchall(
        """SELECT id, unique_id, title, company, salary_raw, tags
           FROM jobs WHERE created_at > now() - make_interval(days := %s)""",
        (days,),
    )


_JOBS_UPDATABLE_COLUMNS = {
    "title", "company", "location", "url", "source", "original_source",
    "salary_raw", "salary_min", "salary_max", "salary_currency",
    "job_type", "seniority", "is_remote", "country", "tags", "topics",
    "sent_at", "telegram_message_ids",
}


def update_job(job_id: int, updates: dict) -> None:
    """Update specific fields on a job. Only whitelisted columns allowed."""
    if not updates:
        return
    # Validate column names against whitelist to prevent SQL injection
    invalid_keys = set(updates.keys()) - _JOBS_UPDATABLE_COLUMNS
    if invalid_keys:
        raise ValueError(f"Invalid column names: {invalid_keys}")
    # Wrap dict/list values as Json for JSONB columns
    safe_updates = {}
    for k, v in updates.items():
        if isinstance(v, (dict, list)) and k in ("telegram_message_ids",):
            safe_updates[k] = Json(v)
        else:
            safe_updates[k] = v
    set_clauses = ", ".join(f"{k} = %({k})s" for k in safe_updates)
    safe_updates["_id"] = job_id
    _execute(
        f"UPDATE jobs SET {set_clauses} WHERE id = %(_id)s",
        safe_updates,
    )


# ─── Bot Runs ─────────────────────────────────────────────

def start_run() -> int:
    """Create a new bot run record. Returns the run ID."""
    row = _fetchone("INSERT INTO bot_runs DEFAULT VALUES RETURNING id")
    return row["id"]


def finish_run(run_id: int, jobs_fetched: int = 0, jobs_filtered: int = 0,
               jobs_new: int = 0, jobs_sent: int = 0,
               source_stats: Optional[dict] = None, errors: Optional[list] = None) -> None:
    """Update a bot run with results."""
    _execute(
        """UPDATE bot_runs SET
            finished_at = now(),
            jobs_fetched = %s, jobs_filtered = %s, jobs_new = %s, jobs_sent = %s,
            source_stats = %s, errors = %s
           WHERE id = %s""",
        (jobs_fetched, jobs_filtered, jobs_new, jobs_sent,
         json.dumps(source_stats or {}), json.dumps(errors or []),
         run_id),
    )


# ─── Source Health ────────────────────────────────────────

def get_source_health(source: str) -> dict | None:
    """Get health status for a source."""
    return _fetchone("SELECT * FROM source_health WHERE source = %s", (source,))


def upsert_source_health(source: str, success: bool, error: str = "") -> None:
    """Update source health after a fetch attempt."""
    if success:
        _execute(
            """INSERT INTO source_health (source, consecutive_failures, last_success_at)
               VALUES (%s, 0, now())
               ON CONFLICT (source) DO UPDATE SET
                   consecutive_failures = 0,
                   circuit_open_until = NULL,
                   last_success_at = now()""",
            (source,),
        )
    else:
        # Sanitize error message — strip anything that looks like a key/token
        clean_error = error[:200]  # Truncate long errors
        _execute(
            """INSERT INTO source_health (source, consecutive_failures, last_failure_at, last_error)
               VALUES (%s, 1, now(), %s)
               ON CONFLICT (source) DO UPDATE SET
                   consecutive_failures = source_health.consecutive_failures + 1,
                   last_failure_at = now(),
                   last_error = %s,
                   circuit_open_until = CASE
                       WHEN source_health.consecutive_failures + 1 >= 3
                       THEN now() + interval '30 minutes'
                       ELSE source_health.circuit_open_until
                   END""",
            (source, clean_error, clean_error),
        )


def is_source_circuit_open(source: str) -> bool:
    """Check if a source's circuit breaker is open (should be skipped)."""
    row = _fetchone(
        "SELECT circuit_open_until > now() AS is_open FROM source_health WHERE source = %s",
        (source,),
    )
    return bool(row and row.get("is_open", False))


# ─── Users ────────────────────────────────────────────────

def get_or_create_user(telegram_id: int, username: str = "") -> dict:
    """Get or create a user by Telegram ID."""
    row = _fetchone("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
    if row:
        return row
    return _fetchone(
        "INSERT INTO users (telegram_id, username) VALUES (%s, %s) RETURNING *",
        (telegram_id, username),
    )


def update_user_subscriptions(telegram_id: int, subscriptions: dict) -> None:
    """Update a user's subscription filters."""
    _execute(
        "UPDATE users SET subscriptions = %s WHERE telegram_id = %s",
        (json.dumps(subscriptions), telegram_id),
    )


# ─── User Saved Jobs ─────────────────────────────────────

def save_job_for_user(user_id: int, job_id: int) -> bool:
    """Save a job for a user. Returns True if saved, False if already saved."""
    row = _execute(
        """INSERT INTO user_saved_jobs (user_id, job_id)
           VALUES (%s, %s)
           ON CONFLICT (user_id, job_id) DO NOTHING
           RETURNING id""",
        (user_id, job_id),
    )
    return row is not None


def get_saved_jobs(user_id: int, limit: int = 20, offset: int = 0) -> list[dict]:
    """Get a user's saved jobs."""
    return _fetchall(
        """SELECT j.* FROM jobs j
           JOIN user_saved_jobs usj ON j.id = usj.job_id
           WHERE usj.user_id = %s
           ORDER BY usj.saved_at DESC
           LIMIT %s OFFSET %s""",
        (user_id, limit, offset),
    )


# ─── Job Feedback ─────────────────────────────────────────

def add_feedback(job_id: int, user_id: int, feedback_type: str) -> None:
    """Record user feedback on a job."""
    _execute(
        "INSERT INTO job_feedback (job_id, user_id, feedback_type) VALUES (%s, %s, %s)",
        (job_id, user_id, feedback_type),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd G:/projects/SWE-Jobs && python -m pytest tests/test_db.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add core/db.py tests/test_db.py
git commit -m "feat: add core/db.py with PostgreSQL CRUD layer and tests"
```

---

### Task 9: Verify Everything Works Together

**Files:** None new — integration check

- [ ] **Step 1: Run all tests**

Run: `cd G:/projects/SWE-Jobs && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Verify imports work**

Run:
```bash
cd G:/projects/SWE-Jobs && python -c "
from core.config import SUPABASE_DB_HOST, TELEGRAM_BOT_TOKEN, MAX_JOBS_PER_RUN
from core.keywords import INCLUDE_KEYWORDS, EXCLUDE_KEYWORDS, SCORE_THRESHOLD
from core.channels import CHANNELS, EMOJI_MAP, get_topic_thread_id
from core.geo import EGYPT_PATTERNS, SAUDI_PATTERNS, REMOTE_PATTERNS
from core.models import Job
print(f'Config: MAX_JOBS_PER_RUN={MAX_JOBS_PER_RUN}')
print(f'Keywords: {len(INCLUDE_KEYWORDS)} include, {len(EXCLUDE_KEYWORDS)} exclude')
print(f'Channels: {len(CHANNELS)} topics')
print(f'Geo: {len(EGYPT_PATTERNS)} egypt, {len(SAUDI_PATTERNS)} saudi patterns')
print(f'Job fields: {[f.name for f in Job.__dataclass_fields__.values()]}')
print('All imports OK')
"
```
Expected: Prints counts and "All imports OK"

- [ ] **Step 3: Verify old sources still importable**

The old `config.py` and `models.py` still exist at the root level. The 15 source fetchers import from these. They will be migrated in a later plan. For now, verify they still work:

Run:
```bash
cd G:/projects/SWE-Jobs && python -c "
from sources import ALL_FETCHERS
print(f'{len(ALL_FETCHERS)} fetchers registered')
for name, fn in ALL_FETCHERS:
    print(f'  {name}: {fn.__module__}.{fn.__name__}')
print('Old sources still work')
"
```
Expected: Lists 15 fetchers and "Old sources still work"

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete Plan 1 — core infrastructure foundation"
```

---

## Summary

After completing this plan, the project has:

- **PostgreSQL schema** ready to deploy to Supabase (6 tables, indexes, RLS, triggers)
- **`core/` package** with cleanly separated config, keywords, channels, geo, models, and DB layer
- **Updated Job model** with salary, seniority, country, topics fields + DB serialization
- **Connection pooling** via pgBouncer-compatible pool
- **Tests** for models and DB layer
- **Old code untouched** — sources/ still work with the root-level config.py and models.py

**Next:** Plan 2 (Quality Engine) builds on `core/` to add salary_parser, seniority, country_detector, weighted scoring, and fuzzy dedup.
