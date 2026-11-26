"""Remote First Jobs (jobscollider.com / remotefirstjobs.com) public API, no key.

Terms of the API: link back to the Remote First Jobs URL and credit it. The
job url below is the Remote First Jobs page, and the source label credits it.
"""

import ast
import logging
from datetime import datetime, timezone

from core.models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)

BASE = "https://jobscollider.com/api/search-jobs"
CATEGORIES = ["software-development", "devops", "data", "design"]
PAGES = 2  # API allows up to 5 pages of 100


def fetch_jobscollider() -> list[Job]:
    jobs = []
    seen = set()
    for category in CATEGORIES:
        for page in range(PAGES):
            data = get_json(BASE, params={"category": category, "page": page, "limit": 100})
            items = (data or {}).get("jobs") or []
            if not items:
                break
            for item in items:
                url = item.get("url", "")
                if not url or url in seen:
                    continue
                seen.add(url)
                jobs.append(Job(
                    title=item.get("title", ""),
                    company=item.get("company_name", ""),
                    location=_location(item.get("locations")),
                    url=url,
                    source="jobscollider",
                    salary_raw=_salary(item),
                    tags=[t for t in (item.get("category"), item.get("seniority")) if t],
                    is_remote=True,
                    posted_at=_parse_date(item.get("published_at")),
                ))
    log.debug(f"JobsCollider: fetched {len(jobs)} jobs.")
    return jobs


def _location(value) -> str:
    if isinstance(value, str):
        try:
            value = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return value or "Remote"
    if isinstance(value, (list, tuple)) and value:
        return "Remote - " + ", ".join(str(v) for v in value[:3])
    return "Remote"


def _salary(item: dict) -> str:
    low, high = int(item.get("salary_min") or 0), int(item.get("salary_max") or 0)
    if not low and not high:
        return ""
    cur = item.get("salary_currency") or ""
    return f"{low}-{high} {cur}".strip()


def _parse_date(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
