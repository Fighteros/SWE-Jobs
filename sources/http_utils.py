"""
Shared HTTP helpers with session reuse, timeouts, and error handling.
"""

import logging
import os
import requests
from core.config import REQUEST_TIMEOUT

log = logging.getLogger(__name__)

_session = requests.Session()
_session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
})


def get_json(url: str, params: dict = None, headers: dict = None,
             timeout: int = REQUEST_TIMEOUT) -> dict | list | None:
    """GET request returning parsed JSON, or None on error."""
    try:
        resp = _session.get(url, params=params, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        status = e.response.status_code if e.response is not None else None
        if status in (404, 429):
            log.debug(f"GET {url} failed ({status}): {e}")
        else:
            log.warning(f"GET {url} failed: {e}")
        return None
    except ValueError as e:
        log.warning(f"JSON parse error for {url}: {e}")
        return None


def post_json(url: str, payload: dict = None, headers: dict = None,
              timeout: int = REQUEST_TIMEOUT) -> dict | list | None:
    """POST request with JSON body, returning parsed JSON or None."""
    try:
        resp = _session.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        status = e.response.status_code if e.response is not None else None
        if status in (404, 429):
            log.debug(f"POST {url} failed ({status}): {e}")
        else:
            log.warning(f"POST {url} failed: {e}")
        return None
    except ValueError as e:
        log.warning(f"JSON parse error for {url}: {e}")
        return None


def get_text(url: str, params: dict = None, headers: dict = None,
             timeout: int = REQUEST_TIMEOUT) -> str | None:
    """GET request returning raw text, or None on error."""
    try:
        resp = _session.get(url, params=params, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        status = e.response.status_code if e.response is not None else None
        if status in (404, 429):
            log.debug(f"GET text {url} failed ({status}): {e}")
        else:
            log.warning(f"GET text {url} failed: {e}")
        return None


def get_public_html(url: str, params: dict = None, headers: dict = None,
                    timeout: int = REQUEST_TIMEOUT) -> str | None:
    """Fetch public listing HTML; switching transport does not bypass denials."""
    if os.getenv("JOB_HTML_TRANSPORT", "requests") != "scrapling":
        return get_text(url, params=params, headers=headers, timeout=timeout)

    from curl_cffi.requests.exceptions import RequestException
    from scrapling.fetchers import Fetcher

    try:
        response = Fetcher.get(
            url, params=params, headers={"User-Agent": "SWE-Jobs/1.0", **(headers or {})},
            timeout=timeout, retries=1, impersonate="", stealthy_headers=False,
        )
        if not 200 <= response.status < 300:
            log.warning("Public listing GET rejected: HTTP %s", response.status)
            return None
        return response.body.decode(response.encoding or "utf-8", errors="replace")
    except (RequestException, LookupError, ValueError) as exc:
        log.warning("Public listing GET failed: %s", type(exc).__name__)
        return None
