"""Greenhouse Job Board API — fetches from curated tech company boards."""

import logging
from core.models import Job
from sources.http_utils import get_json

log = logging.getLogger(__name__)

BASE = "https://boards-api.greenhouse.io/v1/boards/{}/jobs"

# Curated tech company board tokens (verified active on Greenhouse)
BOARDS = [
    "cloudflare", "airbnb", "stripe",
    "twilio", "datadog", "gitlab", "discord",
    "coinbase", "brex", "airtable", "vercel",
    "gusto", "duolingo", "hubspot",
    "instacart", "coupang", "reddit",
]


def fetch_greenhouse() -> list[Job]:
    """Fetch jobs from Greenhouse company boards."""
    jobs = []
    for board in BOARDS:
        url = BASE.format(board)
        data = get_json(url, params={"content": "true"})
        if not data or "jobs" not in data:
            continue
        for item in data["jobs"]:
            title = item.get("title", "")
            abs_url = item.get("absolute_url", "")
            if not title or not abs_url:
                continue

            location = ""
            locs = item.get("location", {})
            if isinstance(locs, dict):
                location = locs.get("name", "")

            jobs.append(Job(
                title=title,
                company=board.replace("-", " ").title(),
                location=location or "Unknown",
                url=abs_url,
                source="greenhouse",
                original_source=f"greenhouse:{board}",
                tags=[],
                is_remote="remote" in location.lower() if location else False,
            ))
    log.debug(f"Greenhouse: fetched {len(jobs)} jobs across {len(BOARDS)} boards.")
    return jobs
