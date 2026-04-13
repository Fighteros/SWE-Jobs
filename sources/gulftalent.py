"""
Gulf Talent — Playwright-based scraper for gulftalent.com (Gulf region job board).
Uses Playwright to bypass bot protection and render JS-heavy pages.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from core.models import Job
from sources.playwright_utils import get_browser_page

log = logging.getLogger(__name__)

BASE_URL = "https://www.gulftalent.com"

SEARCHES = [
    "software engineer",
    "software developer",
    "backend developer",
    "frontend developer",
    "full stack developer",
    "mobile developer",
    "devops engineer",
    "data scientist",
    "machine learning engineer",
    "QA engineer",
    "cloud engineer",
]


def fetch_gulftalent() -> list[Job]:
    """Fetch jobs from Gulf Talent using Playwright."""
    jobs = []
    seen_urls = set()

    try:
        with get_browser_page() as page:
            for keyword in SEARCHES:
                try:
                    kw = keyword.replace(" ", "+")
                    url = f"{BASE_URL}/jobs/search?keywords={kw}&industry=information-technology"
                    page.goto(url, wait_until="domcontentloaded", timeout=20_000)

                    # Wait for job cards to appear
                    page.wait_for_selector(
                        "div.job-card, tr.listing, div.search-result",
                        timeout=10_000,
                    )

                    html = page.content()
                    parsed = _parse_search_html(html)
                    for job in parsed:
                        if job.url not in seen_urls:
                            seen_urls.add(job.url)
                            jobs.append(job)

                except Exception as e:
                    log.warning(f"GulfTalent: error on search '{keyword}': {e}")
                    continue

    except Exception as e:
        log.error(f"GulfTalent: browser launch failed: {e}")

    log.debug(f"GulfTalent: fetched {len(jobs)} jobs.")
    return jobs


def _parse_search_html(html: str) -> list[Job]:
    """Parse Gulf Talent search results HTML into Job objects."""
    jobs = []

    cards = re.findall(
        r'<div[^>]*class="[^"]*job-card[^"]*"[^>]*>.*?</div>\s*</div>',
        html, re.DOTALL,
    )

    if not cards:
        cards = re.findall(
            r'<tr[^>]*class="[^"]*listing[^"]*"[^>]*>.*?</tr>',
            html, re.DOTALL,
        )

    if not cards:
        cards = re.findall(
            r'<div[^>]*class="[^"]*search-result[^"]*"[^>]*>.*?</div>\s*</div>',
            html, re.DOTALL,
        )

    for card in cards:
        try:
            job = _parse_card(card)
            if job:
                jobs.append(job)
        except Exception as e:
            log.debug(f"GulfTalent: error parsing card: {e}")
            continue

    return jobs


def _parse_card(card: str) -> Job | None:
    """Parse a single Gulf Talent job card HTML into a Job."""
    title_match = re.search(
        r'<a[^>]*href="(/[^"]*job[^"]*)"[^>]*>(.*?)</a>',
        card, re.DOTALL,
    )
    if not title_match:
        return None

    href = title_match.group(1)
    title = _clean(title_match.group(2))
    if not title:
        return None
    url = f"{BASE_URL}{href}" if not href.startswith("http") else href

    company_match = re.search(
        r'class="[^"]*company[^"]*"[^>]*>(.*?)</[^>]*>',
        card, re.DOTALL,
    )
    company = _clean(company_match.group(1)) if company_match else ""

    location_match = re.search(
        r'class="[^"]*location[^"]*"[^>]*>(.*?)</[^>]*>',
        card, re.DOTALL,
    )
    location = _clean(location_match.group(1)) if location_match else "Gulf"

    salary_raw = ""
    salary_match = re.search(
        r'class="[^"]*salary[^"]*"[^>]*>(.*?)</[^>]*>',
        card, re.DOTALL,
    )
    if salary_match:
        salary_raw = _clean(salary_match.group(1))

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
        source="gulftalent",
        salary_raw=salary_raw,
        is_remote=is_remote,
        posted_at=posted_at,
    )


def _parse_relative_date(text: str) -> datetime | None:
    """Parse date strings."""
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

    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d %b %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


def _clean(text: str) -> str:
    """Strip HTML tags and whitespace."""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
