"""
X (Twitter) — Playwright-based scraper for job posts on x.com.

Scrapes public search results for tech job hashtags and keywords.
Note: X may require login for full search results. If no results are found,
ensure TWITTER_COOKIES_FILE points to a cookies JSON file (exported via a
browser extension like "EditThisCookie") or set X_AUTH_TOKEN env var.
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

SEARCH_BASE = "https://x.com/search"

# Search queries — sorted by relevance to SWE jobs
SEARCH_QUERIES = [
    '#hiring software engineer -is:reply',
    '#hiring backend developer -is:reply',
    '#hiring frontend developer -is:reply',
    '#hiring devops -is:reply',
    '#hiring flutter developer -is:reply',
    '#techjobs remote developer -is:reply',
    '#hiring data scientist -is:reply',
    '#remotejobs software engineer -is:reply',
    '#hiring mobile developer -is:reply',
]

# How many scroll iterations per search (each scroll loads ~5-10 tweets)
MAX_SCROLLS = 3
SCROLL_PAUSE = 2


def fetch_x_jobs() -> list[Job]:
    """Fetch job posts from X/Twitter search using Playwright."""
    jobs = []
    seen_urls = set()

    cookies_file = os.getenv("TWITTER_COOKIES_FILE", "")
    auth_token = os.getenv("X_AUTH_TOKEN", "")

    try:
        with get_browser_page() as page:
            # Authenticate if credentials provided
            if cookies_file and os.path.isfile(cookies_file):
                _load_cookies(page, cookies_file)
            elif auth_token:
                _set_auth_token(page, auth_token)

            for query in SEARCH_QUERIES:
                try:
                    parsed = _scrape_search(page, query)
                    for job in parsed:
                        if job.url not in seen_urls:
                            seen_urls.add(job.url)
                            jobs.append(job)
                except Exception as e:
                    log.warning(f"X: error on search '{query}': {e}")
                    continue

    except Exception as e:
        log.error(f"X: browser launch failed: {e}")

    log.debug(f"X: fetched {len(jobs)} jobs.")
    return jobs


def _load_cookies(page, cookies_file: str):
    """Load cookies from a JSON file (EditThisCookie export format)."""
    try:
        page.goto("https://x.com", wait_until="domcontentloaded")
        with open(cookies_file, "r") as f:
            cookies = json.load(f)
        # Normalize to Playwright cookie format
        pw_cookies = []
        for c in cookies:
            pw_cookies.append({
                "name": c.get("name", ""),
                "value": c.get("value", ""),
                "domain": c.get("domain", ".x.com"),
                "path": c.get("path", "/"),
                "secure": c.get("secure", True),
                "httpOnly": c.get("httpOnly", False),
                "sameSite": c.get("sameSite", "None"),
            })
        page.context.add_cookies(pw_cookies)
        log.info("X: loaded cookies from file.")
    except Exception as e:
        log.warning(f"X: failed to load cookies: {e}")


def _set_auth_token(page, token: str):
    """Set auth_token cookie for X authentication."""
    try:
        page.goto("https://x.com", wait_until="domcontentloaded")
        page.context.add_cookies([{
            "name": "auth_token",
            "value": token,
            "domain": ".x.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
            "sameSite": "None",
        }])
        # Reload to apply the cookie so X recognises the session
        page.reload(wait_until="domcontentloaded")
        time.sleep(2)
        current_url = page.url
        if "/login" in current_url or "/i/flow/login" in current_url:
            log.warning("X: auth_token cookie set but still redirected to login — token may be expired.")
        else:
            log.info("X: auth_token cookie set and session active.")
    except Exception as e:
        log.warning(f"X: failed to set auth_token: {e}")


def _scrape_search(page, query: str) -> list[Job]:
    """Run a single search query and extract job-like tweets."""
    jobs = []
    import urllib.parse
    encoded_query = urllib.parse.quote(query)
    url = f"https://x.com/search?q={encoded_query}&src=typed_query&f=live"
    
    log.info(f"X: Navigating to {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    except Exception as e:
        log.warning(f"X: Navigation timeout or error: {e}")

    # Give the SPA extra time to load results regardless of networkidle
    page.wait_for_timeout(10000)

    # Check if we got redirected to explore/login
    current_url = page.url
    if "/explore" in current_url:
        log.warning(f"X: redirected to explore — search failed for '{query}'. Auth might be required.")
        return jobs
    if "/login" in current_url or "/i/flow/login" in current_url:
        log.warning(f"X: redirected to login — auth_token may be expired.")
        return jobs

    # Wait for tweets to load
    tweet_selector = 'article[data-testid="tweet"]'
    try:
        page.wait_for_selector(tweet_selector, timeout=15_000)
    except Exception:
        log.warning(f"X: no tweets found for '{query}' (timeout)")
        return jobs

    # Scroll to load more tweets
    for _ in range(MAX_SCROLLS):
        page.mouse.wheel(0, 3000)
        time.sleep(SCROLL_PAUSE)

    # Extract all tweet articles
    tweets = page.query_selector_all(tweet_selector)
    log.debug(f"X: found {len(tweets)} tweets for '{query}'")

    for tweet in tweets:
        try:
            job = _parse_tweet(tweet)
            if job:
                jobs.append(job)
        except Exception as e:
            log.debug(f"X: error parsing tweet: {e}")
            continue

    return jobs


def _parse_tweet(tweet) -> Job | None:
    """Parse a tweet element into a Job if it looks like a job posting."""
    # Get tweet text
    text_el = tweet.query_selector('div[data-testid="tweetText"]')
    if not text_el:
        return None
    text = text_el.inner_text().strip()

    if not text or len(text) < 30:
        return None

    # Must contain job-related signals
    text_lower = text.lower()
    job_signals = ["hiring", "looking for", "job opening", "open position",
                   "we're hiring", "we are hiring", "join our team",
                   "apply now", "job alert", "vacancy", "developer needed",
                   "engineer needed", "career opportunity"]
    if not any(signal in text_lower for signal in job_signals):
        return None

    # Extract title — try to find a job title in the first few lines
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    title = _extract_title(lines, text_lower)
    if not title:
        return None

    # Get tweet permalink and posted time
    time_el = tweet.query_selector("time")
    posted_at = None
    if time_el:
        dt_attr = time_el.get_attribute("datetime")
        posted_at = _parse_date(dt_attr)
    
    # Try to find the tweet URL
    tweet_url = ""
    if time_el:
        # Check if it has a parent anchor
        link_el = time_el.query_selector("xpath=ancestor::a")
        if link_el:
            href = link_el.get_attribute("href")
            if href:
                tweet_url = f"https://x.com{href}" if not href.startswith("http") else href

    if not tweet_url:
        # Fallback: find any link in the tweet that looks like a status URL
        links = tweet.query_selector_all('a[href*="/status/"]')
        for link in links:
            href = link.get_attribute("href") or ""
            if "/status/" in href:
                tweet_url = f"https://x.com{href}" if not href.startswith("http") else href
                break

    # Extract company from the user display name
    name_el = tweet.query_selector('div[data-testid="User-Name"]')
    company = ""
    if name_el:
        # The display name is usually the first span inside a div
        display_name_el = name_el.query_selector('span')
        if display_name_el:
            company = display_name_el.inner_text().strip()

    # Try to refine company from text (e.g., "at Google", "at OpenAI")
    company_patterns = [
        r'(?:at|join|with)\s+([A-Z][a-zA-Z0-9\s&]{2,30})(?:\s|!|\.|\n|$)',
    ]
    for pattern in company_patterns:
        match = re.search(pattern, text)
        if match:
            found_company = match.group(1).strip()
            # If the display name is generic, use the one found in text
            if len(found_company) > 3 and not any(w in found_company.lower() for w in ["hiring", "job", "alert", "tech"]):
                company = found_company
                break

    # Try to extract location from text
    location = _extract_location(text)

    # Check for remote
    is_remote = any(w in text_lower for w in ["remote", "work from home", "wfh",
                                               "anywhere", "distributed"])

    # Extract apply link if present
    apply_url = _extract_apply_link(tweet, text)
    job_url = apply_url or tweet_url

    # Extract salary if mentioned
    salary_raw = _extract_salary(text)

    return Job(
        title=title,
        company=company,
        location=location or ("Remote" if is_remote else ""),
        url=job_url,
        source="x",
        original_source="X (Twitter)",
        salary_raw=salary_raw,
        is_remote=is_remote,
        posted_at=posted_at,
    )


def _extract_title(lines: list[str], text_lower: str) -> str:
    """Try to extract a job title from tweet lines."""
    # Clean hashtags and mentions from lines
    # Only remove hashtags/mentions if they are at the end or standalone
    clean_lines = []
    for l in lines:
        # Remove standalone hashtags/mentions
        l = re.sub(r'^[#@]\S+\s*', '', l)
        l = re.sub(r'\s*[#@]\S+$', '', l)
        l = l.strip()
        if l:
            clean_lines.append(l)
    
    if not clean_lines:
        return ""

    # Common title patterns
    patterns = [
        r'(?:hiring|looking for|seeking)\s*(?:a|an)?\s*([A-Z][^!\n\.,]{5,80})(?:\s+at|\s+for|\n|$|!|\.|,)',
        r'(?:position|role|opening|needed):\s*([A-Z][^!\n\.,]{5,80})(?:\n|$|!|\.|,)',
    ]
    
    # Try case-sensitive patterns first for better quality
    for pattern in patterns:
        match = re.search(pattern, " ".join(clean_lines))
        if match:
            return match.group(1).strip()

    # Keywords that suggest a job title line
    role_keywords = ["engineer", "developer", "architect", "scientist", "tester", "sre", "devops", "lead", "staff", "principal"]
    
    role_lines = []
    for line in clean_lines:
        line_lower = line.lower()
        if any(kw in line_lower for kw in role_keywords):
            # Avoid long hyphenated slugs from URLs
            if line.count('-') > 3 and len(line) > 30:
                continue
                
            # Clean up prefixes
            t = re.sub(r'^(?:new job alert|hiring|we are hiring|vacancy|needed|needed[:])[:\s]*', '', line, flags=re.IGNORECASE).strip()
            t = re.sub(r'[!.,\s]+$', '', t)
            
            # Remove trailing hashtags again
            t = re.sub(r'\s*#\S+$', '', t)
            
            if 5 < len(t) < 100:
                role_lines.append(t)
    
    if role_lines:
        return role_lines[0] # Return the first matching line

    # Fallback
    for line in clean_lines[:2]:
        if 5 < len(line) < 80 and not any(w in line.lower() for w in ["job alert", "new job"]):
            return line

    return ""


def _extract_location(text: str) -> str:
    """Try to pull location info from tweet text."""
    loc_patterns = [
        r'(?:location|based in|located in|office in)[:\s]+([A-Za-z, ]+)',
        r'📍\s*([A-Za-z, ]+)',
    ]
    for pattern in loc_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()[:80]
    return ""


def _extract_apply_link(tweet, text: str) -> str:
    """Try to find an external apply link in the tweet."""
    # Check for t.co links that are not x.com internal
    links = tweet.query_selector_all('a[href]')
    for link in links:
        href = link.get_attribute("href") or ""
        # External links in tweets use t.co redirects
        if "t.co/" in href:
            displayed = link.inner_text().strip()
            # Skip x.com internal links
            if displayed and not displayed.startswith("x.com") and not displayed.startswith("twitter.com"):
                return href
    return ""


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse an ISO date string into a timezone-aware datetime."""
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def _extract_salary(text: str) -> str:
    """Try to extract salary info from text."""
    salary_patterns = [
        r'(\$[\d,]+\s*[-–]\s*\$[\d,]+(?:\s*(?:k|K|/yr|/year|per year))?)',
        r'([\d,]+\s*[-–]\s*[\d,]+\s*(?:USD|EUR|GBP|EGP))',
        r'(?:salary|comp|compensation)[:\s]+([^\n]{5,50})',
    ]
    for pattern in salary_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""
