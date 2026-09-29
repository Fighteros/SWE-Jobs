"""
Shared Playwright browser helpers for scrapers that need JS rendering.

Usage:
    from sources.playwright_utils import get_browser_page

    with get_browser_page() as page:
        page.goto("https://example.com")
        html = page.content()
"""

import logging
import re
from pathlib import Path
from contextlib import contextmanager
from playwright.sync_api import sync_playwright

log = logging.getLogger(__name__)

# Default timeout for page loads (ms)
PAGE_TIMEOUT = 30_000


def normalize_cookies(cookies, default_domain: str) -> list[dict]:
    """Convert common browser-export cookie formats to Playwright cookies."""
    if isinstance(cookies, dict):
        cookies = cookies.get("cookies", [])
    if not isinstance(cookies, list):
        return []

    same_site_values = {
        "strict": "Strict",
        "lax": "Lax",
        "none": "None",
        "no_restriction": "None",
    }
    result = []
    for cookie in cookies:
        if not isinstance(cookie, dict) or not cookie.get("name") or cookie.get("value") is None:
            continue
        item = {
            "name": str(cookie["name"]),
            "value": str(cookie["value"]),
            "domain": cookie.get("domain") or default_domain,
            "path": cookie.get("path") or "/",
            "secure": bool(cookie.get("secure", True)),
            "httpOnly": bool(cookie.get("httpOnly", False)),
        }
        same_site = re.sub(r"[\s-]+", "_", str(cookie.get("sameSite") or "")).lower()
        if same_site in same_site_values:
            item["sameSite"] = same_site_values[same_site]
        result.append(item)
    return result


@contextmanager
def get_browser_page(headless: bool = True, user_data_dir: str = ""):
    """
    Context manager that yields a Playwright page.
    Launches Chromium, creates a single page, and tears everything down on exit.
    """
    pw = sync_playwright().start()
    try:
        browser = None
        launch_options = {"headless": headless}
        if user_data_dir:
            profile = Path(user_data_dir)
            profile.mkdir(parents=True, exist_ok=True)
            context = pw.chromium.launch_persistent_context(
                str(profile),
                **launch_options,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
        else:
            browser = pw.chromium.launch(**launch_options)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
        page = context.new_page()
        page.set_default_timeout(PAGE_TIMEOUT)
        yield page
    except Exception as e:
        log.error(f"Playwright browser error: {e}")
        raise
    finally:
        try:
            context.close()
        except Exception:
            pass
        try:
            if browser:
                browser.close()
        except Exception:
            pass
        pw.stop()
