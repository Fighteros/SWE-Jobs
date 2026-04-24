"""
Workable public job board — https://jobs.workable.com

Aggregates jobs across ALL Workable customer boards (distinct from
sources/workable.py which hits per-company Widget APIs for a curated list).

Endpoint: GET https://jobs.workable.com/api/v1/jobs
Params:   query, location, workplace (remote|hybrid|on_site), limit, nextPageToken

Strategy: run targeted queries aligned with Telegram topic keywords
(backend, frontend, mobile, devops, qa, ai_ml, cybersecurity, gamedev,
blockchain, fullstack, erp, internships) plus Egypt + Saudi geo queries,
so the downstream topic router in core/channels.py has matching volume.
"""

import logging
from datetime import datetime, timezone

from core.models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)

BASE_URL = "https://jobs.workable.com/api/v1/jobs"
PER_PAGE = 20          # API hard max — returns 400 above this
MAX_PAGES_PER_QUERY = 2  # 20 * 2 = 40 jobs/query → ~1k across all queries pre-filter

# (query, extra_params) — queries chosen to match core/channels.py topic keywords.
# workplace=remote for broad topics (geo filter drops non-Egypt/Saudi onsite anyway);
# Egypt / Saudi queries use location= to pull local onsite roles.
QUERIES: list[tuple[str, dict]] = [
    # Backend
    ("backend engineer",            {"workplace": "remote"}),
    ("python developer",            {"workplace": "remote"}),
    ("golang developer",            {"workplace": "remote"}),
    # Frontend
    ("frontend engineer",           {"workplace": "remote"}),
    ("react developer",             {"workplace": "remote"}),
    # Full stack
    ("full stack engineer",         {"workplace": "remote"}),
    # Mobile
    ("mobile developer",            {"workplace": "remote"}),
    ("flutter developer",           {"workplace": "remote"}),
    ("react native developer",      {"workplace": "remote"}),
    # DevOps / SRE / Cloud
    ("devops engineer",             {"workplace": "remote"}),
    ("site reliability engineer",   {"workplace": "remote"}),
    ("platform engineer",           {"workplace": "remote"}),
    # QA
    ("qa automation engineer",      {"workplace": "remote"}),
    ("sdet",                        {"workplace": "remote"}),
    # AI / ML / Data
    ("machine learning engineer",   {"workplace": "remote"}),
    ("data scientist",              {"workplace": "remote"}),
    ("data engineer",               {"workplace": "remote"}),
    # Cybersecurity
    ("security engineer",           {"workplace": "remote"}),
    # Gamedev
    ("unity developer",             {"workplace": "remote"}),
    # Blockchain / Web3
    ("blockchain engineer",         {"workplace": "remote"}),
    ("solidity developer",          {"workplace": "remote"}),
    # ERP
    ("odoo developer",              {"workplace": "remote"}),
    ("salesforce developer",        {"workplace": "remote"}),
    ("sap consultant",              {"workplace": "remote"}),
    # Internships
    ("software engineer intern",    {"workplace": "remote"}),
    # Geo — Egypt
    ("software engineer",           {"location": "Egypt"}),
    ("backend developer",           {"location": "Egypt"}),
    # Geo — Saudi Arabia
    ("software engineer",           {"location": "Saudi Arabia"}),
    ("backend developer",           {"location": "Saudi Arabia"}),
]


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def _format_location(item: dict) -> tuple[str, bool]:
    """Return (location_string, is_remote)."""
    workplace = (item.get("workplace") or "").lower()
    locations = item.get("locations") or []
    # TELECOMMUTE markers indicate remote
    is_remote = workplace == "remote" or any(
        isinstance(loc, str) and "telecommute" in loc.lower() for loc in locations
    )

    loc_obj = item.get("location") or {}
    if isinstance(loc_obj, dict):
        parts = [loc_obj.get("city"), loc_obj.get("subregion"), loc_obj.get("countryName")]
        loc_str = ", ".join(p for p in parts if p)
    else:
        loc_str = str(loc_obj)

    if not loc_str and locations:
        loc_str = next(
            (str(loc) for loc in locations if isinstance(loc, str) and loc.lower() != "telecommute"),
            "",
        )
    if not loc_str and is_remote:
        loc_str = "Remote"
    return loc_str or "Unknown", is_remote


def _parse_job(item: dict) -> Job | None:
    title = item.get("title") or ""
    url = item.get("url") or ""
    if not title or not url:
        return None

    company_obj = item.get("company") or {}
    company = company_obj.get("title") if isinstance(company_obj, dict) else ""
    if not company:
        return None

    location, is_remote = _format_location(item)

    department = item.get("department") or ""
    workplace = item.get("workplace") or ""
    tags = [t for t in (department, workplace) if t]

    return Job(
        title=title,
        company=company,
        location=location,
        url=url,
        source="workable_jobs",
        job_type=item.get("employmentType", ""),
        tags=tags,
        is_remote=is_remote,
        posted_at=_parse_date(item.get("created") or item.get("updated")),
    )


def fetch_workable_jobs() -> list[Job]:
    """Fetch jobs from the Workable public job board across topic-aligned queries."""
    jobs: list[Job] = []
    seen_ids: set[str] = set()

    for query, extra in QUERIES:
        next_token: str | None = None
        added = 0
        for page in range(MAX_PAGES_PER_QUERY):
            params = {"query": query, "limit": PER_PAGE, **extra}
            if next_token:
                params["nextPageToken"] = next_token
            data = get_json(BASE_URL, params=params)
            if not data or "jobs" not in data:
                log.debug(f"Workable Jobs: no data query={query!r} params={extra} page={page}")
                break

            for item in data["jobs"]:
                # In-fetch dedup by job id — same job matches multiple queries;
                # pipeline dedup still runs later on URL/title.
                job_id = item.get("id")
                if job_id and job_id in seen_ids:
                    continue
                job = _parse_job(item)
                if not job:
                    continue
                if job_id:
                    seen_ids.add(job_id)
                jobs.append(job)
                added += 1

            next_token = data.get("nextPageToken")
            if not next_token:
                break
        log.debug(f"Workable Jobs: query={query!r} params={extra} -> {added} new")

    log.debug(f"Workable Jobs: fetched {len(jobs)} jobs across {len(QUERIES)} queries.")
    return jobs
