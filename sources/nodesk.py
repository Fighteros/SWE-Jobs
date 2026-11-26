"""NoDesk — remote jobs RSS feed (no key). Titles look like 'Role at Company'."""

import html
import logging
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from core.models import Job
from sources.http_utils import get_text

log = logging.getLogger(__name__)

FEED = "https://nodesk.co/remote-jobs/index.xml"


def fetch_nodesk() -> list[Job]:
    xml_text = get_text(FEED)
    if not xml_text:
        log.warning("NoDesk: no data")
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        log.warning(f"NoDesk: XML parse error: {e}")
        return []

    jobs = []
    for item in root.findall(".//item"):
        link = (item.findtext("link") or "").strip()
        raw = html.unescape(item.findtext("title") or "").strip()
        if not link or not raw:
            continue
        title, sep, company = raw.rpartition(" at ")
        if not sep:
            title, company = raw, ""
        jobs.append(Job(
            title=title.strip(),
            company=company.strip(),
            location="Remote",
            url=link,
            source="nodesk",
            tags=[c.text for c in item.findall("category") if c.text],
            is_remote=True,
            posted_at=_parse_date(item.findtext("pubDate")),
        ))
    log.debug(f"NoDesk: fetched {len(jobs)} jobs.")
    return jobs


def _parse_date(value):
    try:
        return parsedate_to_datetime(value) if value else None
    except (TypeError, ValueError):
        return None
