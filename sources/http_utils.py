"""
Shared HTTP helpers. All network access goes through Scrapling.

- Plain APIs/feeds/HTML: Scrapling's ``Fetcher`` (curl_cffi, Chrome TLS fingerprint).
- Cloudflare-protected pages (Wuzzuf): ``get_protected_html`` escalates to a
  reusable ``StealthySession`` that solves the Cloudflare challenge.
"""

import atexit
import json
import logging
import threading

from scrapling.fetchers import Fetcher, StealthySession

from core.config import REQUEST_TIMEOUT

log = logging.getLogger(__name__)

_RETRIES = 2
_HEADERS = {"Accept-Language": "en-US,en;q=0.9"}

# Statuses that are expected for dead/limited endpoints and logged quietly.
_QUIET_STATUSES = (404, 429)


def _fetch(method: str, url: str, params: dict = None, headers: dict = None,
           timeout: int = REQUEST_TIMEOUT, json_body: dict = None):
    """Run one Scrapling request. Returns a response, or None on error/non-2xx."""
    kwargs = dict(
        headers={**_HEADERS, **(headers or {})}, timeout=timeout, retries=_RETRIES,
        impersonate="chrome", stealthy_headers=True,
    )
    if params:
        kwargs["params"] = params
    try:
        if method == "POST":
            response = Fetcher.post(url, json=json_body, **kwargs)
        else:
            response = Fetcher.get(url, **kwargs)
    except Exception as exc:  # curl_cffi raises its own hierarchy
        log.warning("%s %s failed: %s", method, url, type(exc).__name__)
        return None
    if not 200 <= response.status < 300:
        level = logging.DEBUG if response.status in _QUIET_STATUSES else logging.WARNING
        log.log(level, "%s %s failed: HTTP %s", method, url, response.status)
        return None
    return response


def _decode(response) -> str:
    return response.body.decode(response.encoding or "utf-8", errors="replace")


def get_json(url: str, params: dict = None, headers: dict = None,
             timeout: int = REQUEST_TIMEOUT) -> dict | list | None:
    """GET request returning parsed JSON, or None on error."""
    response = _fetch("GET", url, params, headers, timeout)
    return _parse_json(response, url)


def post_json(url: str, payload: dict = None, headers: dict = None,
              timeout: int = REQUEST_TIMEOUT) -> dict | list | None:
    """POST request with JSON body, returning parsed JSON or None."""
    response = _fetch("POST", url, None, headers, timeout, json_body=payload)
    return _parse_json(response, url)


def _parse_json(response, url: str):
    if response is None:
        return None
    try:
        return json.loads(_decode(response))
    except ValueError as exc:
        log.warning("JSON parse error for %s: %s", url, exc)
        return None


def get_text(url: str, params: dict = None, headers: dict = None,
             timeout: int = REQUEST_TIMEOUT) -> str | None:
    """GET request returning raw text, or None on error."""
    response = _fetch("GET", url, params, headers, timeout)
    return _decode(response) if response is not None else None


def get_public_html(url: str, params: dict = None, headers: dict = None,
                    timeout: int = REQUEST_TIMEOUT) -> str | None:
    """Fetch public listing HTML. Does not try to get past access challenges."""
    return get_text(url, params=params, headers=headers, timeout=timeout)


# --- Cloudflare-protected pages -------------------------------------------

_stealth_lock = threading.Lock()
_stealth_session: StealthySession | None = None


def _challenge(html: str) -> bool:
    lowered = html[:4000].lower()
    return "just a moment" in lowered or "cf-chl" in lowered or "attention required" in lowered


def _get_stealth_session() -> StealthySession:
    global _stealth_session
    if _stealth_session is None:
        _stealth_session = StealthySession(
            headless=True, solve_cloudflare=True, network_idle=False,
            timeout=60_000,
        )
        _stealth_session.start()
        atexit.register(close_stealth_session)
    return _stealth_session


def close_stealth_session() -> None:
    """Close the shared stealth browser (also runs at interpreter exit)."""
    global _stealth_session
    with _stealth_lock:
        if _stealth_session is not None:
            try:
                _stealth_session.close()
            except Exception:
                log.debug("stealth session close failed", exc_info=True)
            _stealth_session = None


def get_protected_html(url: str, params: dict = None, headers: dict = None,
                       timeout: int = REQUEST_TIMEOUT) -> str | None:
    """
    Fetch a page that may sit behind Cloudflare.

    Tries the fast Scrapling ``Fetcher`` first. On 403/503 or a challenge page it
    retries once in a shared StealthySession with ``solve_cloudflare=True``.
    """
    response = None
    try:
        response = Fetcher.get(
            url, params=params or None, headers={**_HEADERS, **(headers or {})},
            timeout=timeout, retries=1, impersonate="chrome", stealthy_headers=True,
        )
    except Exception as exc:
        log.warning("GET %s failed: %s", url, type(exc).__name__)
    if response is not None and 200 <= response.status < 300:
        html = _decode(response)
        if not _challenge(html):
            return html

    full_url = url
    if params:
        from urllib.parse import urlencode
        full_url = f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"
    with _stealth_lock:
        try:
            page = _get_stealth_session().fetch(full_url)
        except Exception as exc:
            log.warning("Stealth GET %s failed: %s", full_url, type(exc).__name__)
            return None
    if not 200 <= page.status < 300:
        log.warning("Stealth GET %s rejected: HTTP %s", full_url, page.status)
        return None
    html = _decode(page)
    if _challenge(html):
        log.warning("Stealth GET %s still shows a challenge", full_url)
        return None
    return html
