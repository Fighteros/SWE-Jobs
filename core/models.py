"""
Job dataclass — the central data model for SWE-Jobs v2.

All job data flows through this model: fetching, filtering,
deduplication, DB persistence, and Telegram formatting.
"""

from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

from core.channels import EMOJI_MAP, DEFAULT_EMOJI, SOURCE_DISPLAY


def _flatten_tags(tags) -> str:
    """Safely flatten tags to a space-joined string, handling nested lists and dicts."""
    if not tags:
        return ""
    flat = []
    for item in tags:
        if isinstance(item, list):
            flat.extend(str(i) for i in item)
        elif isinstance(item, dict):
            flat.append(str(item.get("name", item.get("label", ""))))
        else:
            flat.append(str(item))
    return " ".join(flat)


def _strip_utm(url: str) -> str:
    """Remove UTM tracking parameters from a URL."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    cleaned = {k: v for k, v in params.items() if not k.lower().startswith("utm")}
    new_query = urlencode(cleaned, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


@dataclass
class Job:
    # Required fields
    title: str
    company: str
    location: str
    url: str
    source: str

    # Salary info
    salary_raw: str = ""
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: str = ""

    # Job metadata
    job_type: str = ""
    seniority: str = "mid"
    is_remote: bool = False
    country: str = ""

    # Taxonomy
    tags: list = field(default_factory=list)
    topics: list = field(default_factory=list)

    # Source tracking
    original_source: str = ""

    # Telegram delivery tracking: {channel_key: message_id}
    telegram_message_ids: dict = field(default_factory=dict)

    def __post_init__(self):
        # Ensure tags is never None
        if self.tags is None:
            self.tags = []
        if self.topics is None:
            self.topics = []
        if self.telegram_message_ids is None:
            self.telegram_message_ids = {}
        # Some APIs return job_type as a list — coerce to string
        if isinstance(self.job_type, list):
            self.job_type = ", ".join(str(t) for t in self.job_type if t)

    # ─── Properties ─────────────────────────────────────────────

    @property
    def unique_id(self) -> str:
        """
        Stable unique identifier for deduplication.
        Prefers URL (normalised: UTM stripped, trailing slash removed, lowercased).
        Falls back to "title|company" when URL is empty.
        """
        if self.url:
            clean = _strip_utm(self.url)
            clean = clean.rstrip("/").lower()
            return clean
        return f"{self.title.lower().strip()}|{self.company.lower().strip()}"

    @property
    def display_source(self) -> str:
        """
        Human-readable source label.
        Returns original_source when set (e.g. for JSearch aggregator),
        otherwise looks up SOURCE_DISPLAY, falling back to title-cased source key.
        """
        if self.original_source:
            return self.original_source
        value = SOURCE_DISPLAY.get(self.source)
        if value is None and self.source in SOURCE_DISPLAY:
            # Explicitly mapped to None (e.g. jsearch) — but no original_source set
            return self.source.title()
        if value is not None:
            return value
        return self.source.title()

    @property
    def emoji(self) -> str:
        """
        Pick the best emoji by scanning title + location + tags against EMOJI_MAP.
        Returns DEFAULT_EMOJI when nothing matches.
        """
        text = f"{self.title} {self.location} {_flatten_tags(self.tags)}".lower()
        for keyword, em in EMOJI_MAP.items():
            if keyword in text:
                return em
        return DEFAULT_EMOJI

    @property
    def salary_display(self) -> str:
        """Format salary for human display."""
        if self.salary_min and self.salary_max:
            currency = self.salary_currency or "$"
            return f"{currency}{self.salary_min:,} – {currency}{self.salary_max:,}"
        if self.salary_raw:
            return self.salary_raw
        return ""

    # ─── DB Serialisation ────────────────────────────────────────

    def to_db_row(self) -> dict:
        """
        Serialize to a dict suitable for a psycopg2 INSERT/UPDATE.
        telegram_message_ids is wrapped with psycopg2.extras.Json for JSONB columns.
        """
        from psycopg2.extras import Json

        return {
            "unique_id": self.unique_id,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "url": self.url,
            "source": self.source,
            "salary_raw": self.salary_raw,
            "salary_min": self.salary_min,
            "salary_max": self.salary_max,
            "salary_currency": self.salary_currency,
            "job_type": self.job_type,
            "seniority": self.seniority,
            "is_remote": self.is_remote,
            "country": self.country,
            "tags": self.tags,
            "topics": self.topics,
            "original_source": self.original_source,
            "telegram_message_ids": Json(self.telegram_message_ids),
        }

    @classmethod
    def from_db_row(cls, row: dict) -> "Job":
        """
        Reconstruct a Job from a DB row dict.
        Handles both plain dicts (from psycopg2 RealDictRow) and extra columns
        like unique_id that are not fields on the dataclass.
        """
        telegram_ids = row.get("telegram_message_ids") or {}
        # If psycopg2 returned a Json wrapper, unwrap it
        if hasattr(telegram_ids, "adapted"):
            telegram_ids = telegram_ids.adapted

        return cls(
            title=row.get("title", ""),
            company=row.get("company", ""),
            location=row.get("location", ""),
            url=row.get("url", ""),
            source=row.get("source", ""),
            salary_raw=row.get("salary_raw", ""),
            salary_min=row.get("salary_min"),
            salary_max=row.get("salary_max"),
            salary_currency=row.get("salary_currency", ""),
            job_type=row.get("job_type", ""),
            seniority=row.get("seniority", "mid"),
            is_remote=row.get("is_remote", False),
            country=row.get("country", ""),
            tags=row.get("tags") or [],
            topics=row.get("topics") or [],
            original_source=row.get("original_source", ""),
            telegram_message_ids=telegram_ids,
        )
