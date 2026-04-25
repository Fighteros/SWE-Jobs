# egytech.fyi Salary Localization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace posting-derived salary aggregations with the egytech.fyi public API as the source of truth, scoped to Egypt-based jobs.

**Architecture:** Two new modules — `core/egytech.py` (HTTP client with 24h in-memory TTL cache) and `core/egytech_mapping.py` (our enums → egytech enums). The Salary dashboard page, `/api/stats/salary` endpoint, `/salary` bot command, and per-job market line on Egypt jobs all flow through these. The old salary parser, the per-job posting-derived salary chip, the `min_salary` subscription filter, and the `min_salary` param on `/api/jobs/search` are removed. DB columns are kept (no migration) so old data is preserved; they just stop being populated.

**Tech Stack:** Python 3, FastAPI, `requests` (already in `requirements.txt`), psycopg2, React + TypeScript, Recharts, python-telegram-bot, pytest.

**Spec:** [docs/superpowers/specs/2026-04-25-egytech-salaries-design.md](../specs/2026-04-25-egytech-salaries-design.md)

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `core/egytech.py` | Create | HTTP client over `https://api.egytech.fyi`, 24h TTL cache, `market_salary_for_job` helper |
| `core/egytech_mapping.py` | Create | `SENIORITY_TO_LEVEL`, `TOPIC_TO_TITLE`, role alias resolver |
| `tests/test_egytech_client.py` | Create | Unit tests for client (mocked HTTP), cache behavior |
| `tests/test_egytech_mapping.py` | Create | Unit tests for enum mappings + role resolver |
| `tests/test_egytech_integration.py` | Create | One live integration test (skipped by default) |
| `api/routes_stats.py` | Modify | Replace `/salary` body with egytech proxy |
| `api/routes_jobs.py` | Modify | Add `market_salary` field to listing response for Egypt jobs; drop `min_salary` query param |
| `dashboard/src/types.ts` | Modify | Update `SalaryStats` type; add `market_salary` to `Job` |
| `dashboard/src/api.ts` | Modify | Update `getSalaryStats` signature |
| `dashboard/src/pages/Salary.tsx` | Rewrite | New filters (role/seniority/yoe), histogram, EGP formatting |
| `dashboard/src/components/JobCard.tsx` | Modify | Replace posting-salary chip with `market_salary` (Egypt only) |
| `bot/commands.py` | Modify | Rewrite `cmd_salary`, drop `min_salary` line in `cmd_mysubs` |
| `bot/sender.py` | Modify | Replace `job.salary_display` line with egytech market line for Egypt jobs |
| `bot/notifications.py` | Modify | Drop `min_salary` filter from `_job_matches_subscription` |
| `core/enrichment.py` | Modify | Remove `parse_salary` step |
| `core/salary_parser.py` | Delete | No longer used |
| `tests/test_salary_parser.py` | Delete | Module gone |
| `tests/test_enrichment.py` | Modify | Drop `test_parses_salary` and `test_no_salary_leaves_none` |
| `core/models.py` | Modify | Update `Job.salary_display` to always return `""` (cleaner than deleting; preserves callers) |

---

## Task 1: HTTP client for egytech.fyi (`core/egytech.py`)

**Files:**
- Create: `core/egytech.py`
- Create: `tests/test_egytech_client.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_egytech_client.py`:

```python
"""Unit tests for core.egytech HTTP client."""

import time
from unittest.mock import patch, MagicMock
import pytest

from core.egytech import get_stats, _cache, market_salary_for_job
from core.models import Job


@pytest.fixture(autouse=True)
def _clear_cache():
    _cache.clear()
    yield
    _cache.clear()


def _mock_response(status_code: int, json_data: dict | None = None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


class TestGetStats:
    def test_returns_stats_on_200(self):
        payload = {
            "stats": {
                "totalCount": 152, "median": 33800,
                "p20Compensation": 21200, "p75Compensation": 44000, "p90Compensation": 63000,
            },
            "buckets": [{"bucket": "20-25K", "count": 19}],
        }
        with patch("core.egytech.requests.get", return_value=_mock_response(200, payload)) as mock_get:
            result = get_stats(title="backend", level="mid_level")
        assert result is not None
        assert result["stats"]["median"] == 33800
        assert result["buckets"][0]["count"] == 19
        # Pinned exclusions must be in the URL
        called_url = mock_get.call_args[0][0]
        assert "include_relocated=false" in called_url
        assert "include_remote_abroad=false" in called_url
        assert "title=backend" in called_url
        assert "level=mid_level" in called_url

    def test_returns_none_on_404(self):
        with patch("core.egytech.requests.get", return_value=_mock_response(404)):
            assert get_stats(title="backend", level="senior_principal") is None

    def test_returns_none_on_network_error(self):
        import requests as r
        with patch("core.egytech.requests.get", side_effect=r.RequestException("boom")):
            assert get_stats(title="backend") is None

    def test_caches_successful_response(self):
        payload = {"stats": {"median": 1}, "buckets": []}
        with patch("core.egytech.requests.get", return_value=_mock_response(200, payload)) as mock_get:
            get_stats(title="backend", level="mid_level")
            get_stats(title="backend", level="mid_level")
        assert mock_get.call_count == 1

    def test_caches_404_response(self):
        with patch("core.egytech.requests.get", return_value=_mock_response(404)) as mock_get:
            get_stats(title="backend", level="senior_principal")
            get_stats(title="backend", level="senior_principal")
        assert mock_get.call_count == 1

    def test_does_not_cache_network_errors(self):
        import requests as r
        with patch("core.egytech.requests.get", side_effect=r.RequestException("boom")) as mock_get:
            get_stats(title="backend")
            get_stats(title="backend")
        assert mock_get.call_count == 2

    def test_cache_expires_after_ttl(self):
        payload = {"stats": {"median": 1}, "buckets": []}
        with patch("core.egytech.requests.get", return_value=_mock_response(200, payload)) as mock_get:
            get_stats(title="backend", level="mid_level")
            # Manually expire the cache entry
            key = next(iter(_cache))
            ts, data = _cache[key]
            _cache[key] = (ts - 25 * 3600, data)
            get_stats(title="backend", level="mid_level")
        assert mock_get.call_count == 2

    def test_omits_optional_params_when_none(self):
        payload = {"stats": {}, "buckets": []}
        with patch("core.egytech.requests.get", return_value=_mock_response(200, payload)) as mock_get:
            get_stats(title="backend")
        url = mock_get.call_args[0][0]
        assert "level=" not in url
        assert "yoe_from_included=" not in url
        assert "yoe_to_excluded=" not in url


class TestMarketSalaryForJob:
    def _job(self, **kwargs) -> Job:
        defaults = {
            "title": "Backend Engineer", "company": "X", "location": "Cairo",
            "url": "http://x", "source": "test",
            "country": "EG", "seniority": "mid", "topics": ["backend"],
        }
        defaults.update(kwargs)
        return Job(**defaults)

    def test_returns_none_for_non_egypt(self):
        job = self._job(country="US")
        assert market_salary_for_job(job) is None

    def test_returns_none_when_seniority_unmappable(self):
        job = self._job(seniority="unknown_level")
        assert market_salary_for_job(job) is None

    def test_returns_none_when_topic_unmappable(self):
        job = self._job(topics=["gamedev"])
        assert market_salary_for_job(job) is None

    def test_returns_formatted_range_when_data_present(self):
        payload = {
            "stats": {"totalCount": 152, "median": 33800,
                      "p20Compensation": 21200, "p75Compensation": 44000, "p90Compensation": 63000},
            "buckets": [],
        }
        with patch("core.egytech.requests.get", return_value=_mock_response(200, payload)):
            job = self._job()
            result = market_salary_for_job(job)
        assert result == "EGP 21k–44k/mo"

    def test_returns_none_when_egytech_returns_none(self):
        with patch("core.egytech.requests.get", return_value=_mock_response(404)):
            job = self._job()
            assert market_salary_for_job(job) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_egytech_client.py -v`
Expected: FAIL with `ImportError: cannot import name 'get_stats' from 'core.egytech'` (module doesn't exist).

- [ ] **Step 3: Implement the client**

Create `core/egytech.py`:

```python
"""
HTTP client for the egytech.fyi public API.
Source: https://api.egytech.fyi (April 2024 Egyptian tech compensation survey).
Caches successful and 404 responses for 24h. Network errors are not cached.
"""

import logging
import time
from typing import Optional
from urllib.parse import urlencode

import requests

from core.egytech_mapping import SENIORITY_TO_LEVEL, TOPIC_TO_TITLE
from core.models import Job

log = logging.getLogger(__name__)

_BASE = "https://api.egytech.fyi"
_TIMEOUT = 5.0
_TTL_SECONDS = 24 * 3600

# Cache: { (title, level, yoe_from, yoe_to): (timestamp, response_dict_or_None) }
# A cached value of `None` means a 404 ("no participants for combo").
_cache: dict[tuple, tuple[float, Optional[dict]]] = {}


def get_stats(
    title: str,
    level: Optional[str] = None,
    yoe_from: Optional[int] = None,
    yoe_to: Optional[int] = None,
) -> Optional[dict]:
    """
    Fetch compensation stats from egytech.fyi.
    Pins include_relocated=false and include_remote_abroad=false.
    Returns the response dict on success, None on 404 or network error.
    """
    key = (title, level, yoe_from, yoe_to)
    now = time.time()

    cached = _cache.get(key)
    if cached:
        ts, data = cached
        if now - ts < _TTL_SECONDS:
            return data

    params: dict[str, str] = {
        "title": title,
        "include_relocated": "false",
        "include_remote_abroad": "false",
    }
    if level:
        params["level"] = level
    if yoe_from is not None:
        params["yoe_from_included"] = str(yoe_from)
    if yoe_to is not None:
        params["yoe_to_excluded"] = str(yoe_to)

    url = f"{_BASE}/stats?{urlencode(params)}"
    try:
        resp = requests.get(url, timeout=_TIMEOUT)
    except requests.RequestException as e:
        log.warning(f"egytech network error: {e}")
        return None

    if resp.status_code == 404:
        _cache[key] = (now, None)
        return None
    if resp.status_code != 200:
        log.warning(f"egytech unexpected status {resp.status_code} for {url}")
        return None

    data = resp.json()
    _cache[key] = (now, data)
    return data


def _round_thousands(n: int) -> str:
    return f"{int(round(n / 1000))}k"


def market_salary_for_job(job: Job) -> Optional[str]:
    """
    Return a human-readable EGP/mo p20–p75 range for an Egypt-based job, or None.
    Uses the job's primary topic + seniority to look up egytech stats.
    """
    if job.country != "EG":
        return None

    level = SENIORITY_TO_LEVEL.get(job.seniority)
    if level is None:
        return None

    title = None
    for topic in job.topics:
        if topic in TOPIC_TO_TITLE:
            title = TOPIC_TO_TITLE[topic]
            break
    if title is None:
        return None

    data = get_stats(title=title, level=level)
    if not data or "stats" not in data:
        return None

    stats = data["stats"]
    p20 = stats.get("p20Compensation")
    p75 = stats.get("p75Compensation")
    if not p20 or not p75:
        return None

    return f"EGP {_round_thousands(p20)}–{_round_thousands(p75)}/mo"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_egytech_client.py -v`
Expected: All 13 tests PASS. If a mapping test fails because `egytech_mapping.py` doesn't exist yet, jump to Task 2 and come back — but the import at the top will fail. To unblock this task only, create a stub `core/egytech_mapping.py` containing just:
```python
SENIORITY_TO_LEVEL = {"mid": "mid_level", "intern": "intern", "junior": "junior", "senior": "senior", "lead": "team_lead", "executive": "c_level"}
TOPIC_TO_TITLE = {"backend": "backend"}
```
Then complete Task 2 next.

- [ ] **Step 5: Commit**

```bash
git add core/egytech.py core/egytech_mapping.py tests/test_egytech_client.py
git commit -m "feat: add egytech.fyi HTTP client with 24h TTL cache"
```

---

## Task 2: Enum mapping module (`core/egytech_mapping.py`)

**Files:**
- Modify (or replace stub): `core/egytech_mapping.py`
- Create: `tests/test_egytech_mapping.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_egytech_mapping.py`:

```python
"""Unit tests for core.egytech_mapping."""

from core.egytech_mapping import (
    SENIORITY_TO_LEVEL,
    TOPIC_TO_TITLE,
    parse_role_query,
    EGYTECH_TITLES,
    EGYTECH_LEVELS,
)


class TestSeniorityMapping:
    def test_all_our_seniorities_map(self):
        for s in ("intern", "junior", "mid", "senior", "lead", "executive"):
            assert s in SENIORITY_TO_LEVEL
            assert SENIORITY_TO_LEVEL[s] in EGYTECH_LEVELS


class TestTopicMapping:
    def test_known_topics_map(self):
        assert TOPIC_TO_TITLE["backend"] == "backend"
        assert TOPIC_TO_TITLE["frontend"] == "frontend"
        assert TOPIC_TO_TITLE["fullstack"] == "fullstack"
        assert TOPIC_TO_TITLE["mobile"] == "mobile"
        assert TOPIC_TO_TITLE["devops"] == "devops_sre_platform"
        assert TOPIC_TO_TITLE["qa"] == "testing"
        assert TOPIC_TO_TITLE["cybersecurity"] == "security"

    def test_all_mapped_titles_are_valid_egytech_titles(self):
        for title in TOPIC_TO_TITLE.values():
            assert title in EGYTECH_TITLES

    def test_unmapped_topics_return_none(self):
        for t in ("gamedev", "blockchain", "erp", "internships", "general", "egypt", "saudi"):
            assert TOPIC_TO_TITLE.get(t) is None


class TestParseRoleQuery:
    def test_canonical_titles_pass_through(self):
        assert parse_role_query("backend") == "backend"
        assert parse_role_query("frontend") == "frontend"

    def test_aliases_resolve(self):
        assert parse_role_query("python") == "backend"
        assert parse_role_query("java") == "backend"
        assert parse_role_query("node") == "backend"
        assert parse_role_query("react") == "frontend"
        assert parse_role_query("vue") == "frontend"
        assert parse_role_query("ios") == "mobile"
        assert parse_role_query("android") == "mobile"
        assert parse_role_query("flutter") == "mobile"
        assert parse_role_query("devops") == "devops_sre_platform"
        assert parse_role_query("sre") == "devops_sre_platform"

    def test_case_insensitive(self):
        assert parse_role_query("Python") == "backend"
        assert parse_role_query("REACT") == "frontend"

    def test_unknown_returns_none(self):
        assert parse_role_query("gamedev") is None
        assert parse_role_query("xyzzy") is None
        assert parse_role_query("") is None
        assert parse_role_query(None) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_egytech_mapping.py -v`
Expected: FAIL — `parse_role_query`, `EGYTECH_TITLES`, `EGYTECH_LEVELS` don't exist (or stub doesn't have all entries).

- [ ] **Step 3: Implement the mapping module**

Replace `core/egytech_mapping.py`:

```python
"""
Mappings from our internal enums (seniority, topic) to egytech.fyi enums (level, title).
Also contains free-text role aliases for the bot/dashboard role search.
"""

from typing import Optional

# Full set of egytech.fyi title enum values (from their OpenAPI spec).
EGYTECH_TITLES: frozenset[str] = frozenset({
    "backend", "frontend", "ai_automation", "crm", "data_analytics",
    "data_engineer", "data_scientist", "devops_sre_platform", "embedded",
    "engineering_manager", "executive", "fullstack", "hardware", "mobile",
    "product_manager", "product_owner", "testing", "research", "scrum",
    "security", "system_arch", "technical_support", "ui_ux",
})

# Full set of egytech.fyi level enum values.
EGYTECH_LEVELS: frozenset[str] = frozenset({
    "c_level", "director", "group_product_manager", "intern", "junior",
    "manager", "mid_level", "principal", "senior", "senior_manager",
    "senior_principal", "senior_staff", "staff", "team_lead", "vp",
})

# Our seniority enum -> egytech level enum.
SENIORITY_TO_LEVEL: dict[str, str] = {
    "intern":    "intern",
    "junior":    "junior",
    "mid":       "mid_level",
    "senior":    "senior",
    "lead":      "team_lead",
    "executive": "c_level",
}

# Our topic key -> egytech title enum.
# Topics not in this dict (gamedev, blockchain, erp, internships, general, egypt, saudi)
# have no clean mapping and produce no salary lookup.
TOPIC_TO_TITLE: dict[str, str] = {
    "backend":       "backend",
    "frontend":      "frontend",
    "fullstack":     "fullstack",
    "mobile":        "mobile",
    "devops":        "devops_sre_platform",
    "qa":            "testing",
    "cybersecurity": "security",
}

# Free-text aliases the user might type (in /salary or the dashboard search).
# Maps lowercased token -> egytech title.
_ROLE_ALIASES: dict[str, str] = {
    # backend
    "backend": "backend", "back-end": "backend", "back end": "backend",
    "python": "backend", "java": "backend", "node": "backend", "nodejs": "backend",
    "go": "backend", "golang": "backend", "rust": "backend", "ruby": "backend",
    "php": "backend", "django": "backend", "flask": "backend", "spring": "backend",
    "rails": "backend", "laravel": "backend", ".net": "backend", "c#": "backend",
    # frontend
    "frontend": "frontend", "front-end": "frontend", "front end": "frontend",
    "react": "frontend", "vue": "frontend", "angular": "frontend",
    "javascript": "frontend", "typescript": "frontend", "next.js": "frontend",
    "nextjs": "frontend", "svelte": "frontend",
    # fullstack
    "fullstack": "fullstack", "full-stack": "fullstack", "full stack": "fullstack",
    # mobile
    "mobile": "mobile", "ios": "mobile", "android": "mobile", "flutter": "mobile",
    "react native": "mobile", "swift": "mobile", "kotlin": "mobile",
    # devops / sre / platform
    "devops": "devops_sre_platform", "sre": "devops_sre_platform",
    "platform": "devops_sre_platform", "infra": "devops_sre_platform",
    "infrastructure": "devops_sre_platform", "cloud": "devops_sre_platform",
    "kubernetes": "devops_sre_platform", "k8s": "devops_sre_platform",
    # testing
    "qa": "testing", "test": "testing", "testing": "testing", "sdet": "testing",
    "automation": "testing",
    # security
    "security": "security", "cybersecurity": "security", "infosec": "security",
    "appsec": "security",
    # data
    "data engineer": "data_engineer", "data engineering": "data_engineer",
    "data scientist": "data_scientist", "data science": "data_scientist",
    "ml": "data_scientist", "machine learning": "data_scientist",
    "data analytics": "data_analytics", "analyst": "data_analytics",
    # embedded / hardware
    "embedded": "embedded", "firmware": "embedded", "iot": "embedded",
    "hardware": "hardware",
    # roles
    "ui": "ui_ux", "ux": "ui_ux", "ui/ux": "ui_ux", "designer": "ui_ux",
    "pm": "product_manager", "product manager": "product_manager",
    "po": "product_owner", "product owner": "product_owner",
    "em": "engineering_manager", "engineering manager": "engineering_manager",
    "scrum": "scrum", "scrum master": "scrum",
    "research": "research", "researcher": "research",
    "support": "technical_support", "technical support": "technical_support",
    "architect": "system_arch", "system architect": "system_arch",
    "ai": "ai_automation", "automation": "ai_automation",
    "crm": "crm",
}


def parse_role_query(text: Optional[str]) -> Optional[str]:
    """Resolve a free-text role query to an egytech title. Returns None on no match."""
    if not text:
        return None
    text = text.strip().lower()
    if not text:
        return None
    return _ROLE_ALIASES.get(text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_egytech_mapping.py tests/test_egytech_client.py -v`
Expected: All tests PASS (mapping tests + client tests).

- [ ] **Step 5: Commit**

```bash
git add core/egytech_mapping.py tests/test_egytech_mapping.py
git commit -m "feat: add egytech.fyi enum mapping and role alias resolver"
```

---

## Task 3: Live integration test (skipped by default)

**Files:**
- Create: `tests/test_egytech_integration.py`

- [ ] **Step 1: Write the test**

Create `tests/test_egytech_integration.py`:

```python
"""
Integration test that hits the real egytech.fyi API.
Skipped by default; run with: pytest -m integration tests/test_egytech_integration.py
"""

import pytest

from core.egytech import _cache, get_stats


@pytest.mark.integration
def test_live_backend_mid_level_returns_data():
    _cache.clear()
    data = get_stats(title="backend", level="mid_level")
    assert data is not None
    stats = data["stats"]
    assert stats["totalCount"] > 0
    assert stats["median"] > 0
    assert stats["p20Compensation"] < stats["median"] < stats["p75Compensation"]
```

- [ ] **Step 2: Register the marker in pytest config**

Check if `pytest.ini` or `pyproject.toml` already declares markers. Run:
```bash
ls pytest.ini pyproject.toml setup.cfg 2>/dev/null
```

If none exist, create `pytest.ini`:
```ini
[pytest]
markers =
    integration: tests that hit live external services (skipped by default)
addopts = -m "not integration"
```

If `pyproject.toml` exists with a `[tool.pytest.ini_options]` section, add:
```toml
markers = ["integration: tests that hit live external services (skipped by default)"]
addopts = "-m 'not integration'"
```

- [ ] **Step 3: Verify it's skipped by default**

Run: `pytest tests/test_egytech_integration.py -v`
Expected: 1 deselected, 0 passed.

Run: `pytest -m integration tests/test_egytech_integration.py -v`
Expected: 1 passed (requires network).

- [ ] **Step 4: Commit**

```bash
git add tests/test_egytech_integration.py pytest.ini
git commit -m "test: add live egytech.fyi integration test (skipped by default)"
```

---

## Task 4: Rewrite `/api/stats/salary` endpoint

**Files:**
- Modify: `api/routes_stats.py:52-102` (the `salary_stats` function)

- [ ] **Step 1: Write a smoke test for the new shape**

There's no existing test file for `routes_stats.py`. Create `tests/test_routes_stats_salary.py`:

```python
"""Tests for /api/stats/salary egytech-backed endpoint."""

from unittest.mock import patch
from fastapi.testclient import TestClient

from api.app import app
from core.egytech import _cache


client = TestClient(app)


def setup_function():
    _cache.clear()


def test_returns_egytech_payload_for_known_role():
    payload = {
        "stats": {
            "totalCount": 152, "median": 33800,
            "p20Compensation": 21200, "p75Compensation": 44000, "p90Compensation": 63000,
        },
        "buckets": [{"bucket": "20-25K", "count": 19}],
    }
    with patch("core.egytech.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = payload
        resp = client.get("/api/stats/salary?role=backend&seniority=mid")
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is True
    assert body["currency"] == "EGP"
    assert body["period"] == "monthly"
    assert body["stats"]["sample_size"] == 152
    assert body["stats"]["median"] == 33800
    assert body["stats"]["p20"] == 21200
    assert body["stats"]["p75"] == 44000
    assert body["stats"]["p90"] == 63000
    assert body["buckets"] == [{"label": "20-25K", "count": 19}]
    assert body["filters"] == {"role": "backend", "seniority": "mid", "yoe_from": None, "yoe_to": None}


def test_unmapped_role_returns_matched_false():
    resp = client.get("/api/stats/salary?role=xyzzy")
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is False
    assert body["stats"] is None
    assert body["buckets"] == []


def test_egytech_404_returns_matched_false():
    with patch("core.egytech.requests.get") as mock_get:
        mock_get.return_value.status_code = 404
        resp = client.get("/api/stats/salary?role=backend&seniority=intern")
    assert resp.status_code == 200
    assert resp.json()["matched"] is False


def test_yoe_filter_passed_through():
    payload = {"stats": {"totalCount": 5, "median": 100,
                         "p20Compensation": 80, "p75Compensation": 120, "p90Compensation": 140},
               "buckets": []}
    with patch("core.egytech.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = payload
        client.get("/api/stats/salary?role=backend&yoe_from=2&yoe_to=5")
    url = mock_get.call_args[0][0]
    assert "yoe_from_included=2" in url
    assert "yoe_to_excluded=5" in url
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_routes_stats_salary.py -v`
Expected: FAIL — current endpoint returns the old shape with `overall` and `by_seniority`.

- [ ] **Step 3: Replace the endpoint**

In `api/routes_stats.py`, replace the entire `salary_stats` function (lines 52-102) with:

```python
@router.get("/salary")
@limiter.limit("20/minute")
async def salary_stats(
    request: Request,
    role: Optional[str] = Query(None, description="Free-text role (e.g. backend, python, react)"),
    seniority: Optional[str] = Query(None, description="Our seniority enum (intern/junior/mid/senior/lead/executive)"),
    yoe_from: Optional[int] = Query(None, ge=0, le=20, description="Min years of experience (inclusive)"),
    yoe_to: Optional[int] = Query(None, ge=1, le=26, description="Max years of experience (exclusive)"),
):
    """Egyptian tech salary statistics, sourced from egytech.fyi (April 2024 survey)."""
    from core.egytech import get_stats
    from core.egytech_mapping import parse_role_query, SENIORITY_TO_LEVEL

    empty = {
        "currency": "EGP",
        "period": "monthly",
        "source": "egytech.fyi April 2024 survey",
        "stats": None,
        "buckets": [],
        "filters": {"role": role, "seniority": seniority, "yoe_from": yoe_from, "yoe_to": yoe_to},
        "matched": False,
    }

    title = parse_role_query(role) if role else None
    if not title:
        return empty

    level = SENIORITY_TO_LEVEL.get(seniority) if seniority else None

    data = get_stats(title=title, level=level, yoe_from=yoe_from, yoe_to=yoe_to)
    if not data or "stats" not in data:
        return empty

    s = data["stats"]
    return {
        "currency": "EGP",
        "period": "monthly",
        "source": "egytech.fyi April 2024 survey",
        "stats": {
            "sample_size": s.get("totalCount", 0),
            "median": s.get("median"),
            "p20": s.get("p20Compensation"),
            "p75": s.get("p75Compensation"),
            "p90": s.get("p90Compensation"),
        },
        "buckets": [{"label": b["bucket"], "count": b["count"]} for b in data.get("buckets", [])],
        "filters": {"role": role, "seniority": seniority, "yoe_from": yoe_from, "yoe_to": yoe_to},
        "matched": True,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_routes_stats_salary.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add api/routes_stats.py tests/test_routes_stats_salary.py
git commit -m "feat: rewrite /api/stats/salary to proxy egytech.fyi"
```

---

## Task 5: Update dashboard types and API client

**Files:**
- Modify: `dashboard/src/types.ts`
- Modify: `dashboard/src/api.ts`

- [ ] **Step 1: Replace `SalaryStats` type and add `market_salary` to `Job`**

In `dashboard/src/types.ts`, replace the `SalaryStats` interface (lines 40-56) with:

```typescript
export interface SalaryStats {
  currency: string;
  period: string;
  source: string;
  stats: {
    sample_size: number;
    median: number | null;
    p20: number | null;
    p75: number | null;
    p90: number | null;
  } | null;
  buckets: { label: string; count: number }[];
  filters: {
    role: string | null;
    seniority: string | null;
    yoe_from: number | null;
    yoe_to: number | null;
  };
  matched: boolean;
}
```

In the same file, add `market_salary` to the `Job` interface (after line 18, `topics: string[];`):

```typescript
  market_salary: string | null;
```

The full `Job` interface should now include `market_salary: string | null;`.

- [ ] **Step 2: Update `getSalaryStats` signature in `api.ts`**

The current signature `getSalaryStats: (params: Record<string, string>) => ...` already passes through arbitrary params, so no change needed in the function body. But to make valid params discoverable, add a comment above it. Replace lines 31-32 with:

```typescript
  // Params: role (string), seniority (string), yoe_from (string), yoe_to (string)
  getSalaryStats: (params: Record<string, string>) =>
    fetchApi<SalaryStats>('/api/stats/salary', params),
```

- [ ] **Step 3: Verify TypeScript still compiles**

Run from the `dashboard/` directory:
```bash
cd dashboard && npm run build
```
Expected: build fails because `Salary.tsx` references `stats.overall.avg_min` etc. — that's fixed in Task 6. To unblock this commit, add a temporary `// @ts-nocheck` line at the top of `dashboard/src/pages/Salary.tsx`. This will be removed in Task 6.

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/types.ts dashboard/src/api.ts dashboard/src/pages/Salary.tsx
git commit -m "feat(dashboard): update types for egytech-backed salary endpoint"
```

---

## Task 6: Rewrite Salary dashboard page

**Files:**
- Rewrite: `dashboard/src/pages/Salary.tsx`

- [ ] **Step 1: Replace the file**

Replace the entire contents of `dashboard/src/pages/Salary.tsx` with:

```tsx
import { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { api } from '../api';
import type { SalaryStats } from '../types';

const ROLE_OPTIONS = [
  '', 'backend', 'frontend', 'fullstack', 'mobile', 'devops', 'qa',
  'security', 'data engineer', 'data scientist', 'data analytics',
  'embedded', 'ui ux', 'product manager', 'engineering manager',
];

const SENIORITY_OPTIONS = ['', 'intern', 'junior', 'mid', 'senior', 'lead', 'executive'];

const fmtEgp = (n: number | null | undefined): string =>
  n == null ? '—' : `EGP ${n.toLocaleString()}/mo`;

export default function Salary() {
  const [stats, setStats] = useState<SalaryStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [role, setRole] = useState('backend');
  const [seniority, setSeniority] = useState('');
  const [yoeFrom, setYoeFrom] = useState('');
  const [yoeTo, setYoeTo] = useState('');

  const fetchSalary = () => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (role) params.role = role;
    if (seniority) params.seniority = seniority;
    if (yoeFrom) params.yoe_from = yoeFrom;
    if (yoeTo) params.yoe_to = yoeTo;
    api.getSalaryStats(params)
      .then(setStats)
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchSalary();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-1">Egyptian Tech Salaries</h1>
      <p className="text-xs text-gray-500 mb-6">
        Source: <a href="https://egytech.fyi" target="_blank" rel="noopener noreferrer" className="underline">egytech.fyi</a> — April 2024 survey, ~2,100 responses. All values are monthly EGP, excluding relocated and remote-abroad participants.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-3 mb-6">
        <div>
          <label className="block text-xs text-gray-600 mb-1">Role</label>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm w-full"
          >
            {ROLE_OPTIONS.map((r) => (
              <option key={r} value={r}>{r || 'Any'}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-600 mb-1">Seniority</label>
          <select
            value={seniority}
            onChange={(e) => setSeniority(e.target.value)}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm w-full"
          >
            {SENIORITY_OPTIONS.map((s) => (
              <option key={s} value={s}>{s || 'Any'}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-600 mb-1">YoE from</label>
          <input
            type="number"
            min={0}
            max={20}
            value={yoeFrom}
            onChange={(e) => setYoeFrom(e.target.value)}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm w-full"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-600 mb-1">YoE to (excl.)</label>
          <input
            type="number"
            min={1}
            max={26}
            value={yoeTo}
            onChange={(e) => setYoeTo(e.target.value)}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm w-full"
          />
        </div>
      </div>

      <button
        onClick={fetchSalary}
        className="bg-blue-600 text-white px-4 py-1.5 rounded text-sm hover:bg-blue-700 mb-6"
      >
        Update
      </button>

      {loading && <p className="text-gray-500 py-8">Loading...</p>}

      {!loading && stats && !stats.matched && (
        <div className="bg-yellow-50 border border-yellow-200 rounded p-4 text-sm text-yellow-900">
          No data for this combination. Try a broader filter (e.g. clear seniority or YoE).
        </div>
      )}

      {!loading && stats && stats.matched && stats.stats && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            <div className="bg-white rounded-lg border p-4 text-center">
              <p className="text-2xl font-bold text-gray-700">{stats.stats.sample_size}</p>
              <p className="text-xs text-gray-500">Sample Size</p>
            </div>
            <div className="bg-white rounded-lg border p-4 text-center">
              <p className="text-2xl font-bold text-blue-600">{fmtEgp(stats.stats.median)}</p>
              <p className="text-xs text-gray-500">Median</p>
            </div>
            <div className="bg-white rounded-lg border p-4 text-center">
              <p className="text-lg font-bold text-green-600">
                {fmtEgp(stats.stats.p20)} – {fmtEgp(stats.stats.p75)}
              </p>
              <p className="text-xs text-gray-500">P20 – P75</p>
            </div>
            <div className="bg-white rounded-lg border p-4 text-center">
              <p className="text-2xl font-bold text-orange-600">{fmtEgp(stats.stats.p90)}</p>
              <p className="text-xs text-gray-500">P90</p>
            </div>
          </div>

          {stats.buckets.length > 0 && (
            <div className="bg-white rounded-lg border p-4">
              <h2 className="font-semibold text-gray-900 mb-4">Distribution</h2>
              <ResponsiveContainer width="100%" height={350}>
                <BarChart data={stats.buckets}>
                  <XAxis dataKey="label" />
                  <YAxis />
                  <Tooltip />
                  <Bar dataKey="count" fill="#3b82f6" name="Participants" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify the build**

```bash
cd dashboard && npm run build
```
Expected: build succeeds with no TypeScript errors.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/Salary.tsx
git commit -m "feat(dashboard): rewrite Salary page for egytech.fyi data"
```

---

## Task 7: Add `market_salary` to job listings (backend + JobCard)

**Files:**
- Modify: `api/routes_jobs.py`
- Modify: `dashboard/src/components/JobCard.tsx`

- [ ] **Step 1: Add `market_salary` enrichment to the listing endpoint**

In `api/routes_jobs.py`, replace the `return` block (lines 67-73) and the rows fetching block. The full updated function body from line 24 onward:

```python
    """Search and filter jobs."""
    from core.egytech import market_salary_for_job
    from core.models import Job

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
    if remote:
        conditions_sql.append("is_remote = TRUE")
    if country:
        conditions_sql.append("country = %s")
        params_sql.append(country)

    where_sql = " AND ".join(conditions_sql)
    offset = (page - 1) * per_page

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

    # Enrich each row with the egytech market reference (cache-backed; cheap after warmup).
    for row in rows:
        try:
            job = Job.from_db_row(row)
            row["market_salary"] = market_salary_for_job(job)
        except Exception:
            row["market_salary"] = None

    return {
        "jobs": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total else 0,
    }
```

Also remove the `min_salary` parameter from the function signature (line 18) and the corresponding query block (lines 37-39):

```python
async def search_jobs(
    request: Request,
    q: Optional[str] = Query(None, description="Search query"),
    topic: Optional[str] = Query(None, description="Filter by topic"),
    seniority: Optional[str] = Query(None, description="Filter by seniority"),
    remote: Optional[bool] = Query(None, description="Remote only"),
    country: Optional[str] = Query(None, description="Country ISO code"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=50, description="Items per page"),
):
```

- [ ] **Step 2: Replace JobCard salary display**

Replace `dashboard/src/components/JobCard.tsx` entirely:

```tsx
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
        <span>{job.location || 'Not specified'}</span>
        {job.is_remote && <span className="text-green-600">Remote</span>}
        {job.market_salary && (
          <span
            className="text-green-700 font-medium"
            title="Median range from egytech.fyi April 2024 survey for this role/level"
          >
            Market: {job.market_salary}
          </span>
        )}
        <span>{job.original_source || job.source}</span>
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
          Apply &rarr;
        </a>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify the dashboard builds**

```bash
cd dashboard && npm run build
```
Expected: build succeeds.

- [ ] **Step 4: Run backend tests to confirm /api/jobs/search still works**

Run: `pytest tests/ -v -k "not integration"`
Expected: All tests pass. (If tests reference `min_salary` query param on `/search`, update them — but a grep should show none in the existing test suite.)

```bash
grep -rn "min_salary" tests/
```
Expected: no hits in tests/ (only references should be in the plan/spec docs).

- [ ] **Step 5: Commit**

```bash
git add api/routes_jobs.py dashboard/src/components/JobCard.tsx
git commit -m "feat: replace per-job posting salary with egytech market reference"
```

---

## Task 8: Rewrite `/salary` bot command

**Files:**
- Modify: `bot/commands.py:281-320` (`cmd_salary`)

- [ ] **Step 1: Replace `cmd_salary`**

In `bot/commands.py`, replace the entire `cmd_salary` function (starting at line 281) with:

```python
async def cmd_salary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Egyptian salary insights via egytech.fyi. Usage: /salary <role> [seniority] [yoe]"""
    from core.egytech import get_stats
    from core.egytech_mapping import parse_role_query, SENIORITY_TO_LEVEL

    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: /salary <role> [seniority] [yoe]\n"
            "Examples:\n"
            "  /salary backend\n"
            "  /salary frontend mid\n"
            "  /salary devops senior 5\n\n"
            "Roles: backend, frontend, fullstack, mobile, devops, qa, security, "
            "data engineer, data scientist, embedded, ui ux, product manager"
        )
        return

    # Parse positional args: role (1+ words), seniority (single word from our enum), yoe (int).
    raw = list(args)
    yoe: int | None = None
    if raw and raw[-1].isdigit():
        yoe = int(raw.pop())

    seniority: str | None = None
    if raw and raw[-1].lower() in SENIORITY_TO_LEVEL:
        seniority = raw.pop().lower()

    role_text = " ".join(raw).strip().lower()
    title = parse_role_query(role_text)

    if not title:
        await update.message.reply_text(
            f"No data for '{role_text}'.\n\n"
            "Try one of: backend, frontend, fullstack, mobile, devops, qa, security, "
            "data engineer, data scientist, embedded, ui ux, product manager."
        )
        return

    level = SENIORITY_TO_LEVEL.get(seniority) if seniority else None
    yoe_from = yoe
    yoe_to = yoe + 1 if yoe is not None else None

    data = get_stats(title=title, level=level, yoe_from=yoe_from, yoe_to=yoe_to)
    if not data or "stats" not in data:
        await update.message.reply_text(
            f"No data for {title} / {seniority or 'any'} / yoe={yoe if yoe is not None else 'any'}.\n"
            "Try a broader filter."
        )
        return

    s = data["stats"]
    header = f"💰 {title}"
    if seniority:
        header += f" / {seniority}"
    if yoe is not None:
        header += f" / {yoe} yoe"
    header += f" · n={s.get('totalCount', 0)}"

    lines = [
        header,
        f"Median: EGP {s.get('median', 0):,}/mo",
        f"P20–P75: EGP {s.get('p20Compensation', 0):,} – {s.get('p75Compensation', 0):,}/mo",
        f"P90: EGP {s.get('p90Compensation', 0):,}/mo",
        "Source: egytech.fyi April 2024",
    ]
    await update.message.reply_text("\n".join(lines))
```

- [ ] **Step 2: Manual smoke test (sanity check, not a unit test)**

There's no async bot harness in the test suite. Skip automated testing for this task; manual verification happens in Task 11. The function is small enough that the type hints + the egytech client tests give sufficient coverage.

Run a syntax check:
```bash
python -c "import bot.commands"
```
Expected: no error.

- [ ] **Step 3: Commit**

```bash
git add bot/commands.py
git commit -m "feat(bot): rewrite /salary command to use egytech.fyi"
```

---

## Task 9: Update Telegram job message format

**Files:**
- Modify: `bot/sender.py:32-73` (`format_job_message`)
- Modify: `core/models.py:165-173` (`Job.salary_display` property)

- [ ] **Step 1: Replace `format_job_message`**

In `bot/sender.py`, replace the `format_job_message` function (lines 32-73) with:

```python
def format_job_message(job: Job) -> str:
    """Format a job as an HTML Telegram message."""
    from core.egytech import market_salary_for_job

    emoji = job.emoji
    title = _escape_html(job.title)
    company = _escape_html(job.company) if job.company else "Unknown"
    location = _escape_html(job.location) if job.location else "Not specified"
    source = _escape_html(job.display_source)

    lines = [
        f"{emoji} <b>{title}</b>",
        f"🏢 {company}",
        f"📍 {location}",
    ]

    market = market_salary_for_job(job)
    if market:
        lines.append(f"💰 Market: {_escape_html(market)}")

    if job.seniority and job.seniority != "mid":
        seniority_labels = {
            "intern": "🎓 Intern", "junior": "🌱 Junior",
            "senior": "👨‍💻 Senior", "lead": "⭐ Lead",
            "executive": "🏛️ Executive",
        }
        label = seniority_labels.get(job.seniority, "")
        if label:
            lines.append(label)
    if job.job_type:
        lines.append(f"📋 {_escape_html(job.job_type)}")
    if job.is_remote:
        lines.append("🌍 Remote")
    if job.is_easy_apply:
        lines.append("⚡ Easy Apply on LinkedIn")

    if job.posted_display:
        lines.append(f"🕐 Posted {job.posted_display}")

    lines.append("")
    apply_label = "⚡ Easy Apply on LinkedIn" if job.is_easy_apply else "Apply Now"
    lines.append(f'🔗 <a href="{job.url}">{apply_label}</a>')
    source_icon = SOURCE_ICON.get(job.source, "📡")
    lines.append(f"{source_icon} Source: {source}")

    return "\n".join(lines)
```

- [ ] **Step 2: Neutralize `Job.salary_display`**

In `core/models.py`, replace the `salary_display` property body (lines 165-173) with:

```python
    @property
    def salary_display(self) -> str:
        """Posting-derived salary is no longer surfaced; use core.egytech.market_salary_for_job instead."""
        return ""
```

This keeps the property for any caller that still references it (the dashboard search may). Returning an empty string makes the existing `if job.salary_display:` guards in any old code path simply skip rendering.

- [ ] **Step 3: Verify the test suite still passes**

Run: `pytest tests/ -v -k "not integration"`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add bot/sender.py core/models.py
git commit -m "feat(bot): replace posting salary with egytech market line in job messages"
```

---

## Task 10: Drop `min_salary` subscription filter

**Files:**
- Modify: `bot/notifications.py:71-74`
- Modify: `bot/commands.py:124-125`

- [ ] **Step 1: Remove `min_salary` from notification matcher**

In `bot/notifications.py`, delete lines 71-74 (the comment + the 3-line check):

```python
    # Check min salary
    min_salary = subs.get("min_salary")
    if min_salary and job.salary_max and job.salary_max < min_salary:
        return False
```

There should be nothing where those lines were — the function now ends at the keywords check.

- [ ] **Step 2: Remove `min_salary` from `/mysubs` output**

In `bot/commands.py`, delete lines 124-125 (the `if subs.get("min_salary"):` block):

```python
    if subs.get("min_salary"):
        lines.append(f"Min salary: ${subs['min_salary']:,}/year")
```

- [ ] **Step 3: Verify**

```bash
grep -rn "min_salary" bot/ api/
```
Expected: no hits.

Run: `pytest tests/ -v -k "not integration"`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add bot/notifications.py bot/commands.py
git commit -m "feat(bot): drop min_salary subscription filter"
```

---

## Task 11: Strip salary parsing from enrichment

**Files:**
- Modify: `core/enrichment.py:77-83`
- Delete: `core/salary_parser.py`
- Delete: `tests/test_salary_parser.py`
- Modify: `tests/test_enrichment.py:14-19, 57-60`

- [ ] **Step 1: Update `core/enrichment.py`**

Remove the `parse_salary` import (line 8) and the salary parsing block (lines 77-83). The full updated `enrich_job` function:

```python
def enrich_job(job: Job) -> Job:
    """
    Enrich a job with seniority, country, and topic routing.
    Returns the same Job object with fields updated (mutates in place).
    """
    # 1. Detect seniority (only if still default)
    if job.seniority == "mid":
        job.seniority = detect_seniority(job.title)

    # 2. Detect country (only if empty)
    if not job.country:
        job.country = detect_country(job.location)

    # 3. Route to topics (always recalculate)
    job.topics = _route_topics(job)

    return job
```

Also remove the import on line 8: `from core.salary_parser import parse_salary`.

- [ ] **Step 2: Update `tests/test_enrichment.py`**

Delete `test_parses_salary` (lines 14-19) and `test_no_salary_leaves_none` (lines 57-60). After deletion, the file should still have `test_detects_seniority`, `test_detects_country`, `test_routes_topics`, `test_general_fallback_when_no_topic_matched`, `test_fullstack_excludes_backend_and_frontend`, `test_fullstack_keeps_other_topics`, and `test_preserves_existing_fields`.

- [ ] **Step 3: Delete the parser and its tests**

```bash
rm core/salary_parser.py tests/test_salary_parser.py
```

- [ ] **Step 4: Verify nothing else imports the parser**

```bash
grep -rn "salary_parser\|parse_salary" --include="*.py" .
```
Expected: no hits.

- [ ] **Step 5: Run the full test suite**

Run: `pytest tests/ -v -k "not integration"`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add core/enrichment.py tests/test_enrichment.py
git rm core/salary_parser.py tests/test_salary_parser.py
git commit -m "feat: remove posting-derived salary parser (replaced by egytech.fyi)"
```

---

## Task 12: End-to-end verification

**Files:** none (pure verification)

- [ ] **Step 1: Run full backend test suite**

```bash
pytest tests/ -v -k "not integration"
```
Expected: all pass, no warnings about missing modules.

- [ ] **Step 2: Run the live integration test**

```bash
pytest -m integration tests/test_egytech_integration.py -v
```
Expected: 1 passed (requires internet).

- [ ] **Step 3: Build the dashboard**

```bash
cd dashboard && npm run build
```
Expected: build succeeds with no TypeScript errors.

- [ ] **Step 4: Search for stragglers**

```bash
grep -rn "salary_display\|salary_min\|salary_max\|salary_raw\|salary_currency\|min_salary" --include="*.py" --include="*.ts" --include="*.tsx" . \
  | grep -v "docs/superpowers" \
  | grep -v "tests/test_db" \
  | grep -v "supabase/migrations"
```

Expected hits (legitimate keepers — verify):
- `core/models.py` — field definitions on the dataclass + neutralized `salary_display` property.
- `core/db.py` — column reads/writes (we kept the columns).
- `tests/test_db.py` — fixtures using `salary_min/salary_max: None`.
- `dashboard/src/types.ts` — `salary_min`/`salary_max`/`salary_raw`/`salary_currency` on the `Job` interface (kept for back-compat with old data).

Anything else, especially live readers/writers, indicates an incomplete cleanup — investigate.

- [ ] **Step 5: Manual smoke (optional, requires running services)**

If you can run the bot and dashboard locally:
1. Start the API: `uvicorn server:app`.
2. `curl http://localhost:8000/api/stats/salary?role=backend&seniority=mid` → expect `matched: true` with EGP figures.
3. `curl "http://localhost:8000/api/jobs/search?country=EG&per_page=5"` → confirm at least one job has `market_salary: "EGP …"` populated.
4. Start the dashboard: `cd dashboard && npm run dev` → load Salary page; change role/seniority/yoe filters and confirm the histogram updates.
5. Send `/salary backend mid` to the bot in DM → expect EGP figures with source attribution.

- [ ] **Step 6: Final commit (only if anything was found and fixed)**

If steps 1–5 surface no issues, no commit is needed for this task.

---

## Self-Review

**Spec coverage (each section → task):**
- Architecture / `core/egytech.py` → Task 1 ✓
- Architecture / `core/egytech_mapping.py` → Task 2 ✓
- `/api/stats/salary` rewrite → Task 4 ✓
- Salary dashboard page rewrite → Tasks 5 + 6 ✓
- `/salary` bot command rewrite → Task 8 ✓
- Per-job card salary (Egypt-only egytech reference) → Task 7 ✓
- Enrichment pipeline cleanup → Task 11 ✓
- Job model & DB (keep columns, stop populating) → Task 9 (neutralized salary_display) + Task 11 ✓
- Subscription `min_salary` filter removal → Task 10 ✓
- Telegram message format change → Task 9 ✓
- Tests (client unit, mapping unit, integration, updated enrichment) → Tasks 1, 2, 3, 11 ✓

**Type/method consistency:**
- `get_stats` signature consistent across all callers (Tasks 1, 4, 7, 8, 9).
- `market_salary_for_job(job: Job) -> str | None` signature used identically in Tasks 7, 9.
- `parse_role_query` returns `Optional[str]` — consumers (Tasks 4, 8) handle `None`.
- Cache key `(title, level, yoe_from, yoe_to)` consistent with `get_stats` parameter order.
- `SalaryStats` TypeScript interface (Task 5) matches FastAPI response shape (Task 4) — fields: `currency`, `period`, `source`, `stats{sample_size,median,p20,p75,p90}`, `buckets[{label,count}]`, `filters`, `matched`.
- `Job.market_salary` field added in Task 5, populated by Task 7 backend, rendered by Task 7 frontend.

**No placeholders found.** Every code block contains the exact code to write or replace. No "TODO", no "implement later", no "similar to Task N".

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-25-egytech-salaries.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
