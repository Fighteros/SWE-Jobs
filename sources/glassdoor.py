"""
Glassdoor — Playwright-based scraper for glassdoor.com job listings.
Searches for software/tech roles across target regions.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from core.models import Job
from sources.playwright_utils import get_browser_page

log = logging.getLogger(__name__)

BASE_URL = "https://www.glassdoor.com/Job/jobs.htm"

SEARCHES = [
    # Remote
    {"sc.keyword": "software engineer", "locT": "", "locKeyword": "Remote"},
    {"sc.keyword": "backend developer", "locT": "", "locKeyword": "Remote"},
    {"sc.keyword": "frontend developer", "locT": "", "locKeyword": "Remote"},
    {"sc.keyword": "devops engineer", "locT": "", "locKeyword": "Remote"},
    {"sc.keyword": "data scientist", "locT": "", "locKeyword": "Remote"},
    # Egypt
    {"sc.keyword": "software engineer", "locT": "N", "locKeyword": "Egypt"},
    {"sc.keyword": "software developer", "locT": "N", "locKeyword": "Egypt"},
    {"sc.keyword": "backend developer", "locT": "N", "locKeyword": "Egypt"},
    # Saudi Arabia
    {"sc.keyword": "software engineer", "locT": "N", "locKeyword": "Saudi Arabia"},
    {"sc.keyword": "software developer", "locT": "N", "locKeyword": "Saudi Arabia"},
    # UAE
    {"sc.keyword": "software engineer", "locT": "N", "locKeyword": "United Arab Emirates"},
    {"sc.keyword": "software developer", "locT": "N", "locKeyword": "United Arab Emirates"},
]

# Only get jobs from last 24 hours
FRESHNESS = "fromAge=1"


def fetch_glassdoor() -> list[Job]:
    """Fetch jobs from Glassdoor using Playwright."""
    jobs = []
    seen_urls = set()

    try:
        with get_browser_page() as page:
            for params in SEARCHES:
                try:
                    keyword = params["sc.keyword"].replace(" ", "+")
                    loc = params["locKeyword"]
                    url = (
                        f"{BASE_URL}?sc.keyword={keyword}"
                        f"&locKeyword={loc}&{FRESHNESS}"
                    )
                    page.goto(url, wait_until="domcontentloaded")

                    # Wait for job cards to render
                    try:
                        page.wait_for_selector(
                            '[data-test="jobListing"], .JobsList_jobListItem__wjTHv, li.react-job-listing',
                            timeout=12_000,
                        )
                    except Exception:
                        log.debug(f"Glassdoor: no results for '{params['sc.keyword']}' in {loc}")
                        continue

                    cards = page.query_selector_all(
                        '[data-test="jobListing"], .JobsList_jobListItem__wjTHv, li.react-job-listing'
                    )

                    for card in cards:
                        try:
                            job = _parse_card(card, loc)
                            if job and job.url not in seen_urls:
                                seen_urls.add(job.url)
                                jobs.append(job)
                        except Exception as e:
                            log.debug(f"Glassdoor: error parsing card: {e}")
                            continue

                except Exception as e:
                    log.warning(f"Glassdoor: error on search '{params['sc.keyword']}': {e}")
                    continue

    except Exception as e:
        log.error(f"Glassdoor: browser launch failed: {e}")

    log.debug(f"Glassdoor: fetched {len(jobs)} jobs.")
    return jobs


def _parse_card(card, search_location: str) -> Job | None:
    """Parse a single Glassdoor job card into a Job."""
    # Title
    title_el = card.query_selector(
        '[data-test="job-title"], a.JobCard_jobTitle__GLyJ1, a.jobTitle'
    )
    if not title_el:
        return None
    title = title_el.inner_text().strip()
    href = title_el.get_attribute("href") or ""
    if not title:
        return None
    url = href if href.startswith("http") else f"https://www.glassdoor.com{href}"

    # Company
    company_el = card.query_selector(
        '[data-test="emp-name"], .EmployerProfile_compactEmployerName__9MGcV, .jobCard_company'
    )
    company = company_el.inner_text().strip() if company_el else ""

    # Location
    location_el = card.query_selector(
        '[data-test="emp-location"], .JobCard_location__Ds1fM, .jobCard_location'
    )
    location = location_el.inner_text().strip() if location_el else search_location

    # Salary
    salary_raw = ""
    salary_el = card.query_selector(
        '[data-test="detailSalary"], .JobCard_salaryEstimate__QpbTW, .salary-estimate'
    )
    if salary_el:
        salary_raw = salary_el.inner_text().strip()

    is_remote = "remote" in location.lower() or search_location.lower() == "remote"

    # Posted date
    posted_at = None
    age_el = card.query_selector(
        '[data-test="job-age"], .JobCard_listingAge__KuaxZ, .listing-age'
    )
    if age_el:
        posted_at = _parse_relative_date(age_el.inner_text().strip())

    return Job(
        title=title,
        company=company,
        location=location,
        url=url,
        source="glassdoor",
        salary_raw=salary_raw,
        is_remote=is_remote,
        posted_at=posted_at,
    )


def _parse_relative_date(text: str) -> datetime | None:
    """Parse relative dates like '2d', '1d', '24h', '3d ago'."""
    if not text:
        return None
    text = text.lower().strip()
    now = datetime.now(timezone.utc)

    match = re.search(r'(\d+)\s*([hdwm])', text)
    if not match:
        match = re.search(r'(\d+)\s*(hour|day|week|month)s?\s*ago', text)
        if not match:
            return None
        num = int(match.group(1))
        unit = match.group(2)[0]  # first letter
    else:
        num = int(match.group(1))
        unit = match.group(2)

    deltas = {
        "h": timedelta(hours=num),
        "d": timedelta(days=num),
        "w": timedelta(weeks=num),
        "m": timedelta(days=num * 30),
    }
    delta = deltas.get(unit)
    return (now - delta) if delta else None
