"""
LinkedIn Posts — Playwright-based scraper for job posts shared on LinkedIn feed.

Scrapes public LinkedIn search for posts containing hiring keywords.
Similar to x_jobs.py but for LinkedIn. May require authentication via
LINKEDIN_COOKIES_FILE env var (exported via a browser extension).
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from core.models import Job
from sources.playwright_utils import get_browser_page

log = logging.getLogger(__name__)

SEARCH_BASE = "https://www.linkedin.com/search/results/content/"

# Search queries for job posts on LinkedIn feed
SEARCH_QUERIES = [
    '#hiring software engineer',
    '#hiring backend developer',
    '#hiring frontend developer',
    '#hiring devops engineer',
    '#hiring flutter developer',
    '#hiring mobile developer',
    '#hiring data scientist',
    '#hiring remote developer',
    '#hiring machine learning',
    'we are hiring software',
    'join our team developer',
    'open position software engineer',
    '#techjobs #hiring',
]

MAX_SCROLLS = 3
SCROLL_PAUSE = 2


def fetch_linkedin_posts() -> list[Job]:
    """Fetch job posts from LinkedIn feed search using Playwright."""
    jobs = []
    seen_urls = set()

    cookies_file = os.getenv("LINKEDIN_COOKIES_FILE", "")

    if not cookies_file or not os.path.isfile(cookies_file):
        log.warning(
            "LinkedIn Posts: LINKEDIN_COOKIES_FILE not set or missing — skipping. "
            "Export your LinkedIn cookies to a JSON file and set the env var."
        )
        return []

    try:
        with get_browser_page() as page:
            # Load LinkedIn cookies for authentication
            _load_cookies(page, cookies_file)

            for query in SEARCH_QUERIES:
                try:
                    parsed = _scrape_search(page, query)
                    for job in parsed:
                        if job.url not in seen_urls:
                            seen_urls.add(job.url)
                            jobs.append(job)
                except Exception as e:
                    log.warning(f"LinkedIn Posts: error on search '{query}': {e}")
                    continue

    except Exception as e:
        log.error(f"LinkedIn Posts: browser launch failed: {e}")

    log.debug(f"LinkedIn Posts: fetched {len(jobs)} jobs.")
    return jobs


def _load_cookies(page, cookies_file: str):
    """Load cookies from a JSON file for LinkedIn authentication."""
    try:
        page.goto("https://www.linkedin.com", wait_until="domcontentloaded")
        with open(cookies_file, "r") as f:
            cookies = json.load(f)
        pw_cookies = []
        for c in cookies:
            pw_cookies.append({
                "name": c.get("name", ""),
                "value": c.get("value", ""),
                "domain": c.get("domain", ".linkedin.com"),
                "path": c.get("path", "/"),
                "secure": c.get("secure", True),
                "httpOnly": c.get("httpOnly", False),
                "sameSite": c.get("sameSite", "None"),
            })
        page.context.add_cookies(pw_cookies)
        log.info("LinkedIn Posts: loaded cookies from file.")
        # Navigate again to apply cookies
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
        time.sleep(2)
    except Exception as e:
        log.warning(f"LinkedIn Posts: failed to load cookies: {e}")


def _scrape_search(page, query: str) -> list[Job]:
    """Run a single search query and extract job-like posts."""
    jobs = []
    encoded = query.replace(" ", "%20").replace("#", "%23")
    url = f"{SEARCH_BASE}?keywords={encoded}&sortBy=%22date_posted%22"

    page.goto(url, wait_until="domcontentloaded")

    # Wait for feed posts to load
    try:
        page.wait_for_selector(
            'div.feed-shared-update-v2, div.update-components-text',
            timeout=15_000,
        )
    except Exception:
        log.debug(f"LinkedIn Posts: no results for '{query}'")
        return jobs

    # Scroll to load more posts
    for _ in range(MAX_SCROLLS):
        page.mouse.wheel(0, 3000)
        time.sleep(SCROLL_PAUSE)

    # Extract all post containers
    posts = page.query_selector_all('div.feed-shared-update-v2')

    for post in posts:
        try:
            job = _parse_post(post)
            if job:
                jobs.append(job)
        except Exception as e:
            log.debug(f"LinkedIn Posts: error parsing post: {e}")
            continue

    return jobs


def _parse_post(post) -> Job | None:
    """Parse a LinkedIn feed post into a Job if it looks like a job posting."""
    # Get post text
    text_el = post.query_selector(
        'div.feed-shared-text, span.break-words, div.update-components-text'
    )
    if not text_el:
        return None
    text = text_el.inner_text().strip()

    if not text or len(text) < 30:
        return None

    # Must contain job-related signals
    text_lower = text.lower()
    job_signals = [
        "hiring", "looking for", "job opening", "open position",
        "we're hiring", "we are hiring", "join our team",
        "apply now", "job alert", "vacancy", "developer needed",
        "engineer needed", "open role", "we need", "come join",
    ]
    if not any(signal in text_lower for signal in job_signals):
        return None

    # Extract title
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    title = _extract_title(lines, text_lower)
    if not title:
        return None

    # Get post permalink
    post_url = ""
    link_el = post.query_selector('a.app-aware-link[href*="/feed/update/"]')
    if link_el:
        href = link_el.get_attribute("href") or ""
        post_url = href.split("?")[0] if href else ""

    if not post_url:
        # Try alternate permalink patterns
        urn_el = post.query_selector('[data-urn]')
        if urn_el:
            urn = urn_el.get_attribute("data-urn") or ""
            if urn:
                activity_id = urn.split(":")[-1]
                post_url = f"https://www.linkedin.com/feed/update/urn:li:activity:{activity_id}"

    if not post_url:
        return None

    # Extract author/company from post header
    company = ""
    author_el = post.query_selector(
        'span.feed-shared-actor__name, span.update-components-actor__name'
    )
    if author_el:
        company = author_el.inner_text().strip()
        # Clean up "View X's profile" type suffixes
        company = re.sub(r'\s*View\s+.*$', '', company).strip()

    # Extract location from text
    location = _extract_location(text)

    # Check for remote
    is_remote = any(
        w in text_lower
        for w in ["remote", "work from home", "wfh", "anywhere", "distributed"]
    )

    # Extract apply link if present
    apply_url = _extract_apply_link(post, text)
    job_url = apply_url or post_url

    # Extract salary if mentioned
    salary_raw = _extract_salary(text)

    return Job(
        title=title,
        company=company,
        location=location or ("Remote" if is_remote else ""),
        url=job_url,
        source="linkedin_posts",
        original_source="LinkedIn Posts",
        salary_raw=salary_raw,
        is_remote=is_remote,
    )


def _extract_title(lines: list[str], text_lower: str) -> str:
    """Try to extract a job title from post lines."""
    title_patterns = [
        r'(?:hiring|looking for|seeking)\s*(?:a|an)?\s*(.+?)(?:\n|$|!|\.|,)',
        r'(?:position|role|opening):\s*(.+?)(?:\n|$|!|\.|,)',
        r'((?:senior|junior|mid|lead|staff|principal)?\s*(?:software|backend|frontend|full[- ]?stack|mobile|flutter|devops|cloud|data|ml|ai|qa|security|game|blockchain|web)\s*(?:engineer|developer|scientist|analyst|architect|tester))',
    ]
    for pattern in title_patterns:
        match = re.search(pattern, text_lower)
        if match:
            title = match.group(1).strip().title()
            if len(title) > 10:
                return title[:120]

    # Fallback: use first non-empty line that looks like a title
    for line in lines[:3]:
        line_clean = re.sub(r'[#@]\S+', '', line).strip()
        if 10 < len(line_clean) < 120:
            return line_clean

    return ""


def _extract_location(text: str) -> str:
    """Try to pull location info from post text."""
    loc_patterns = [
        r'(?:location|based in|located in|office in)[:\s]+([A-Za-z, ]+)',
        r'📍\s*([A-Za-z, ]+)',
    ]
    for pattern in loc_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()[:80]
    return ""


def _extract_apply_link(post, text: str) -> str:
    """Try to find an external apply link in the post."""
    links = post.query_selector_all('a.app-aware-link[href]')
    for link in links:
        href = link.get_attribute("href") or ""
        # Skip internal LinkedIn links
        if href and "linkedin.com" not in href and href.startswith("http"):
            return href.split("?")[0]
    return ""


def _extract_salary(text: str) -> str:
    """Try to extract salary info from text."""
    salary_patterns = [
        r'(\$[\d,]+\s*[-–]\s*\$[\d,]+(?:\s*(?:k|K|/yr|/year|per year))?)',
        r'([\d,]+\s*[-–]\s*[\d,]+\s*(?:USD|EUR|GBP|EGP|AED|SAR))',
        r'(?:salary|comp|compensation)[:\s]+([^\n]{5,50})',
    ]
    for pattern in salary_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""
