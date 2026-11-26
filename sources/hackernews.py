"""Hacker News "Ask HN: Who is hiring?" monthly thread (Algolia API, no key)."""

import html
import logging
import re
from datetime import datetime, timezone

from core.models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)

SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
ITEM_URL = "https://hn.algolia.com/api/v1/items/{id}"
HN_ITEM_LINK = "https://news.ycombinator.com/item?id={id}"
MAX_AGE_DAYS = 35
_TAG_RE = re.compile(r"<[^>]+>")


def fetch_hackernews() -> list[Job]:
    """Fetch top-level job comments from the latest 'Who is hiring?' thread."""
    search = get_json(SEARCH_URL, params={
        "tags": "story,author_whoishiring", "hitsPerPage": 5,
    })
    thread_id = None
    for hit in (search or {}).get("hits", []):
        if "who is hiring" in (hit.get("title") or "").lower():
            thread_id = hit.get("objectID")
            break
    if not thread_id:
        log.warning("HackerNews: no 'Who is hiring' thread found")
        return []

    thread = get_json(ITEM_URL.format(id=thread_id))
    if not thread:
        return []

    now = datetime.now(timezone.utc)
    jobs = []
    for child in thread.get("children", []):
        job = _parse_comment(child, now)
        if job:
            jobs.append(job)
    log.debug(f"HackerNews: fetched {len(jobs)} jobs.")
    return jobs


def _parse_comment(child: dict, now: datetime) -> Job | None:
    text = child.get("text")
    if not text or child.get("deleted") or child.get("dead"):
        return None
    first_line = re.split(r"<p>|\n", text, maxsplit=1)[0]
    plain = html.unescape(_TAG_RE.sub("", first_line)).strip()
    parts = [p.strip() for p in plain.split("|") if p.strip()]
    # Real postings start with a "Company | Role | Location | ..." header line.
    if len(parts) < 3:
        return None

    company, title = parts[0], parts[1]
    rest = parts[2:]
    location = next((p for p in rest if _looks_like_location(p)), rest[0])
    remote = any("remote" in p.lower() for p in parts)
    posted = _parse_date(child.get("created_at"))
    if posted and (now - posted).days > MAX_AGE_DAYS:
        return None

    return Job(
        title=title[:200],
        company=company[:120],
        location=location[:120],
        url=HN_ITEM_LINK.format(id=child["id"]),
        source="hackernews",
        job_type=next((p for p in rest if re.search(r"full.?time|part.?time|contract|intern", p, re.I)), ""),
        tags=["Hacker News"],
        is_remote=remote,
        posted_at=posted,
    )


def _looks_like_location(part: str) -> bool:
    return bool(re.search(
        r"remote|onsite|on-site|hybrid|[A-Z][a-z]+,\s*[A-Z]{2}|\b(?:USA|UK|EU|Europe|Germany|Egypt|Canada|India|Berlin|London|NYC|SF)\b",
        part,
    ))


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
