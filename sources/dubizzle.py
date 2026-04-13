"""
Dubizzle Jobs — HTML scraper for dubizzle.com (UAE/Middle East classifieds).
Scrapes IT/software job listings from dubizzle's jobs section.
"""

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from core.models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

# Dubizzle UAE jobs section
BASE_URL = "https://www.dubizzle.com/jobs/"

SEARCHES = [
    {"keyword": "software engineer"},
    {"keyword": "software developer"},
    {"keyword": "backend developer"},
    {"keyword": "frontend developer"},
    {"keyword": "full stack developer"},
    {"keyword": "mobile developer"},
    {"keyword": "flutter developer"},
    {"keyword": "devops engineer"},
    {"keyword": "data scientist"},
    {"keyword": "QA engineer"},
    {"keyword": "cloud engineer"},
]

REQUEST_DELAY = 3


def fetch_dubizzle() -> list[Job]:
    """Fetch jobs from Dubizzle."""
    jobs = []
    seen_urls = set()

    for i, params in enumerate(SEARCHES):
        if i > 0:
            time.sleep(REQUEST_DELAY)

        keyword = params["keyword"].replace(" ", "+")
        url = f"{BASE_URL}?keyword={keyword}"

        html = get_text(url, headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        })

        if not html:
            log.warning(f"Dubizzle: no response for '{params['keyword']}'")
            continue

        parsed = _parse_search_html(html)
        for job in parsed:
            if job.url not in seen_urls:
                seen_urls.add(job.url)
                jobs.append(job)

    log.debug(f"Dubizzle: fetched {len(jobs)} jobs.")
    return jobs


def _parse_search_html(html: str) -> list[Job]:
    """Parse Dubizzle search results HTML into Job objects."""
    jobs = []

    # Dubizzle uses listing cards
    cards = re.findall(
        r'<li[^>]*class="[^"]*listing[^"]*"[^>]*>.*?</li>',
        html, re.DOTALL,
    )

    if not cards:
        # Try alternate card patterns
        cards = re.findall(
            r'<div[^>]*class="[^"]*job-item[^"]*"[^>]*>.*?</div>\s*</div>',
            html, re.DOTALL,
        )

    if not cards:
        # Broader fallback: any link to job detail
        cards = re.findall(
            r'<a[^>]*href="(/jobs/[^"]*)"[^>]*>.*?</a>',
            html, re.DOTALL,
        )
        # Wrap bare links into pseudo-cards for uniform parsing
        if cards:
            for href_block in cards:
                try:
                    job = _parse_link_block(href_block, html)
                    if job:
                        jobs.append(job)
                except Exception:
                    continue
            return jobs

    for card in cards:
        try:
            job = _parse_card(card)
            if job:
                jobs.append(job)
        except Exception as e:
            log.debug(f"Dubizzle: error parsing card: {e}")
            continue

    return jobs


def _parse_card(card: str) -> Job | None:
    """Parse a single Dubizzle job card HTML into a Job."""
    # Title & URL
    title_match = re.search(
        r'<a[^>]*href="(/jobs/[^"]*)"[^>]*>(.*?)</a>',
        card, re.DOTALL,
    )
    if not title_match:
        title_match = re.search(
            r'<h2[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            card, re.DOTALL,
        )
    if not title_match:
        return None

    href = title_match.group(1)
    title = _clean(title_match.group(2))
    if not title or len(title) < 5:
        return None
    url = f"https://www.dubizzle.com{href}" if not href.startswith("http") else href

    # Company
    company_match = re.search(
        r'class="[^"]*company[^"]*"[^>]*>(.*?)</[^>]*>',
        card, re.DOTALL,
    )
    company = _clean(company_match.group(1)) if company_match else ""

    # Location
    location_match = re.search(
        r'class="[^"]*location[^"]*"[^>]*>(.*?)</[^>]*>',
        card, re.DOTALL,
    )
    location = _clean(location_match.group(1)) if location_match else "UAE"

    # Salary
    salary_raw = ""
    salary_match = re.search(
        r'class="[^"]*salary[^"]*"[^>]*>(.*?)</[^>]*>',
        card, re.DOTALL,
    )
    if salary_match:
        salary_raw = _clean(salary_match.group(1))

    # Date
    posted_at = None
    date_match = re.search(
        r'class="[^"]*date[^"]*"[^>]*>(.*?)</[^>]*>',
        card, re.DOTALL,
    )
    if date_match:
        posted_at = _parse_relative_date(_clean(date_match.group(1)))

    is_remote = "remote" in (location + title).lower()

    return Job(
        title=title,
        company=company,
        location=location,
        url=url,
        source="dubizzle",
        is_remote=is_remote,
        country="UAE",
        posted_at=posted_at,
        salary_raw=salary_raw,
    )


def _parse_link_block(href: str, full_html: str) -> Job | None:
    """Fallback: parse a bare job link from the full HTML."""
    # Extract surrounding context
    idx = full_html.find(href)
    if idx < 0:
        return None
    context = full_html[max(0, idx - 200):idx + 500]

    title_match = re.search(r'>([^<]{10,100})</a>', context)
    title = _clean(title_match.group(1)) if title_match else ""
    if not title:
        return None

    url = f"https://www.dubizzle.com{href}" if not href.startswith("http") else href

    return Job(
        title=title,
        company="",
        location="UAE",
        url=url,
        source="dubizzle",
        is_remote=False,
        country="UAE",
    )


def _parse_relative_date(text: str) -> datetime | None:
    """Parse Dubizzle date strings."""
    if not text:
        return None
    text = text.lower().strip()
    now = datetime.now(timezone.utc)

    if "today" in text or "just" in text:
        return now
    if "yesterday" in text:
        return now - timedelta(days=1)

    match = re.search(r'(\d+)\s*(second|minute|hour|day|week|month)s?\s*ago', text)
    if match:
        num = int(match.group(1))
        unit = match.group(2)
        deltas = {
            "second": timedelta(seconds=num),
            "minute": timedelta(minutes=num),
            "hour": timedelta(hours=num),
            "day": timedelta(days=num),
            "week": timedelta(weeks=num),
            "month": timedelta(days=num * 30),
        }
        delta = deltas.get(unit)
        if delta:
            return now - delta
    return None


def _clean(text: str) -> str:
    """Strip HTML tags and whitespace."""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
