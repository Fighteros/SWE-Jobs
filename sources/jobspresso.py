"""Jobspresso — curated remote jobs RSS feed (no key)."""

import html
import logging
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from core.models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

FEED = "https://jobspresso.co/feed/?post_type=job_listing"
DC = "{http://purl.org/dc/elements/1.1/}"


def fetch_jobspresso() -> list[Job]:
    xml_text = get_text(FEED)
    if not xml_text:
        log.warning("Jobspresso: no data")
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        log.warning(f"Jobspresso: XML parse error: {e}")
        return []

    jobs = []
    for item in root.findall(".//item"):
        link = (item.findtext("link") or "").strip()
        title = html.unescape(item.findtext("title") or "").strip()
        if not link or not title:
            continue
        # dc:creator looks like "Company<br>⚲ Location"
        creator = html.unescape(item.findtext(f"{DC}creator") or "")
        company, _, location = re.sub(r"\s+", " ", creator.replace("&nbsp;", " ")).partition("<br>")
        location = location.replace("⚲", "").strip() or "Remote"
        jobs.append(Job(
            title=title,
            company=company.strip(),
            location=location,
            url=link,
            source="jobspresso",
            tags=[c.text for c in item.findall("category") if c.text],
            is_remote=True,
            posted_at=_parse_date(item.findtext("pubDate")),
        ))
    log.debug(f"Jobspresso: fetched {len(jobs)} jobs.")
    return jobs


def _parse_date(value):
    try:
        return parsedate_to_datetime(value) if value else None
    except (TypeError, ValueError):
        return None
