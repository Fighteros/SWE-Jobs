"""
Bayt.com — Playwright-based scraper for the Middle East's largest job board.
Uses Playwright to bypass bot protection and render JS-heavy pages.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from core.models import Job
from sources.playwright_utils import get_browser_page

log = logging.getLogger(__name__)

BASE_URL = "https://www.bayt.com/en/international/jobs/"

# Search queries targeting tech roles in MENA region
SEARCHES = [
    "software engineer",
    "software developer",
    "backend developer",
    "frontend developer",
    "full stack developer",
    "mobile developer",
    "flutter developer",
    "devops engineer",
    "data scientist",
    "machine learning engineer",
    "QA engineer",
    "cloud engineer",
]


def fetch_bayt() -> list[Job]:
    """Fetch jobs from Bayt.com using Playwright."""
    jobs = []
    seen_urls = set()

    try:
        with get_browser_page() as page:
            for keyword in SEARCHES:
                try:
                    keyword_slug = keyword.replace(" ", "-")
                    url = f"{BASE_URL}{keyword_slug}-jobs/"
                    page.goto(url, wait_until="networkidle", timeout=20_000)

                    # Wait for any job-related link to appear
                    page.wait_for_selector(
                        "a[href*='/en/'][href*='job'], h2 a",
                        timeout=10_000,
                    )

                    html = page.content()
                    parsed = _parse_search_html(html)
                    for job in parsed:
                        if job.url not in seen_urls:
                            seen_urls.add(job.url)
                            jobs.append(job)

                except Exception as e:
                    log.warning(f"Bayt: error on search '{keyword}': {e}")
                    continue

    except Exception as e:
        log.error(f"Bayt: browser launch failed: {e}")

    log.debug(f"Bayt: fetched {len(jobs)} jobs.")
    return jobs


def _parse_search_html(html: str) -> list[Job]:
    """Parse Bayt search results HTML into Job objects."""
    jobs = []

    # Bayt job cards are in <li> elements with job listing data
    cards = re.findall(
        r'<li[^>]*class="[^"]*has-pointer-d[^"]*"[^>]*>.*?</li>',
        html, re.DOTALL,
    )

    if not cards:
        cards = re.findall(
            r'<div[^>]*data-job-id[^>]*>.*?</div>\s*</div>\s*</div>',
            html, re.DOTALL,
        )

    if not cards:
        cards = re.findall(
            r'<div[^>]*class="[^"]*jb-listing[^"]*"[^>]*>.*?</div>\s*</div>',
            html, re.DOTALL,
        )

    for card in cards:
        try:
            job = _parse_card(card)
            if job:
                jobs.append(job)
        except Exception as e:
            log.debug(f"Bayt: error parsing card: {e}")
            continue

    return jobs


def _parse_card(card: str) -> Job | None:
    """Parse a single Bayt job card HTML into a Job."""
    # Title & URL
    title_match = re.search(
        r'<a[^>]*href="(/en/[^"]*job[^"]*)"[^>]*>.*?<h2[^>]*>(.*?)</h2>',
        card, re.DOTALL,
    )
    if not title_match:
        title_match = re.search(
            r'<h2[^>]*>\s*<a[^>]*href="(/en/[^"]*)"[^>]*>(.*?)</a>',
            card, re.DOTALL,
        )
    if not title_match:
        return None

    href = title_match.group(1)
    title = _clean(title_match.group(2))
    if not title:
        return None
    url = f"https://www.bayt.com{href}" if not href.startswith("http") else href

    # Company
    company_match = re.search(
        r'class="[^"]*company[^"]*"[^>]*>.*?<[^>]*>(.*?)</[^>]*>',
        card, re.DOTALL,
    )
    company = _clean(company_match.group(1)) if company_match else ""

    # Location
    location_match = re.search(
        r'class="[^"]*location[^"]*"[^>]*>(.*?)</[^>]*>',
        card, re.DOTALL,
    )
    location = _clean(location_match.group(1)) if location_match else "Middle East"

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
        source="bayt",
        is_remote=is_remote,
        posted_at=posted_at,
    )


def _parse_relative_date(text: str) -> datetime | None:
    """Parse Bayt dates like '2 days ago', 'today', 'yesterday'."""
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
