"""Wuzzuf scraper.

Wuzzuf renders job cards from an SSR state object. The card markup changes
often, while the state object has remained the more stable source of rich job
metadata. DOM cards are therefore used for ordering and fallback fields, and
the SSR entities enrich them when available.
"""

import html as html_lib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from core.config import WUZZUF_MAX_PAGES
from core.models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

BASE_URL = "https://wuzzuf.net"
STATE_MARKER = re.compile(r'"job"\s*:\s*\{\s*"collection"\s*:')
JOB_LINK_RE = re.compile(
    r'<a\b[^>]*href=["\'](?P<href>[^"\']*/jobs/p/[^"\']+)["\'][^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
CAREER_LINK_RE = re.compile(
    r'<a\b[^>]*href=["\'][^"\']*/jobs/careers/[^"\']+["\'][^>]*>(?P<company>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
SPAN_RE = re.compile(r"<span\b[^>]*>(.*?)</span>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<a\b[^>]*>(.*?)</a>|<span\b[^>]*>(.*?)</span>", re.IGNORECASE | re.DOTALL)
TAG_BLOCK_RE = re.compile(
    r"class=[\"'][^\"']*(?:tag|css-5jhz9n)[^\"']*[\"'][^>]*>(.*?)</div>",
    re.DOTALL | re.IGNORECASE,
)
JOB_ID_RE = re.compile(r"(?:/jobs/p/|^)([A-Za-z0-9]+)(?:-|/|$)")

SEARCH_URLS = [
    "https://wuzzuf.net/a/Software-Development-Jobs-in-Egypt",
    "https://wuzzuf.net/a/Software-Engineering-Jobs-in-Egypt",
    "https://wuzzuf.net/a/Information-Technology-IT-Jobs-in-Egypt",
    "https://wuzzuf.net/a/Android-Jobs-in-Egypt",
    "https://wuzzuf.net/a/Marketing-PR-Advertising-Jobs-in-Egypt",
    "https://wuzzuf.net/a/Creative-Design-Art-Jobs-in-Egypt",
    "https://wuzzuf.net/a/Analyst-Research-Jobs-in-Egypt",
    "https://wuzzuf.net/a/Project-Program-Management-Jobs-in-Egypt",
    "https://wuzzuf.net/a/Internships-in-Egypt",
    "https://wuzzuf.net/a/work-from-home",
]

JOB_TYPE_PATTERNS = (
    "Full Time", "Part Time", "Internship", "Freelance / Project",
    "Freelance", "Shift Based", "Volunteering", "دوام كامل", "دوام جزئي",
    "تدريب عملي",
)
WORKPLACE_PATTERNS = (
    "Remote", "Hybrid", "On-site", "Work From Home", "عمل عن بُعد",
    "عمل من المنزل", "عمل من مقر الشركة", "هجين",
)
REMOTE_MARKERS = ("remote", "work from home", "عمل عن بُعد", "عمل من المنزل")


def fetch_wuzzuf() -> list[Job]:
    """Fetch public Wuzzuf category pages and normalize their job cards."""
    jobs: list[Job] = []
    seen_urls: set[str] = set()
    max_pages = max(1, WUZZUF_MAX_PAGES)

    pages_requested = 0
    for base_url in SEARCH_URLS:
        category_seen: set[str] = set()
        for page_index in range(max_pages):
            url = _with_start(base_url, page_index * 20)
            pages_requested += 1
            page_html = get_text(url)
            if not page_html:
                log.warning("Wuzzuf: no response for %s", url)
                break

            parsed = _parse_html(page_html, page_url=url)
            page_ids = {_job_id(job.url) for job in parsed if _job_id(job.url)}
            if not page_ids or page_ids.issubset(category_seen):
                break
            category_seen.update(page_ids)
            for job in parsed:
                canonical_url = job.url.rstrip("/").lower()
                if canonical_url not in seen_urls:
                    seen_urls.add(canonical_url)
                    jobs.append(job)

    log.info("Wuzzuf: fetched %s jobs from %s page requests.", len(jobs), pages_requested)
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


def _parse_html(page_html: str, page_url: str = BASE_URL) -> list[Job]:
    """Parse public job-card anchors and enrich them with SSR data if present."""
    if not page_html:
        return []
    state = _extract_state(page_html)
    entities = _entities_by_id(state)
    jobs = []
    seen_ids = set()
    matches = list(JOB_LINK_RE.finditer(page_html))
    for index, match in enumerate(matches):
        href = html_lib.unescape(match.group("href"))
        job_id = _job_id(href)
        if not job_id or job_id in seen_ids:
            continue
        seen_ids.add(job_id)
        title = _clean(match.group("title"))
        if not title:
            continue
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(page_html)
        card_html = page_html[match.end():next_start]
        company, location = _extract_company_location(card_html)
        posted = _extract_posted(card_html)
        tags = _extract_tags(card_html, company, location)
        entity = entities.get(job_id, {})
        jobs.append(
            _to_job(
                href, title, company, location, posted, tags, entity,
                card_job_type=_extract_job_type(card_html),
                card_is_remote=_is_remote_text(card_html),
                page_url=page_url,
            )
        )
    return jobs


def _to_job(
    href: str,
    title: str,
    company: str,
    location: str,
    posted: str,
    tags: list[str],
    entity: dict,
    *,
    card_job_type: str = "",
    card_is_remote: bool = False,
    page_url: str = BASE_URL,
) -> Job:
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
    job_url = urljoin(page_url, href)
    split_url = urlsplit(job_url)
    job_url = urlunsplit((split_url.scheme, split_url.netloc, split_url.path, "", ""))
    return Job(
        title=title,
        company=company,
        location=location,
        url=job_url,
        source="wuzzuf",
        salary_raw=salary_raw,
        job_type=", ".join(work_types) or card_job_type,
        seniority=_normalise_seniority(career),
        is_remote=card_is_remote or any(
            marker in f"{title} {location} {workplace}".lower() for marker in REMOTE_MARKERS
        ),
        country="Egypt",
        tags=all_tags,
        posted_at=posted_at,
    )


def _extract_company_location(card_html: str) -> tuple[str, str]:
    company_match = CAREER_LINK_RE.search(card_html)
    company = _clean(company_match.group("company")).strip(" -") if company_match else ""
    company = (company or _field(card_html, r"(?:company|css-ipsyv7)")).strip(" -")

    location = ""
    for match in SPAN_RE.finditer(card_html):
        candidate = _clean(match.group(1)).strip(" -")
        if _looks_like_location(candidate):
            location = candidate
            break
    location = location or _field(card_html, r"(?:location|css-16x61xq)")

    if not company or not location:
        text = _clean(card_html)
        fallback = re.search(
            r"(?P<company>[^\n|]+?)\s+-\s+(?P<location>[^\n]+?(?:Egypt|مصر|Saudi Arabia|السعودية))",
            text,
            re.IGNORECASE,
        )
        if fallback:
            company = company or fallback.group("company").strip()
            location = location or fallback.group("location").strip()
    return company, location


def _extract_job_type(card_html: str) -> str:
    text = _clean(card_html).lower()
    values = []
    for pattern in JOB_TYPE_PATTERNS + WORKPLACE_PATTERNS:
        if pattern.lower() in text and pattern not in values:
            values.append(pattern)
    return " | ".join(values[:3])


def _extract_tags(card_html: str, company: str = "", location: str = "") -> list[str]:
    tag_block = TAG_BLOCK_RE.search(card_html)
    if tag_block:
        candidates = (_clean(value) for value in SPAN_RE.findall(tag_block.group(1)))
    else:
        candidates = (_clean(match.group(1) or match.group(2) or "") for match in TAG_RE.finditer(card_html))

    tags = []
    blocked = {"apply", "view", "log in", "get started", company.lower(), location.lower()}
    for text in candidates:
        lowered = text.lower()
        if not text or lowered in blocked or _looks_like_location(text):
            continue
        if lowered.endswith("ago") or len(text) > 70 or text in tags:
            continue
        tags.append(text)
        if len(tags) >= 18:
            break
    return tags


def _extract_posted(card_html: str) -> str:
    text = _clean(card_html)
    match = re.search(r"\b\d+\s*(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?)\s+ago\b", text, re.IGNORECASE)
    return match.group(0) if match else ""


def _with_start(url: str, start: int) -> str:
    """Add or replace Wuzzuf's 20-result pagination offset."""
    if start <= 0:
        return url
    split = urlsplit(url)
    pairs = [(key, value) for key, value in parse_qsl(split.query, keep_blank_values=True) if key != "start"]
    pairs.append(("start", str(start)))
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(pairs), split.fragment))


def _field(context: str, class_pattern: str) -> str:
    match = re.search(rf"class=[\"'][^\"']*{class_pattern}[^\"']*[\"'][^>]*>\s*(.*?)</", context, re.DOTALL | re.IGNORECASE)
    return _clean(match.group(1)) if match else ""


def _job_id(value: str) -> str:
    match = JOB_ID_RE.search(value or "")
    return match.group(1) if match else ""


def _looks_like_location(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "egypt", "مصر", "cairo", "giza", "alexandria", "saudi", "riyadh",
            "jeddah", "remote",
        )
    )


def _is_remote_text(raw_html: str) -> bool:
    text = _clean(raw_html).lower()
    return any(marker in text for marker in REMOTE_MARKERS)


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
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", text or "", flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", text))).strip()
