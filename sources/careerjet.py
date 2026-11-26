"""Careerjet — job search API v4 (free publisher account, needs API key).

Docs: https://www.careerjet.com/partners/api/
The key is the Basic-auth user name with an empty password. Careerjet also
requires the end user's IP, user agent and a Referer on every call; for a
background collector these are the server's own values.
"""

import base64
import logging
import os
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from core.config import CAREERJET_API_KEY
from core.models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)

URL = "https://search.api.careerjet.net/v4/query"
REFERER = os.getenv("CAREERJET_REFERER", "https://github.com/Fighteros/SWE-Jobs")
USER_IP = os.getenv("CAREERJET_USER_IP", "127.0.0.1")
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36"

SEARCHES = [
    {"locale_code": "en_EG", "keywords": "software engineer", "location": "Egypt"},
    {"locale_code": "en_EG", "keywords": "backend developer", "location": "Egypt"},
    {"locale_code": "en_AE", "keywords": "software engineer", "location": "United Arab Emirates"},
    {"locale_code": "en_SA", "keywords": "software engineer", "location": "Saudi Arabia"},
    {"locale_code": "en_GB", "keywords": "backend developer remote", "location": "United Kingdom"},
    {"locale_code": "en_US", "keywords": "backend developer remote", "location": "United States"},
]


def fetch_careerjet() -> list[Job]:
    if not CAREERJET_API_KEY:
        log.debug("Careerjet: skipped (no API key)")
        return []

    token = base64.b64encode(f"{CAREERJET_API_KEY}:".encode()).decode()
    headers = {"Authorization": f"Basic {token}", "Referer": REFERER}
    jobs = []
    for search in SEARCHES:
        params = {**search, "user_ip": USER_IP, "user_agent": USER_AGENT,
                  "sort": "date", "page_size": 50}
        data = get_json(URL, params=params, headers=headers)
        if not isinstance(data, dict) or data.get("type") not in (None, "JOBS"):
            continue
        for item in data.get("jobs", []):
            url = item.get("url", "")
            if not url:
                continue
            jobs.append(Job(
                title=item.get("title", ""),
                company=item.get("company", ""),
                location=item.get("locations", ""),
                url=url,
                source="careerjet",
                salary_raw=item.get("salary", ""),
                is_remote="remote" in f"{item.get('title', '')} {item.get('locations', '')}".lower(),
                posted_at=_parse_date(item.get("date")),
            ))
    log.debug(f"Careerjet: fetched {len(jobs)} jobs.")
    return jobs


def _parse_date(value):
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
