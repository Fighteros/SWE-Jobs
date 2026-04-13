"""
Wuzzuf — Playwright-based scraper for wuzzuf.net (Egypt's largest job board).
Scrapes software/tech job listings across multiple search queries.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from core.models import Job
from sources.playwright_utils import get_browser_page

log = logging.getLogger(__name__)

BASE_URL = "https://wuzzuf.net/search/jobs/"

# Search queries targeting SWE roles in Egypt
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
]


def fetch_wuzzuf() -> list[Job]:
    """Fetch jobs from Wuzzuf using Playwright."""
    jobs = []
    seen_urls = set()

    try:
        with get_browser_page() as page:
            for params in SEARCHES:
                try:
                    query = params["q"].replace(" ", "+")
                    url = f"{BASE_URL}?q={query}&a={params['a']}"
                    page.goto(url, wait_until="networkidle", timeout=20_000)

                    # Use stable selectors — Wuzzuf wraps each job in an
                    # <a> that links to /jobs/p/…  Fall back to any h2 > a.
                    page.wait_for_selector(
                        "a[href*='/jobs/p/'], h2 a[href*='/jobs/']",
                        timeout=10_000,
                    )

                    html = page.content()
                    parsed = _parse_html(html)
                    for job in parsed:
                        if job.url not in seen_urls:
                            seen_urls.add(job.url)
                            jobs.append(job)

                except Exception as e:
                    log.warning(f"Wuzzuf: error on search '{params['q']}': {e}")
                    continue

    except Exception as e:
        log.error(f"Wuzzuf: browser launch failed: {e}")

    log.debug(f"Wuzzuf: fetched {len(jobs)} jobs.")
    return jobs


def _parse_html(html: str) -> list[Job]:
    """Parse Wuzzuf search results HTML into Job objects."""
    jobs = []

    # Each job card is wrapped in a div containing an h2 with the job link.
    # Extract blocks that contain a wuzzuf.net/jobs link.
    cards = re.findall(
        r'<div[^>]*>\s*<h2[^>]*>\s*<a[^>]*href="(/jobs/p/[^"]*)"[^>]*>(.*?)</a>.*?</div>(?:\s*</div>){0,4}',
        html, re.DOTALL,
    )

    if not cards:
        # Broader fallback: find all job links with surrounding context
        cards = re.findall(
            r'<a[^>]*href="(/jobs/p/[^"]*)"[^>]*>(.*?)</a>',
            html, re.DOTALL,
        )

    for match in cards:
        try:
            href, title_raw = match[0], match[1]
            title = _clean(title_raw)
            if not title or not href:
                continue
            url = f"https://wuzzuf.net{href}"

            jobs.append(Job(
                title=title,
                company="",
                location="Egypt",
                url=url,
                source="wuzzuf",
                is_remote="remote" in title.lower(),
                country="Egypt",
            ))
        except Exception as e:
            log.debug(f"Wuzzuf: error parsing card: {e}")
            continue

    return jobs


def _clean(text: str) -> str:
    """Strip HTML tags and whitespace."""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_relative_date(text: str) -> datetime | None:
    """Parse Wuzzuf relative dates like '2 days ago', '1 month ago' into datetime."""
    if not text:
        return None
    text = text.lower().strip()
    now = datetime.now(timezone.utc)
    match = re.search(r'(\d+)\s*(second|minute|hour|day|week|month|year)s?\s*ago', text)
    if not match:
        return None
    num = int(match.group(1))
    unit = match.group(2)
    deltas = {
        "second": timedelta(seconds=num),
        "minute": timedelta(minutes=num),
        "hour": timedelta(hours=num),
        "day": timedelta(days=num),
        "week": timedelta(weeks=num),
        "month": timedelta(days=num * 30),
        "year": timedelta(days=num * 365),
    }
    delta = deltas.get(unit)
    return (now - delta) if delta else None
