"""
Indeed — Playwright-based scraper for indeed.com job listings.
Searches for software/tech roles across target regions.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from core.models import Job
from sources.playwright_utils import get_browser_page

log = logging.getLogger(__name__)

BASE_URL = "https://www.indeed.com/jobs"

# fromage=1 = last 24 hours, remotejob for remote filter
SEARCHES = [
    # Remote
    {"q": "software engineer", "l": "Remote", "fromage": "1"},
    {"q": "backend developer", "l": "Remote", "fromage": "1"},
    {"q": "frontend developer", "l": "Remote", "fromage": "1"},
    {"q": "devops engineer", "l": "Remote", "fromage": "1"},
    {"q": "flutter developer", "l": "Remote", "fromage": "1"},
    {"q": "data scientist", "l": "Remote", "fromage": "1"},
    {"q": "mobile developer", "l": "Remote", "fromage": "1"},
    # Egypt
    {"q": "software engineer", "l": "Egypt", "fromage": "1"},
    {"q": "software developer", "l": "Egypt", "fromage": "1"},
    {"q": "backend developer", "l": "Egypt", "fromage": "1"},
    # Saudi Arabia
    {"q": "software engineer", "l": "Saudi Arabia", "fromage": "1"},
    {"q": "software developer", "l": "Saudi Arabia", "fromage": "1"},
    # UAE
    {"q": "software engineer", "l": "United Arab Emirates", "fromage": "1"},
    {"q": "software developer", "l": "United Arab Emirates", "fromage": "1"},
]


def fetch_indeed() -> list[Job]:
    """Fetch jobs from Indeed using Playwright."""
    jobs = []
    seen_urls = set()

    try:
        with get_browser_page() as page:
            for params in SEARCHES:
                try:
                    q = params["q"].replace(" ", "+")
                    loc = params["l"]
                    url = f"{BASE_URL}?q={q}&l={loc}&fromage={params['fromage']}"
                    page.goto(url, wait_until="domcontentloaded")

                    # Wait for job cards
                    try:
                        page.wait_for_selector(
                            '.job_seen_beacon, .resultContent, div.cardOutline',
                            timeout=12_000,
                        )
                    except Exception:
                        log.debug(f"Indeed: no results for '{params['q']}' in {loc}")
                        continue

                    cards = page.query_selector_all(
                        '.job_seen_beacon, .resultContent, div.cardOutline'
                    )

                    for card in cards:
                        try:
                            job = _parse_card(card, loc)
                            if job and job.url not in seen_urls:
                                seen_urls.add(job.url)
                                jobs.append(job)
                        except Exception as e:
                            log.debug(f"Indeed: error parsing card: {e}")
                            continue

                except Exception as e:
                    log.warning(f"Indeed: error on search '{params['q']}': {e}")
                    continue

    except Exception as e:
        log.error(f"Indeed: browser launch failed: {e}")

    log.debug(f"Indeed: fetched {len(jobs)} jobs.")
    return jobs


def _parse_card(card, search_location: str) -> Job | None:
    """Parse a single Indeed job card into a Job."""
    # Title & URL
    title_el = card.query_selector(
        'h2.jobTitle a, a.jcs-JobTitle, h2 a[data-jk]'
    )
    if not title_el:
        return None
    title = title_el.inner_text().strip()
    href = title_el.get_attribute("href") or ""
    if not title:
        return None

    # Indeed uses relative URLs with job keys
    if href.startswith("/"):
        url = f"https://www.indeed.com{href}"
    elif href.startswith("http"):
        url = href
    else:
        # Try data-jk attribute for job key
        jk = title_el.get_attribute("data-jk") or ""
        url = f"https://www.indeed.com/viewjob?jk={jk}" if jk else ""

    if not url:
        return None

    # Company
    company_el = card.query_selector(
        '[data-testid="company-name"], .companyName, span.css-1h7lukg'
    )
    company = company_el.inner_text().strip() if company_el else ""

    # Location
    location_el = card.query_selector(
        '[data-testid="text-location"], .companyLocation, div.css-1restlb'
    )
    location = location_el.inner_text().strip() if location_el else search_location

    # Salary
    salary_raw = ""
    salary_el = card.query_selector(
        '.salary-snippet-container, .estimated-salary, div.css-1cvvo1b, '
        '[data-testid="attribute_snippet_testid"]'
    )
    if salary_el:
        text = salary_el.inner_text().strip()
        if any(c in text for c in "$€£") or "salary" in text.lower():
            salary_raw = text

    # Job type
    job_type = ""
    type_el = card.query_selector(
        '.metadata div.css-1cvvo1b, [data-testid="attribute_snippet_testid"]'
    )
    if type_el:
        type_text = type_el.inner_text().strip().lower()
        type_map = {
            "full-time": "Full-time", "part-time": "Part-time",
            "contract": "Contract", "internship": "Internship",
            "temporary": "Temporary",
        }
        for kw, jt in type_map.items():
            if kw in type_text:
                job_type = jt
                break

    is_remote = "remote" in location.lower() or search_location.lower() == "remote"

    # Posted date
    posted_at = None
    date_el = card.query_selector('.date, span.css-qvloho, .myJobsState')
    if date_el:
        posted_at = _parse_relative_date(date_el.inner_text().strip())

    return Job(
        title=title,
        company=company,
        location=location,
        url=url,
        source="indeed",
        salary_raw=salary_raw,
        job_type=job_type,
        is_remote=is_remote,
        posted_at=posted_at,
    )


def _parse_relative_date(text: str) -> datetime | None:
    """Parse Indeed date strings like 'Just posted', '1 day ago', 'Today'."""
    if not text:
        return None
    text = text.lower().strip()
    now = datetime.now(timezone.utc)

    if "just" in text or "today" in text:
        return now

    match = re.search(r'(\d+)\s*(second|minute|hour|day|week|month)s?\s*ago', text)
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
    }
    delta = deltas.get(unit)
    return (now - delta) if delta else None
