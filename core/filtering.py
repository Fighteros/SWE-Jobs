"""
Weighted keyword scoring and geo-based filtering.
Replaces the old boolean contains-match with a scoring system.
"""

import re
import logging

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
