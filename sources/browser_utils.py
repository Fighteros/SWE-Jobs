"""
Shared browser helpers for scrapers that need JS rendering.

The browser is Scrapling's StealthySession (patchright, anti-detection patches,
Cloudflare solving). The page it yields exposes the usual page API.

Usage:
    from sources.browser_utils import get_browser_page

    with get_browser_page() as page:
        page.goto("https://example.com")
        html = page.content()
"""

import logging
import re
from pathlib import Path
from contextlib import contextmanager
from scrapling.fetchers import StealthySession

log = logging.getLogger(__name__)

# Default timeout for page loads (ms)
PAGE_TIMEOUT = 30_000


def normalize_cookies(cookies, default_domain: str) -> list[dict]:
    """Convert common browser-export cookie formats to browser cookies."""
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
    Context manager that yields a page from a Scrapling StealthySession.
    Starts the stealth browser, opens one page, and tears everything down on exit.
    """
    options = {
        "headless": headless,
        "solve_cloudflare": True,
        "network_idle": False,
        "timeout": PAGE_TIMEOUT,
        "locale": "en-US",
    }
    if user_data_dir:
        Path(user_data_dir).mkdir(parents=True, exist_ok=True)
        options["user_data_dir"] = str(user_data_dir)
    session = StealthySession(**options)
    page = None
    try:
        session.start()
        page = session.context.new_page()
        page.set_default_timeout(PAGE_TIMEOUT)
        yield page
    except Exception as e:
        log.error(f"Browser error: {e}")
        raise
    finally:
        try:
            if page:
                page.close()
        except Exception:
            pass
        try:
            session.close()
        except Exception:
            pass
