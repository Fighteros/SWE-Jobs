"""
core/subscription_matching.py — Shared job-to-alert matching and blacklist checks.

This logic is used both when building subscriber-DM delivery records (at queue
 time) and when delivering them, so it lives in core to avoid circular imports.
"""

from core.models import Job


def job_matches_alert(job: Job, alert: dict) -> bool:
    """Check if a job matches a single user alert (filter dict)."""
    if not alert:
        return False

    # An explicit general-only alert is the sole wildcard; malformed or empty
    # topic selections must not silently become all-jobs alerts.
    sub_topics = set(alert.get("topics") or [])
    if not sub_topics:
        return False
    if sub_topics != {"general"} and not sub_topics.intersection(job.topics or []):
        return False

    # Check seniority
    sub_seniority = alert.get("seniority", [])
    if sub_seniority and job.seniority not in sub_seniority:
        return False

    # Check sources — match against source key and original_source (for aggregators like JSearch)
    sub_sources = set(alert.get("sources", []))
    if sub_sources:
        _DISPLAY_TO_KEY = {
            "LinkedIn": "linkedin",
            "Indeed": "indeed",
            "Glassdoor": "glassdoor",
            "ZipRecruiter": "ziprecruiter",
            "Monster": "monster",
        }
        job_source_key = job.source
        original_key = _DISPLAY_TO_KEY.get(job.original_source, "")
        if job_source_key not in sub_sources and original_key not in sub_sources:
            return False

    # Check locations — "remote" matches is_remote, others match country code
    sub_locations = alert.get("locations", [])
    if sub_locations:
        matched = False
        for loc in sub_locations:
            if loc == "remote" and job.is_remote:
                matched = True
                break
            if loc == job.country:
                matched = True
                break
        if not matched:
            return False

    # Check keywords
    sub_keywords = alert.get("keywords", [])
    if sub_keywords:
        title_lower = job.title.lower()
        if not any(kw.lower() in title_lower for kw in sub_keywords):
            return False

    # Check minimum salary
    min_salary = alert.get("min_salary")
    if min_salary:
        if job.salary_min is None or job.salary_min < min_salary:
            return False

    return True


def job_blocked_by_blacklist(job: Job, blacklist: dict) -> bool:
    """Check if a job is blocked by the user's blacklist."""
    if not blacklist:
        return False

    company_lower = job.company.lower()
    for blocked in blacklist.get("companies", []):
        if blocked.lower() in company_lower:
            return True

    searchable = f"{job.title} {job.company}".lower()
    for kw in blacklist.get("keywords", []):
        if kw.lower() in searchable:
            return True

    return False
