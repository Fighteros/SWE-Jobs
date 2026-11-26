"""Landing.jobs public API (European tech jobs, no key)."""

import ast
import logging
from datetime import datetime, timezone

from core.models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)

URL = "https://landing.jobs/api/v1/jobs"
PAGE_SIZE = 50
MAX_PAGES = 3


def fetch_landingjobs() -> list[Job]:
    jobs = []
    for page in range(MAX_PAGES):
        data = get_json(URL, params={"limit": PAGE_SIZE, "offset": page * PAGE_SIZE})
        if not isinstance(data, list) or not data:
            break
        for item in data:
            url = item.get("url", "")
            if not url:
                continue
            jobs.append(Job(
                title=item.get("title", ""),
                company=_company(url),
                location=_location(item.get("locations")),
                url=url,
                source="landingjobs",
                salary_raw=_salary(item),
                job_type=item.get("type", ""),
                tags=_list(item.get("tags")),
                is_remote=bool(item.get("remote")),
                posted_at=_parse_date(item.get("published_at")),
            ))
        if len(data) < PAGE_SIZE:
            break
    log.debug(f"Landing.jobs: fetched {len(jobs)} jobs.")
    return jobs


def _company(url: str) -> str:
    # https://landing.jobs/at/<company-slug>/<job-slug>
    parts = url.split("/at/", 1)
    return parts[1].split("/", 1)[0].replace("-", " ").title() if len(parts) == 2 else ""


def _list(value) -> list:
    if isinstance(value, str):
        try:
            value = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return []
    return [str(v) for v in value] if isinstance(value, (list, tuple)) else []


def _location(value) -> str:
    if isinstance(value, str):
        try:
            value = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return value
    if isinstance(value, list):
        names = [f"{v.get('city', '')}, {v.get('country_code', '')}".strip(", ") for v in value if isinstance(v, dict)]
        return "; ".join(n for n in names if n)
    return ""


def _salary(item: dict) -> str:
    low, high = item.get("gross_salary_low"), item.get("gross_salary_high")
    if not low and not high:
        return ""
    return f"{low or ''}-{high or ''} {item.get('currency_code', '')}".strip()


def _parse_date(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
