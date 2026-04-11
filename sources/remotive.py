"""Remotive — remote jobs API (software-dev, qa, devops-sysadmin)."""

import logging
from datetime import datetime, timezone
from core.models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)

BASE = "https://remotive.com/api/remote-jobs"
CATEGORIES = ["software-dev", "qa", "devops-sysadmin"]


def fetch_remotive() -> list[Job]:
    """Fetch jobs from Remotive across multiple categories."""
    jobs = []
    for cat in CATEGORIES:
        data = get_json(BASE, params={"category": cat, "limit": 50})
        if not data or "jobs" not in data:
            log.warning(f"Remotive: no data for category={cat}")
            continue
        for item in data["jobs"]:
            posted_at = _parse_date(item.get("publication_date"))
            jobs.append(Job(
                title=item.get("title", ""),
                company=item.get("company_name", ""),
                location=item.get("candidate_required_location", "Anywhere"),
                url=item.get("url", ""),
                source="remotive",
                salary_raw=item.get("salary", ""),
                job_type=item.get("job_type", "").replace("_", " ").title(),
                tags=[item.get("category", "")],
                is_remote=True,
                posted_at=posted_at,
            ))
    log.debug(f"Remotive: fetched {len(jobs)} jobs.")
    return jobs


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse an ISO date string into a timezone-aware datetime."""
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None
