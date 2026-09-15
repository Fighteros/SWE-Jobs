"""Wuzzuf scraper.

Wuzzuf renders job cards from an SSR state object. The card markup changes
often, while the state object has remained the more stable source of rich job
metadata. DOM cards are therefore used for ordering and fallback fields, and
the SSR entities enrich them when available.
"""

import html as html_lib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from core.config import WUZZUF_HEADLESS, WUZZUF_MAX_PAGES, WUZZUF_PROFILE_DIR
from core.models import Job
from sources.playwright_utils import get_browser_page

log = logging.getLogger(__name__)

BASE_URL = "https://wuzzuf.net/search/jobs/"
STATE_MARKER = re.compile(r'"job"\s*:\s*\{\s*"collection"\s*:')
JOB_HREF_RE = re.compile(r"/jobs/p/[^\"'?#]+")

SEARCHES = [
    {"q": "software engineer", "a": "hpb"},
    {"q": "software developer", "a": "hpb"},
    {"q": "backend developer", "a": "hpb"},
    {"q": "frontend developer", "a": "hpb"},
    {"q": "full stack developer", "a": "hpb"},
    {"q": "mobile developer", "a": "hpb"},
    {"q": "flutter developer", "a": "hpb"},
    {"q": "devops engineer", "a": "hpb"},
    {"q": "data scientist", "a": "hpb"},
    {"q": "machine learning engineer", "a": "hpb"},
    {"q": "QA engineer", "a": "hpb"},
    {"q": "marketing manager", "a": "hpb"},
    {"q": "hr manager", "a": "hpb"},
    {"q": "accountant", "a": "hpb"},
    {"q": "operations manager", "a": "hpb"},
    {"q": "customer support", "a": "hpb"},
    {"q": "product manager", "a": "hpb"},
]


def fetch_wuzzuf() -> list[Job]:
    """Fetch Wuzzuf jobs using a persistent browser profile when configured."""
    jobs: list[Job] = []
    seen_ids: set[str] = set()
    profile_dir = WUZZUF_PROFILE_DIR or os.getenv("WUZZUF_PROFILE_DIR", "")
    max_pages = max(1, WUZZUF_MAX_PAGES)

    try:
        with get_browser_page(headless=WUZZUF_HEADLESS, user_data_dir=profile_dir) as page:
            page.set_default_timeout(30_000)
            for params in SEARCHES:
                query_seen: set[str] = set()
                for page_number in range(max_pages):
                    try:
                        query = urlencode({"q": params["q"], "a": params["a"], "start": page_number})
                        page.goto(f"{BASE_URL}?{query}", wait_until="domcontentloaded", timeout=30_000)
                        page.wait_for_timeout(1500)
                        page.wait_for_selector("a[href^='/jobs/p/']", timeout=15_000)
                        parsed = _parse_html(page.content())
                    except Exception as exc:
                        log.warning("Wuzzuf: error on search '%s' page %s: %s", params["q"], page_number, exc)
                        break

                    page_ids = {_job_id(job.url) for job in parsed if _job_id(job.url)}
                    if not page_ids or page_ids.issubset(query_seen):
                        break
                    query_seen.update(page_ids)
                    for job in parsed:
                        job_id = _job_id(job.url)
                        if job_id and job_id not in seen_ids:
                            seen_ids.add(job_id)
                            jobs.append(job)
    except Exception as exc:
        log.error("Wuzzuf: browser launch failed: %s", exc)

    log.debug("Wuzzuf: fetched %s jobs.", len(jobs))
    return jobs


def _extract_state(page_html: str) -> dict:
    """Extract ``job.collection`` from Wuzzuf's inline SSR state."""
    match = STATE_MARKER.search(page_html or "")
    if not match:
        return {}
    start = page_html.find("{", match.start())
    if start < 0:
        return {}
    depth = 0
    in_string = False
    escaped = False
    end = start
    for index in range(start, len(page_html)):
        char = page_html[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index
                break
    try:
        # The marker starts at the ``"job"`` key, so wrap that key/value
        # pair before decoding it as JSON.
        parsed = json.loads("{" + page_html[match.start():end + 1] + "}")
        return (parsed.get("job") or {}).get("collection") or {}
    except (ValueError, TypeError, UnboundLocalError) as exc:
        log.debug("Wuzzuf: unable to parse SSR state: %s", exc)
        return {}


def _entities_by_id(collection: dict) -> dict[str, dict]:
    entities = collection.values() if isinstance(collection, dict) else collection
    result = {}
    for entity in entities or []:
        if not isinstance(entity, dict):
            continue
        slug = (entity.get("attributes") or {}).get("slug", "")
        job_id = _job_id(slug)
        if job_id:
            result[job_id] = entity
    return result


def _parse_html(page_html: str) -> list[Job]:
    """Parse DOM cards and enrich them with the SSR entity payload."""
    state = _extract_state(page_html)
    entities = _entities_by_id(state)
    jobs = []
    seen_ids = set()
    for match in JOB_HREF_RE.finditer(page_html or ""):
        href = html_lib.unescape(match.group(0))
        job_id = _job_id(href)
        if not job_id or job_id in seen_ids:
            continue
        seen_ids.add(job_id)
        context = page_html[max(0, match.start() - 500):match.end() + 1800]
        title_match = re.search(r"<h2[^>]*>.*?>(.*?)</a>", context, re.DOTALL | re.IGNORECASE)
        title = _clean(title_match.group(1)) if title_match else ""
        if not title:
            continue
        company = _field(context, r"(?:company|css-ipsyv7)")
        location = _field(context, r"(?:location|css-16x61xq)") or "Egypt"
        posted = _field(context, r"(?:posted|css-eg55jf)")
        tag_block = re.search(r"class=[\"'][^\"']*(?:tag|css-5jhz9n)[^\"']*[\"'][^>]*>(.*?)</div>", context, re.DOTALL | re.IGNORECASE)
        tags = re.findall(r"<span[^>]*>(.*?)</span>", tag_block.group(1), re.DOTALL | re.IGNORECASE) if tag_block else []
        entity = entities.get(job_id, {})
        jobs.append(_to_job(href, title, company, location, posted, [_clean(t) for t in tags], entity))
    return jobs


def _to_job(href: str, title: str, company: str, location: str, posted: str, tags: list[str], entity: dict) -> Job:
    attrs = (entity.get("attributes") or {}) if entity else {}
    salary = attrs.get("salary") or {}
    salary_raw = salary.get("additionalDetails", "")
    if not salary_raw and (salary.get("min") is not None or salary.get("max") is not None):
        salary_raw = _clean(f"{salary.get('min') or ''} - {salary.get('max') or ''} {salary.get('currency') or ''} {salary.get('period') or ''}")
    work_types = [item.get("displayedName") for item in attrs.get("workTypes") or [] if item.get("displayedName")]
    workplace = (attrs.get("workplaceArrangement") or {}).get("displayedName", "")
    career = (attrs.get("careerLevel") or {}).get("name", "")
    location = location or "Egypt"
    all_tags = [tag for tag in tags + work_types if tag]
    posted_at = _parse_state_timestamp(attrs.get("postedAt")) or _parse_relative_date(posted)
    return Job(
        title=title,
        company=company,
        location=location,
        url=f"https://wuzzuf.net{href}" if href.startswith("/") else href,
        source="wuzzuf",
        salary_raw=salary_raw,
        job_type=", ".join(work_types),
        seniority=_normalise_seniority(career),
        is_remote="remote" in f"{title} {location} {workplace}".lower(),
        country="Egypt",
        tags=all_tags,
        posted_at=posted_at,
    )


def _field(context: str, class_pattern: str) -> str:
    match = re.search(rf"class=[\"'][^\"']*{class_pattern}[^\"']*[\"'][^>]*>\s*(.*?)</", context, re.DOTALL | re.IGNORECASE)
    return _clean(match.group(1)) if match else ""


def _job_id(value: str) -> str:
    match = re.search(r"(?:/jobs/p/|^)(\d+)(?:-|$)", value or "")
    return match.group(1) if match else ""


def _normalise_seniority(value: str) -> str:
    value = (value or "").lower()
    for key in ("intern", "entry", "junior", "mid", "senior", "lead", "manager", "director"):
        if key in value:
            return "entry" if key == "intern" else key
    return "mid"


def _parse_state_timestamp(value: str) -> datetime | None:
    for fmt in ("%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            local = datetime.strptime(value, fmt).replace(tzinfo=ZoneInfo("Africa/Cairo"))
            return local.astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
    return None


def _parse_relative_date(text: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    match = re.search(r"(\d+)\s*(second|minute|hour|day|week|month|year)s?\s*ago", (text or "").lower())
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2)
    delta = {"second": timedelta(seconds=value), "minute": timedelta(minutes=value), "hour": timedelta(hours=value), "day": timedelta(days=value), "week": timedelta(weeks=value), "month": timedelta(days=value * 30), "year": timedelta(days=value * 365)}[unit]
    return now - delta


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", "", text or ""))).strip()
