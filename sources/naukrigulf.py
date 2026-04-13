"""
NaukriGulf — HTML scraper for naukrigulf.com (Gulf region job board).
Uses requests + regex to parse search results for tech roles.
"""

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from core.models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

BASE_URL = "https://www.naukrigulf.com"

SEARCHES = [
    {"keyword": "software engineer", "location": ""},
    {"keyword": "software developer", "location": ""},
    {"keyword": "backend developer", "location": ""},
    {"keyword": "frontend developer", "location": ""},
    {"keyword": "full stack developer", "location": ""},
    {"keyword": "mobile developer", "location": ""},
    {"keyword": "flutter developer", "location": ""},
    {"keyword": "devops engineer", "location": ""},
    {"keyword": "data scientist", "location": ""},
    {"keyword": "machine learning engineer", "location": ""},
    {"keyword": "QA engineer", "location": ""},
    {"keyword": "cloud engineer", "location": ""},
]

REQUEST_DELAY = 3


def fetch_naukrigulf() -> list[Job]:
    """Fetch jobs from NaukriGulf."""
    jobs = []
    seen_urls = set()

    for i, params in enumerate(SEARCHES):
        if i > 0:
            time.sleep(REQUEST_DELAY)

        keyword_slug = params["keyword"].replace(" ", "-")
        url = f"{BASE_URL}/{keyword_slug}-jobs"

        html = get_text(url, headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        })

        if not html:
            log.warning(f"NaukriGulf: no response for '{params['keyword']}'")
            continue

        parsed = _parse_search_html(html)
        for job in parsed:
            if job.url not in seen_urls:
                seen_urls.add(job.url)
                jobs.append(job)

    log.debug(f"NaukriGulf: fetched {len(jobs)} jobs.")
    return jobs


def _parse_search_html(html: str) -> list[Job]:
    """Parse NaukriGulf search results HTML into Job objects."""
    jobs = []

    # NaukriGulf uses structured job listing cards
    cards = re.findall(
        r'<div[^>]*class="[^"]*srp-tuple[^"]*"[^>]*>.*?</div>\s*</div>\s*</div>',
        html, re.DOTALL,
    )

    if not cards:
        # Fallback: match by job link pattern
        cards = re.findall(
            r'<article[^>]*>.*?</article>',
            html, re.DOTALL,
        )

    if not cards:
        # Broader fallback
        cards = re.findall(
            r'<div[^>]*class="[^"]*listing[^"]*"[^>]*>.*?</div>\s*</div>',
            html, re.DOTALL,
        )

    for card in cards:
        try:
            job = _parse_card(card)
            if job:
                jobs.append(job)
        except Exception as e:
            log.debug(f"NaukriGulf: error parsing card: {e}")
            continue

    return jobs


def _parse_card(card: str) -> Job | None:
    """Parse a single NaukriGulf job card HTML into a Job."""
    # Title & URL
    title_match = re.search(
        r'<a[^>]*href="(https?://www\.naukrigulf\.com/[^"]*)"[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</a>',
        card, re.DOTALL,
    )
    if not title_match:
        title_match = re.search(
            r'<a[^>]*class="[^"]*desig[^"]*"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            card, re.DOTALL,
        )
    if not title_match:
        title_match = re.search(
            r'<a[^>]*href="(/[^"]*-jobs-[^"]*)"[^>]*>(.*?)</a>',
            card, re.DOTALL,
        )
    if not title_match:
        return None

    href = title_match.group(1)
    title = _clean(title_match.group(2))
    if not title:
        return None
    url = href if href.startswith("http") else f"{BASE_URL}{href}"

    # Company
    company_match = re.search(
        r'class="[^"]*comp-name[^"]*"[^>]*>(.*?)</[^>]*>',
        card, re.DOTALL,
    )
    if not company_match:
        company_match = re.search(
            r'class="[^"]*company[^"]*"[^>]*>(.*?)</[^>]*>',
            card, re.DOTALL,
        )
    company = _clean(company_match.group(1)) if company_match else ""

    # Location
    location_match = re.search(
        r'class="[^"]*loc[^"]*"[^>]*>\s*(?:<[^>]*>)*(.*?)</[^>]*>',
        card, re.DOTALL,
    )
    if not location_match:
        location_match = re.search(
            r'class="[^"]*location[^"]*"[^>]*>(.*?)</[^>]*>',
            card, re.DOTALL,
        )
    location = _clean(location_match.group(1)) if location_match else "Gulf"

    # Salary
    salary_raw = ""
    salary_match = re.search(
        r'class="[^"]*salary[^"]*"[^>]*>(.*?)</[^>]*>',
        card, re.DOTALL,
    )
    if salary_match:
        salary_raw = _clean(salary_match.group(1))

    # Experience
    tags = []
    exp_match = re.search(
        r'class="[^"]*exp[^"]*"[^>]*>(.*?)</[^>]*>',
        card, re.DOTALL,
    )
    if exp_match:
        tags.append(_clean(exp_match.group(1)))

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
        source="naukrigulf",
        salary_raw=salary_raw,
        is_remote=is_remote,
        tags=tags,
        posted_at=posted_at,
    )


def _parse_relative_date(text: str) -> datetime | None:
    """Parse NaukriGulf date strings."""
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
