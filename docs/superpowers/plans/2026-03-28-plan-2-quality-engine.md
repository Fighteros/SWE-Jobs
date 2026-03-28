# Plan 2: Quality Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the quality improvement modules — salary parsing, seniority detection, country detection, weighted keyword scoring, and fuzzy deduplication — so jobs are cleaner, better classified, and free of cross-source duplicates.

**Architecture:** Five independent modules in `core/` that each take a `Job` and enrich or score it. The filtering pipeline chains them: parse salary → detect seniority → detect country → score keywords → fuzzy dedup. Each module is pure logic with no DB dependency (except dedup which queries `pg_trgm`).

**Tech Stack:** Python 3.11, regex, psycopg2 (for pg_trgm dedup), pytest

**Spec:** `docs/superpowers/specs/2026-03-28-v2-redesign-design.md` (Section 2)

**Depends on:** Plan 1 (core/models.py, core/db.py, core/keywords.py, core/geo.py)
**Blocks:** Plans 3, 4, 6

---

## File Structure

```
core/
├── salary_parser.py       # Extract min/max/currency from salary strings
├── seniority.py           # Detect seniority level from job title
├── country_detector.py    # Detect country from location string
├── filtering.py           # Weighted keyword scoring + geo filter (replaces old models.py filtering)
└── dedup.py               # Fuzzy dedup using pg_trgm (replaces old dedup.py)
tests/
├── test_salary_parser.py
├── test_seniority.py
├── test_country_detector.py
├── test_filtering.py
└── test_dedup.py
```

---

### Task 1: Salary Parser

**Files:**
- Create: `core/salary_parser.py`
- Create: `tests/test_salary_parser.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_salary_parser.py
"""Tests for salary extraction and normalization."""

from core.salary_parser import parse_salary


class TestParseSalaryUSD:
    def test_range_with_dollar_sign(self):
        result = parse_salary("$80,000 - $120,000")
        assert result == {"min": 80000, "max": 120000, "currency": "USD"}

    def test_range_with_k_shorthand(self):
        result = parse_salary("$80k - $120k")
        assert result == {"min": 80000, "max": 120000, "currency": "USD"}

    def test_single_value(self):
        result = parse_salary("$100,000/year")
        assert result == {"min": 100000, "max": 100000, "currency": "USD"}

    def test_usd_prefix(self):
        result = parse_salary("USD 50000-60000")
        assert result == {"min": 50000, "max": 60000, "currency": "USD"}

    def test_range_no_spaces(self):
        result = parse_salary("$70000-$90000")
        assert result == {"min": 70000, "max": 90000, "currency": "USD"}


class TestParseSalaryOtherCurrencies:
    def test_eur(self):
        result = parse_salary("EUR 50k-70k")
        assert result == {"min": 50000, "max": 70000, "currency": "EUR"}

    def test_euro_sign(self):
        result = parse_salary("€50,000 - €70,000")
        assert result == {"min": 50000, "max": 70000, "currency": "EUR"}

    def test_gbp(self):
        result = parse_salary("£45,000/year")
        assert result == {"min": 45000, "max": 45000, "currency": "GBP"}

    def test_gbp_range(self):
        result = parse_salary("GBP 40,000 - 60,000")
        assert result == {"min": 40000, "max": 60000, "currency": "GBP"}


class TestParseSalaryPeriodConversion:
    def test_monthly_to_yearly(self):
        result = parse_salary("EGP 15,000 - 25,000/month")
        assert result == {"min": 180000, "max": 300000, "currency": "EGP"}

    def test_hourly_to_yearly(self):
        result = parse_salary("$50/hour")
        assert result == {"min": 104000, "max": 104000, "currency": "USD"}

    def test_hourly_range(self):
        result = parse_salary("$40 - $60/hr")
        assert result == {"min": 83200, "max": 124800, "currency": "USD"}


class TestParseSalaryEdgeCases:
    def test_empty_string(self):
        assert parse_salary("") is None

    def test_no_salary(self):
        assert parse_salary("Competitive") is None

    def test_none_input(self):
        assert parse_salary(None) is None

    def test_unparseable(self):
        assert parse_salary("Great benefits package") is None

    def test_sar_currency(self):
        result = parse_salary("SAR 10,000 - 15,000/month")
        assert result == {"min": 120000, "max": 180000, "currency": "SAR"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd G:/projects/SWE-Jobs && python -m pytest tests/test_salary_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.salary_parser'`

- [ ] **Step 3: Write the implementation**

```python
# core/salary_parser.py
"""
Salary extraction and normalization.
Parses salary strings into structured min/max/currency data.
Normalizes to yearly amounts.
"""

import re
from typing import Optional

# Currency detection patterns
_CURRENCY_MAP = {
    "$": "USD", "usd": "USD",
    "€": "EUR", "eur": "EUR", "euro": "EUR",
    "£": "GBP", "gbp": "GBP",
    "egp": "EGP",
    "sar": "SAR",
    "aed": "AED",
    "inr": "INR",
    "cad": "CAD",
    "aud": "AUD",
    "chf": "CHF",
    "pln": "PLN",
    "brl": "BRL",
    "sgd": "SGD",
}

# Period multipliers to normalize to yearly
_PERIOD_MULTIPLIERS = {
    "hour": 2080, "hr": 2080, "hourly": 2080,
    "month": 12, "monthly": 12, "mo": 12,
    "week": 52, "weekly": 52, "wk": 52,
    "year": 1, "yearly": 1, "annual": 1, "annually": 1, "yr": 1, "pa": 1,
}

# Regex to extract numbers (with optional k/K suffix)
_NUMBER_RE = re.compile(r'[\d,]+(?:\.\d+)?[kK]?')


def _parse_number(s: str) -> Optional[int]:
    """Parse a number string like '80,000', '80k', '80K' into an integer."""
    s = s.strip().replace(",", "")
    multiplier = 1
    if s.lower().endswith("k"):
        multiplier = 1000
        s = s[:-1]
    try:
        return int(float(s) * multiplier)
    except (ValueError, TypeError):
        return None


def _detect_currency(text: str) -> str:
    """Detect currency from text. Returns currency code or 'USD' as default."""
    text_lower = text.lower()
    # Check symbol first
    for symbol, code in _CURRENCY_MAP.items():
        if symbol in text_lower:
            return code
    return "USD"


def _detect_period(text: str) -> int:
    """Detect pay period and return yearly multiplier."""
    text_lower = text.lower()
    for period, mult in _PERIOD_MULTIPLIERS.items():
        if period in text_lower:
            return mult
    # Default: if numbers are small (< 500), assume hourly; if < 20000, monthly; else yearly
    return 1  # Will be adjusted after number extraction


def _infer_period_from_value(value: int) -> int:
    """Infer the pay period from the magnitude of the value."""
    if value < 500:
        return 2080  # Hourly
    elif value < 20000:
        return 12  # Monthly
    return 1  # Yearly


def parse_salary(raw: Optional[str]) -> Optional[dict]:
    """
    Parse a salary string into structured data.

    Returns: {"min": int, "max": int, "currency": str} or None if unparseable.
    All values normalized to yearly.
    """
    if not raw or not isinstance(raw, str):
        return None

    raw = raw.strip()
    if not raw:
        return None

    # Extract all numbers
    numbers = _NUMBER_RE.findall(raw)
    if not numbers:
        return None

    parsed = [_parse_number(n) for n in numbers]
    parsed = [n for n in parsed if n is not None and n > 0]

    if not parsed:
        return None

    currency = _detect_currency(raw)

    # Detect explicit period from text
    text_lower = raw.lower()
    period_mult = 1
    explicit_period = False
    for period, mult in _PERIOD_MULTIPLIERS.items():
        if period in text_lower:
            period_mult = mult
            explicit_period = True
            break

    if len(parsed) >= 2:
        sal_min, sal_max = parsed[0], parsed[1]
        # Ensure min <= max
        if sal_min > sal_max:
            sal_min, sal_max = sal_max, sal_min
    else:
        sal_min = sal_max = parsed[0]

    # Infer period if not explicit
    if not explicit_period:
        period_mult = _infer_period_from_value(sal_min)

    sal_min = sal_min * period_mult
    sal_max = sal_max * period_mult

    return {"min": sal_min, "max": sal_max, "currency": currency}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd G:/projects/SWE-Jobs && python -m pytest tests/test_salary_parser.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add core/salary_parser.py tests/test_salary_parser.py
git commit -m "feat: add salary parser with currency detection and period normalization"
```

---

### Task 2: Seniority Detection

**Files:**
- Create: `core/seniority.py`
- Create: `tests/test_seniority.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_seniority.py
"""Tests for seniority level detection."""

from core.seniority import detect_seniority


class TestSeniorityDetection:
    def test_intern(self):
        assert detect_seniority("Software Engineering Intern") == "intern"

    def test_internship(self):
        assert detect_seniority("Python Internship") == "intern"

    def test_trainee(self):
        assert detect_seniority("Trainee Developer") == "intern"

    def test_coop(self):
        assert detect_seniority("Co-op Software Engineer") == "intern"

    def test_junior(self):
        assert detect_seniority("Junior Python Developer") == "junior"

    def test_jr(self):
        assert detect_seniority("Jr. Software Engineer") == "junior"

    def test_entry_level(self):
        assert detect_seniority("Entry Level Developer") == "junior"

    def test_fresh_grad(self):
        assert detect_seniority("Fresh Graduate Developer") == "junior"

    def test_associate(self):
        assert detect_seniority("Associate Software Engineer") == "junior"

    def test_senior(self):
        assert detect_seniority("Senior Backend Developer") == "senior"

    def test_sr(self):
        assert detect_seniority("Sr. Python Engineer") == "senior"

    def test_lead(self):
        assert detect_seniority("Lead Software Engineer") == "lead"

    def test_principal(self):
        assert detect_seniority("Principal Engineer") == "lead"

    def test_staff(self):
        assert detect_seniority("Staff Software Engineer") == "lead"

    def test_architect(self):
        assert detect_seniority("Solutions Architect") == "lead"

    def test_cto(self):
        assert detect_seniority("CTO") == "executive"

    def test_vp_engineering(self):
        assert detect_seniority("VP of Engineering") == "executive"

    def test_head_of(self):
        assert detect_seniority("Head of Engineering") == "executive"

    def test_director(self):
        assert detect_seniority("Director of Engineering") == "executive"

    def test_mid_default(self):
        assert detect_seniority("Python Developer") == "mid"

    def test_mid_explicit(self):
        assert detect_seniority("Mid-Level Software Engineer") == "mid"

    def test_senior_beats_intern_keyword(self):
        """'Senior' should win over embedded 'intern' in 'internal'."""
        assert detect_seniority("Senior Internal Tools Engineer") == "senior"

    def test_empty(self):
        assert detect_seniority("") == "mid"

    def test_none(self):
        assert detect_seniority(None) == "mid"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd G:/projects/SWE-Jobs && python -m pytest tests/test_seniority.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# core/seniority.py
"""
Seniority level detection from job titles.
"""

import re
from typing import Optional

# Ordered by priority: higher priority patterns are checked first.
# Each tuple: (seniority_level, list_of_patterns)
# Patterns use word boundaries to avoid false matches (e.g. "internal" matching "intern").
_SENIORITY_PATTERNS = [
    ("executive", [
        r"\bcto\b", r"\bvp\b", r"\bvice president\b",
        r"\bhead of\b", r"\bdirector\b",
        r"\bchief\b",
    ]),
    ("lead", [
        r"\blead\b", r"\bprincipal\b", r"\bstaff\b",
        r"\barchitect\b",
    ]),
    ("senior", [
        r"\bsenior\b", r"\bsr\.?\b", r"\bexperienced\b",
    ]),
    ("intern", [
        r"\bintern\b", r"\binternship\b", r"\btrainee\b",
        r"\bco-op\b", r"\bcoop\b",
    ]),
    ("junior", [
        r"\bjunior\b", r"\bjr\.?\b", r"\bentry[\s-]?level\b",
        r"\bfresh\s*grad", r"\bassociate\b",
    ]),
    ("mid", [
        r"\bmid[\s-]?level\b", r"\bintermediate\b",
    ]),
]


def detect_seniority(title: Optional[str]) -> str:
    """
    Detect seniority level from a job title.

    Returns one of: 'intern', 'junior', 'mid', 'senior', 'lead', 'executive'.
    Defaults to 'mid' if no pattern matches.
    """
    if not title:
        return "mid"

    title_lower = title.lower()

    for level, patterns in _SENIORITY_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, title_lower):
                return level

    return "mid"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd G:/projects/SWE-Jobs && python -m pytest tests/test_seniority.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add core/seniority.py tests/test_seniority.py
git commit -m "feat: add seniority detection with word-boundary patterns"
```

---

### Task 3: Country Detection

**Files:**
- Create: `core/country_detector.py`
- Create: `tests/test_country_detector.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_country_detector.py
"""Tests for country detection from location strings."""

from core.country_detector import detect_country


class TestCountryDetection:
    def test_egypt_english(self):
        assert detect_country("Cairo, Egypt") == "EG"

    def test_egypt_arabic(self):
        assert detect_country("القاهرة، مصر") == "EG"

    def test_egypt_city(self):
        assert detect_country("Alexandria") == "EG"

    def test_saudi_english(self):
        assert detect_country("Riyadh, Saudi Arabia") == "SA"

    def test_saudi_arabic(self):
        assert detect_country("الرياض") == "SA"

    def test_saudi_ksa(self):
        assert detect_country("Jeddah, KSA") == "SA"

    def test_us(self):
        assert detect_country("San Francisco, CA, United States") == "US"

    def test_us_short(self):
        assert detect_country("New York, USA") == "US"

    def test_uk(self):
        assert detect_country("London, United Kingdom") == "GB"

    def test_uk_short(self):
        assert detect_country("Manchester, UK") == "GB"

    def test_germany(self):
        assert detect_country("Berlin, Germany") == "DE"

    def test_remote(self):
        assert detect_country("Remote") == ""

    def test_anywhere(self):
        assert detect_country("Anywhere") == ""

    def test_empty(self):
        assert detect_country("") == ""

    def test_none(self):
        assert detect_country(None) == ""

    def test_canada(self):
        assert detect_country("Toronto, Canada") == "CA"

    def test_india(self):
        assert detect_country("Bangalore, India") == "IN"

    def test_uae(self):
        assert detect_country("Dubai, UAE") == "AE"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd G:/projects/SWE-Jobs && python -m pytest tests/test_country_detector.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# core/country_detector.py
"""
Country detection from job location strings.
Pattern-based, no external geocoding API needed.
"""

from typing import Optional
from core.geo import EGYPT_PATTERNS, SAUDI_PATTERNS

# Country pattern map: {ISO code: set of patterns}
# Egypt and Saudi use the existing detailed patterns from core.geo
# Other countries use country names, abbreviations, and major cities
_COUNTRY_PATTERNS: dict[str, set[str]] = {
    "EG": EGYPT_PATTERNS,
    "SA": SAUDI_PATTERNS,
    "US": {
        "united states", "usa", "u.s.a", "u.s.", "us-remote",
        "new york", "san francisco", "los angeles", "chicago", "seattle",
        "austin", "boston", "denver", "atlanta", "dallas", "houston",
        "miami", "philadelphia", "phoenix", "san jose", "san diego",
        "washington dc", "washington, dc",
    },
    "GB": {
        "united kingdom", "uk", "england", "scotland", "wales",
        "london", "manchester", "birmingham", "leeds", "bristol",
        "edinburgh", "glasgow", "cambridge", "oxford",
    },
    "DE": {
        "germany", "deutschland",
        "berlin", "munich", "frankfurt", "hamburg", "cologne",
        "stuttgart", "dusseldorf",
    },
    "CA": {
        "canada",
        "toronto", "vancouver", "montreal", "ottawa", "calgary",
    },
    "FR": {
        "france",
        "paris", "lyon", "marseille", "toulouse",
    },
    "NL": {
        "netherlands", "holland",
        "amsterdam", "rotterdam", "the hague", "utrecht",
    },
    "IN": {
        "india",
        "bangalore", "bengaluru", "mumbai", "delhi", "hyderabad",
        "pune", "chennai", "kolkata", "noida", "gurgaon", "gurugram",
    },
    "AE": {
        "uae", "united arab emirates",
        "dubai", "abu dhabi", "sharjah",
    },
    "AU": {
        "australia",
        "sydney", "melbourne", "brisbane", "perth",
    },
    "SG": {"singapore"},
    "IE": {"ireland", "dublin"},
    "ES": {"spain", "madrid", "barcelona"},
    "IT": {"italy", "milan", "rome"},
    "PT": {"portugal", "lisbon", "porto"},
    "PL": {"poland", "warsaw", "krakow", "wroclaw"},
    "SE": {"sweden", "stockholm", "gothenburg"},
    "CH": {"switzerland", "zurich", "geneva", "basel"},
    "JP": {"japan", "tokyo", "osaka"},
    "KR": {"south korea", "korea", "seoul"},
    "BR": {"brazil", "sao paulo", "rio de janeiro"},
    "IL": {"israel", "tel aviv", "jerusalem"},
    "NG": {"nigeria", "lagos", "abuja"},
    "KE": {"kenya", "nairobi"},
    "ZA": {"south africa", "cape town", "johannesburg"},
    "TR": {"turkey", "turkiye", "istanbul", "ankara"},
    "RO": {"romania", "bucharest"},
    "UA": {"ukraine", "kyiv"},
    "AR": {"argentina", "buenos aires"},
    "MX": {"mexico", "mexico city", "guadalajara"},
    "CO": {"colombia", "bogota", "medellin"},
}


def detect_country(location: Optional[str]) -> str:
    """
    Detect country ISO code from a location string.

    Returns 2-letter ISO code (e.g. 'US', 'EG') or empty string if unknown.
    """
    if not location:
        return ""

    loc_lower = location.lower().strip()

    if not loc_lower:
        return ""

    for iso_code, patterns in _COUNTRY_PATTERNS.items():
        for pattern in patterns:
            if pattern in loc_lower:
                return iso_code

    return ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd G:/projects/SWE-Jobs && python -m pytest tests/test_country_detector.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add core/country_detector.py tests/test_country_detector.py
git commit -m "feat: add country detector with 30+ country patterns"
```

---

### Task 4: Weighted Keyword Scoring

**Files:**
- Create: `core/filtering.py`
- Create: `tests/test_filtering.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_filtering.py
"""Tests for weighted keyword scoring and geo filtering."""

from core.filtering import score_job, is_programming_job, passes_geo_filter
from core.models import Job


def _make_job(**kwargs) -> Job:
    defaults = {"title": "", "company": "", "location": "", "url": "http://x.com", "source": "test"}
    defaults.update(kwargs)
    return Job(**defaults)


class TestScoreJob:
    def test_exact_word_match_scores_10(self):
        job = _make_job(title="Senior Python Developer")
        score = score_job(job)
        assert score >= 10  # "developer" exact word match

    def test_tag_match_scores_8(self):
        job = _make_job(title="Something", tags=["python"])
        score = score_job(job)
        assert score >= 8

    def test_partial_match_scores_3(self):
        job = _make_job(title="Software Engineering Team")
        score = score_job(job)
        # "engineering" partially matches "engineer" but not as a whole word
        assert score >= 3

    def test_exclude_rejects(self):
        job = _make_job(title="Sales Engineer")
        assert is_programming_job(job) is False

    def test_marketing_rejected(self):
        job = _make_job(title="Marketing Developer Tools")
        assert is_programming_job(job) is False

    def test_real_job_passes(self):
        job = _make_job(title="Senior Python Developer", tags=["python", "django"])
        assert is_programming_job(job) is True

    def test_react_developer_passes(self):
        job = _make_job(title="React Developer", tags=["react", "javascript"])
        assert is_programming_job(job) is True

    def test_no_keywords_fails(self):
        job = _make_job(title="Office Manager")
        assert is_programming_job(job) is False

    def test_threshold_boundary(self):
        """A single exact word match should pass (score=10, threshold=10)."""
        job = _make_job(title="Software Developer")
        assert is_programming_job(job) is True


class TestGeoFilter:
    def test_egypt_passes(self):
        job = _make_job(title="Dev", location="Cairo, Egypt")
        assert passes_geo_filter(job) is True

    def test_saudi_passes(self):
        job = _make_job(title="Dev", location="Riyadh, Saudi Arabia")
        assert passes_geo_filter(job) is True

    def test_remote_passes(self):
        job = _make_job(title="Dev", location="Remote", is_remote=True)
        assert passes_geo_filter(job) is True

    def test_remote_only_source_passes(self):
        job = _make_job(title="Dev", location="", source="remotive")
        assert passes_geo_filter(job) is True

    def test_onsite_us_fails(self):
        job = _make_job(title="Dev", location="New York, USA", source="jsearch")
        assert passes_geo_filter(job) is False

    def test_remote_keyword_in_location(self):
        job = _make_job(title="Dev", location="Remote - Worldwide")
        assert passes_geo_filter(job) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd G:/projects/SWE-Jobs && python -m pytest tests/test_filtering.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# core/filtering.py
"""
Weighted keyword scoring and geo-based filtering.
Replaces the old boolean contains-match with a scoring system.
"""

import re
import logging
from typing import Optional

from core.keywords import (
    INCLUDE_KEYWORDS, EXCLUDE_KEYWORDS,
    SCORE_EXACT_WORD, SCORE_TAG_MATCH, SCORE_PARTIAL, SCORE_EXCLUDE,
    SCORE_THRESHOLD,
)
from core.geo import (
    EGYPT_PATTERNS, SAUDI_PATTERNS, REMOTE_PATTERNS,
    REMOTE_ONLY_SOURCES,
)
from core.models import Job, _flatten_tags

log = logging.getLogger(__name__)


def _word_boundary_pattern(keyword: str) -> re.Pattern:
    """Create a compiled regex for whole-word matching."""
    escaped = re.escape(keyword)
    return re.compile(rf"\b{escaped}\b", re.IGNORECASE)


# Pre-compile word boundary patterns for include keywords
_INCLUDE_PATTERNS = [(kw, _word_boundary_pattern(kw)) for kw in INCLUDE_KEYWORDS]
_EXCLUDE_PATTERNS = [(kw, _word_boundary_pattern(kw)) for kw in EXCLUDE_KEYWORDS]


def score_job(job: Job) -> int:
    """
    Score a job based on keyword matches.

    Scoring:
    - Exact word match in title: +10 (SCORE_EXACT_WORD)
    - Tag/skill match: +8 (SCORE_TAG_MATCH)
    - Partial substring match: +3 (SCORE_PARTIAL)
    - Exclude keyword match: -20 (SCORE_EXCLUDE) — instant reject

    Returns the total score.
    """
    title = job.title or ""
    tags_str = _flatten_tags(job.tags).lower()
    tags_set = {t.lower() for t in (job.tags or []) if isinstance(t, str)}
    title_lower = title.lower()

    score = 0
    matched_keywords = set()

    # Check excludes first — any match is instant reject
    for kw, pattern in _EXCLUDE_PATTERNS:
        if pattern.search(title_lower) or kw.lower() in tags_str:
            return SCORE_EXCLUDE

    # Score includes
    for kw, pattern in _INCLUDE_PATTERNS:
        kw_lower = kw.lower()

        # Exact word match in title
        if pattern.search(title):
            if kw_lower not in matched_keywords:
                score += SCORE_EXACT_WORD
                matched_keywords.add(kw_lower)
                continue

        # Tag match
        if kw_lower in tags_set:
            if kw_lower not in matched_keywords:
                score += SCORE_TAG_MATCH
                matched_keywords.add(kw_lower)
                continue

        # Partial substring match in title
        if kw_lower in title_lower:
            if kw_lower not in matched_keywords:
                score += SCORE_PARTIAL
                matched_keywords.add(kw_lower)

    return score


def is_programming_job(job: Job) -> bool:
    """Check if job passes the keyword scoring threshold."""
    return score_job(job) >= SCORE_THRESHOLD


# ─── Geo Filtering ────────────────────────────────────────

def _is_in_egypt(location: str) -> bool:
    loc = location.lower().strip()
    return any(p in loc for p in EGYPT_PATTERNS)


def _is_in_saudi(location: str) -> bool:
    loc = location.lower().strip()
    return any(p in loc for p in SAUDI_PATTERNS)


def _is_remote(job: Job) -> bool:
    if job.is_remote:
        return True
    combined = f"{job.title} {job.location} {job.job_type} {_flatten_tags(job.tags)}".lower()
    return any(p in combined for p in REMOTE_PATTERNS)


def passes_geo_filter(job: Job) -> bool:
    """
    Geo-filtering:
    - Remote-only sources: auto-pass
    - Egypt/Saudi locations: pass regardless
    - Remote jobs: pass
    - Onsite outside Egypt/Saudi: reject
    """
    if job.source in REMOTE_ONLY_SOURCES:
        return True
    if _is_in_egypt(job.location) or _is_in_saudi(job.location):
        return True
    if _is_remote(job):
        return True
    return False


def filter_jobs(jobs: list[Job]) -> list[Job]:
    """Apply all filters: keyword scoring + geo filter."""
    filtered = []
    for job in jobs:
        if not job.title or not job.url:
            continue
        if not is_programming_job(job):
            continue
        if not passes_geo_filter(job):
            continue
        filtered.append(job)
    return filtered
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd G:/projects/SWE-Jobs && python -m pytest tests/test_filtering.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add core/filtering.py tests/test_filtering.py
git commit -m "feat: add weighted keyword scoring and geo filtering"
```

---

### Task 5: Fuzzy Deduplication

**Files:**
- Create: `core/dedup.py`
- Create: `tests/test_dedup.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_dedup.py
"""Tests for fuzzy deduplication."""

from unittest.mock import patch
from core.dedup import deduplicate_batch, is_duplicate_url, normalize_url
from core.models import Job


def _make_job(**kwargs) -> Job:
    defaults = {"title": "", "company": "", "location": "", "url": "http://x.com", "source": "test"}
    defaults.update(kwargs)
    return Job(**defaults)


class TestNormalizeUrl:
    def test_strips_utm(self):
        assert normalize_url("http://x.com/job?utm_source=email") == "http://x.com/job"

    def test_strips_trailing_slash(self):
        assert normalize_url("http://x.com/job/") == "http://x.com/job"

    def test_lowercases(self):
        assert normalize_url("HTTP://X.COM/Job") == "http://x.com/job"


class TestIsDuplicateUrl:
    def test_exact_match(self):
        seen = {"http://x.com/job/1", "http://x.com/job/2"}
        assert is_duplicate_url("http://x.com/job/1", seen) is True

    def test_no_match(self):
        seen = {"http://x.com/job/1"}
        assert is_duplicate_url("http://x.com/job/99", seen) is False

    def test_normalized_match(self):
        seen = {"http://x.com/job/1"}
        assert is_duplicate_url("http://x.com/job/1?utm_source=email", seen) is True


class TestDeduplicateBatch:
    def test_removes_within_batch_dupes(self):
        jobs = [
            _make_job(title="Dev", url="http://x.com/1"),
            _make_job(title="Dev", url="http://x.com/1"),
        ]
        result = deduplicate_batch(jobs, seen_ids=set())
        assert len(result) == 1

    def test_removes_seen_jobs(self):
        jobs = [
            _make_job(title="Dev", url="http://x.com/1"),
            _make_job(title="Dev 2", url="http://x.com/2"),
        ]
        result = deduplicate_batch(jobs, seen_ids={"http://x.com/1"})
        assert len(result) == 1
        assert result[0].url == "http://x.com/2"

    def test_empty_batch(self):
        assert deduplicate_batch([], set()) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd G:/projects/SWE-Jobs && python -m pytest tests/test_dedup.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# core/dedup.py
"""
Fuzzy deduplication using three layers:
1. Exact URL match
2. Title + Company similarity (pg_trgm, when DB is available)
3. Batch-internal dedup

Designed to work with or without a database connection.
When DB is unavailable (e.g. unit tests), only URL and batch dedup run.
"""

import logging
from typing import Optional
from core.models import Job

log = logging.getLogger(__name__)


def normalize_url(url: str) -> str:
    """Normalize a URL for comparison: strip tracking params, trailing slash, lowercase."""
    if not url:
        return ""
    clean = url.split("?utm")[0].split("&utm")[0]
    clean = clean.rstrip("/").lower()
    return clean


def is_duplicate_url(url: str, seen_ids: set) -> bool:
    """Check if a normalized URL is in the seen set."""
    return normalize_url(url) in seen_ids


def deduplicate_batch(jobs: list[Job], seen_ids: set) -> list[Job]:
    """
    Deduplicate a batch of jobs against seen IDs and within the batch itself.
    Uses URL-based exact matching. Does NOT use DB (fuzzy dedup is separate).

    Args:
        jobs: List of jobs to deduplicate
        seen_ids: Set of already-seen unique_ids (normalized URLs or title|company hashes)

    Returns: List of new, unique jobs
    """
    new_jobs = []
    batch_ids = set()

    for job in jobs:
        uid = job.unique_id
        if uid in seen_ids:
            continue
        if uid in batch_ids:
            continue
        batch_ids.add(uid)
        new_jobs.append(job)

    log.info(f"Dedup: {len(jobs)} total -> {len(new_jobs)} new (batch)")
    return new_jobs


def fuzzy_dedup_against_db(job: Job, db_module=None) -> Optional[int]:
    """
    Check if a job is a fuzzy duplicate of an existing DB job.
    Uses pg_trgm similarity on title + exact company match.

    Args:
        job: The job to check
        db_module: The core.db module (passed to avoid circular imports)

    Returns: ID of the existing duplicate job, or None if no duplicate found.
    """
    if db_module is None:
        return None

    try:
        rows = db_module._fetchall(
            """SELECT id, title, company, salary_raw, tags
               FROM jobs
               WHERE created_at > now() - make_interval(days := 7)
                 AND lower(company) = lower(%s)
                 AND similarity(title, %s) > 0.7
               LIMIT 1""",
            (job.company, job.title),
        )
        if rows:
            existing = rows[0]
            log.debug(
                f"Fuzzy dupe found: '{job.title}' ~ '{existing['title']}' "
                f"(company: {job.company})"
            )
            return existing["id"]
    except Exception as e:
        log.warning(f"Fuzzy dedup query failed: {e}")

    return None


def should_replace_existing(new_job: Job, existing_row: dict) -> bool:
    """
    Determine if the new job has more data than the existing one.
    Used when a fuzzy duplicate is found to decide which version to keep.
    """
    score_new = 0
    score_existing = 0

    # Salary data
    if new_job.salary_raw:
        score_new += 1
    if existing_row.get("salary_raw"):
        score_existing += 1

    # Tags
    if new_job.tags:
        score_new += len(new_job.tags)
    if existing_row.get("tags"):
        score_existing += len(existing_row["tags"])

    return score_new > score_existing
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd G:/projects/SWE-Jobs && python -m pytest tests/test_dedup.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add core/dedup.py tests/test_dedup.py
git commit -m "feat: add fuzzy dedup with URL matching and pg_trgm support"
```

---

### Task 6: Job Enrichment Pipeline

**Files:**
- Create: `core/enrichment.py`
- Create: `tests/test_enrichment.py`

This module chains all quality modules together: salary → seniority → country → topics.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_enrichment.py
"""Tests for the job enrichment pipeline."""

from core.enrichment import enrich_job
from core.models import Job


def _make_job(**kwargs) -> Job:
    defaults = {"title": "", "company": "", "location": "", "url": "http://x.com", "source": "test"}
    defaults.update(kwargs)
    return Job(**defaults)


class TestEnrichJob:
    def test_parses_salary(self):
        job = _make_job(title="Dev", salary_raw="$80,000 - $120,000")
        enriched = enrich_job(job)
        assert enriched.salary_min == 80000
        assert enriched.salary_max == 120000
        assert enriched.salary_currency == "USD"

    def test_detects_seniority(self):
        job = _make_job(title="Senior Python Developer")
        enriched = enrich_job(job)
        assert enriched.seniority == "senior"

    def test_detects_country(self):
        job = _make_job(title="Dev", location="Cairo, Egypt")
        enriched = enrich_job(job)
        assert enriched.country == "EG"

    def test_routes_topics(self):
        job = _make_job(title="Flutter Developer", location="Cairo, Egypt")
        enriched = enrich_job(job)
        assert "mobile" in enriched.topics
        assert "egypt" in enriched.topics
        assert "general" in enriched.topics

    def test_no_salary_leaves_none(self):
        job = _make_job(title="Dev", salary_raw="Competitive")
        enriched = enrich_job(job)
        assert enriched.salary_min is None

    def test_preserves_existing_fields(self):
        job = _make_job(title="Dev", company="Acme", tags=["python"])
        enriched = enrich_job(job)
        assert enriched.company == "Acme"
        assert enriched.tags == ["python"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd G:/projects/SWE-Jobs && python -m pytest tests/test_enrichment.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# core/enrichment.py
"""
Job enrichment pipeline.
Chains: salary parsing -> seniority detection -> country detection -> topic routing.
"""

import logging
from core.models import Job, _flatten_tags
from core.salary_parser import parse_salary
from core.seniority import detect_seniority
from core.country_detector import detect_country
from core.channels import CHANNELS
from core.geo import EGYPT_PATTERNS, SAUDI_PATTERNS

log = logging.getLogger(__name__)


def _match_keywords(text: str, keywords: list[str]) -> bool:
    """Check if lowered text contains any of the keywords."""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def _is_egypt_location(location: str) -> bool:
    loc = location.lower()
    return any(p in loc for p in EGYPT_PATTERNS)


def _is_saudi_location(location: str) -> bool:
    loc = location.lower()
    return any(p in loc for p in SAUDI_PATTERNS)


def _route_topics(job: Job) -> list[str]:
    """Determine which topics a job should be sent to."""
    topics = []
    tags_str = _flatten_tags(job.tags)
    searchable = f"{job.title} {job.company} {tags_str}".lower()

    for key, ch in CHANNELS.items():
        match_type = ch.get("match", "")
        if match_type == "ALL":
            topics.append(key)
        elif match_type == "GEO_EGYPT":
            if _is_egypt_location(job.location):
                topics.append(key)
        elif match_type == "GEO_SAUDI":
            if _is_saudi_location(job.location):
                topics.append(key)
        elif "keywords" in ch:
            if _match_keywords(searchable, ch["keywords"]):
                topics.append(key)

    return topics


def enrich_job(job: Job) -> Job:
    """
    Enrich a job with parsed salary, seniority, country, and topic routing.
    Returns the same Job object with fields updated (mutates in place).
    """
    # 1. Parse salary
    if job.salary_raw and not job.salary_min:
        result = parse_salary(job.salary_raw)
        if result:
            job.salary_min = result["min"]
            job.salary_max = result["max"]
            job.salary_currency = result["currency"]

    # 2. Detect seniority (only if still default)
    if job.seniority == "mid":
        job.seniority = detect_seniority(job.title)

    # 3. Detect country (only if empty)
    if not job.country:
        job.country = detect_country(job.location)

    # 4. Route to topics (always recalculate)
    job.topics = _route_topics(job)

    return job
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd G:/projects/SWE-Jobs && python -m pytest tests/test_enrichment.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add core/enrichment.py tests/test_enrichment.py
git commit -m "feat: add job enrichment pipeline chaining all quality modules"
```

---

### Task 7: Run All Tests and Final Verification

- [ ] **Step 1: Run full test suite**

Run: `cd G:/projects/SWE-Jobs && python -m pytest tests/ -v`
Expected: All tests PASS (test_models, test_db, test_salary_parser, test_seniority, test_country_detector, test_filtering, test_dedup, test_enrichment)

- [ ] **Step 2: Verify imports**

Run:
```bash
cd G:/projects/SWE-Jobs && python -c "
from core.salary_parser import parse_salary
from core.seniority import detect_seniority
from core.country_detector import detect_country
from core.filtering import score_job, is_programming_job, passes_geo_filter, filter_jobs
from core.dedup import deduplicate_batch, fuzzy_dedup_against_db
from core.enrichment import enrich_job
print('All quality modules imported OK')
"
```
Expected: "All quality modules imported OK"

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat: complete Plan 2 — quality engine (salary, seniority, country, scoring, dedup)"
```

---

## Summary

After completing this plan, the project has:

- **Salary parser** — handles USD, EUR, GBP, EGP, SAR + hourly/monthly/yearly normalization
- **Seniority detector** — intern through executive with word-boundary regex
- **Country detector** — 30+ countries by pattern matching
- **Weighted keyword scoring** — replaces boolean matching, threshold-based, pre-compiled regex
- **Fuzzy dedup** — URL + pg_trgm title similarity + batch dedup
- **Enrichment pipeline** — chains all modules to enrich a Job in one call
- **Full test coverage** for every module

**Next:** Plan 3 (Interactive Telegram Bot) builds on enrichment to send richer messages with inline buttons.
