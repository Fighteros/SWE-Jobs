"""
HTTP client for the egytech.fyi public API.
Source: https://api.egytech.fyi (April 2024 Egyptian tech compensation survey).
Caches successful and 404 responses for 24h. Network errors are not cached.
"""

import logging
import time
from typing import Optional
from urllib.parse import urlencode

import requests

from core.egytech_mapping import SENIORITY_TO_LEVEL, TOPIC_TO_TITLE
from core.models import Job

log = logging.getLogger(__name__)

_BASE = "https://api.egytech.fyi"
_TIMEOUT = 5.0
_TTL_SECONDS = 24 * 3600

# Cache: { (title, level, yoe_from, yoe_to): (timestamp, response_dict_or_None) }
# A cached value of `None` means a 404 ("no participants for combo").
_cache: dict[tuple, tuple[float, Optional[dict]]] = {}


def get_stats(
    title: str,
    level: Optional[str] = None,
    yoe_from: Optional[int] = None,
    yoe_to: Optional[int] = None,
) -> Optional[dict]:
    """
    Fetch compensation stats from egytech.fyi.
    Pins include_relocated=false and include_remote_abroad=false.
    Returns the response dict on success, None on 404 or network error.
    """
    key = (title, level, yoe_from, yoe_to)
    now = time.time()

    cached = _cache.get(key)
    if cached:
        ts, data = cached
        if now - ts < _TTL_SECONDS:
            return data

    params: dict[str, str] = {
        "title": title,
        "include_relocated": "false",
        "include_remote_abroad": "false",
    }
    if level:
        params["level"] = level
    if yoe_from is not None:
        params["yoe_from_included"] = str(yoe_from)
    if yoe_to is not None:
        params["yoe_to_excluded"] = str(yoe_to)

    url = f"{_BASE}/stats?{urlencode(params)}"
    try:
        resp = requests.get(url, timeout=_TIMEOUT)
    except requests.RequestException as e:
        log.warning(f"egytech network error: {e}")
        return None

    if resp.status_code == 404:
        _cache[key] = (now, None)
        return None
    if resp.status_code != 200:
        log.warning(f"egytech unexpected status {resp.status_code} for {url}")
        return None

    data = resp.json()
    _cache[key] = (now, data)
    return data


def _round_thousands(n: int) -> str:
    return f"{int(round(n / 1000))}k"


def market_salary_for_job(job: Job) -> Optional[str]:
    """
    Return a human-readable EGP/mo p20–p75 range for an Egypt-based job, or None.
    Uses the job's primary topic + seniority to look up egytech stats.
    """
    if job.country != "EG":
        return None

    level = SENIORITY_TO_LEVEL.get(job.seniority)
    if level is None:
        return None

    title = None
    for topic in job.topics:
        if topic in TOPIC_TO_TITLE:
            title = TOPIC_TO_TITLE[topic]
            break
    if title is None:
        return None

    data = get_stats(title=title, level=level)
    if not data or "stats" not in data:
        return None

    stats = data["stats"]
    p20 = stats.get("p20Compensation")
    p75 = stats.get("p75Compensation")
    if not p20 or not p75:
        return None

    return f"EGP {_round_thousands(p20)}–{_round_thousands(p75)}/mo"
