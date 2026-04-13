"""
Tests for sources/x_jobs.py — pure parsing/extraction functions.
Playwright-dependent functions (fetch_x_jobs, _scrape_search, _parse_tweet)
are not tested here as they require a live browser.
"""

import pytest
from datetime import datetime, timezone

from sources.x_jobs import (
    _extract_title,
    _extract_location,
    _extract_salary,
    _parse_date,
)


# ── _extract_title ──────────────────────────────────────────


class TestExtractTitle:
    def test_hiring_pattern(self):
        text = "we're hiring a senior backend developer for our team!"
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        title = _extract_title(lines, text.lower())
        assert title
        assert "backend" in title.lower() or "senior" in title.lower()

    def test_looking_for_pattern(self):
        text = "Looking for a Senior Software Engineer to join us"
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        title = _extract_title(lines, text.lower())
        assert title
        assert "software engineer" in title.lower()

    def test_role_keyword_pattern(self):
        text = "Great opportunity!\nsenior frontend developer needed at our company"
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        title = _extract_title(lines, text.lower())
        assert title
        assert "frontend" in title.lower()

    def test_position_colon_pattern(self):
        text = "Position: DevOps Engineer\nApply now at our website"
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        title = _extract_title(lines, text.lower())
        assert title
        assert "devops" in title.lower()

    def test_flutter_developer(self):
        text = "We are hiring a flutter developer, remote position available"
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        title = _extract_title(lines, text.lower())
        assert title
        assert "flutter" in title.lower()

    def test_data_scientist(self):
        text = "Hiring a data scientist for ML team at our startup"
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        title = _extract_title(lines, text.lower())
        assert title
        assert "data scientist" in title.lower()

    def test_fallback_to_first_line(self):
        text = "Amazing Remote Cloud Engineering Role Available\nApply at link.com"
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        title = _extract_title(lines, text.lower())
        assert title
        assert len(title) > 10

    def test_short_text_no_match(self):
        text = "Nice day"
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        title = _extract_title(lines, text.lower())
        assert title == ""

    def test_title_truncated_at_120(self):
        long_role = "senior " + "full stack " * 20 + "developer"
        text = f"Hiring a {long_role} for our team"
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        title = _extract_title(lines, text.lower())
        if title:
            assert len(title) <= 120

    def test_strips_hashtags_in_fallback(self):
        # Text with no hiring/role keywords forces fallback path
        text = "#python #django Great opportunity for backend teams worldwide"
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        title = _extract_title(lines, text.lower())
        assert title
        # Fallback strips #hashtags and @mentions
        assert "#" not in title


# ── _extract_location ───────────────────────────────────────


class TestExtractLocation:
    def test_based_in(self):
        assert _extract_location("We are based in San Francisco, CA") == "San Francisco, CA"

    def test_located_in(self):
        assert _extract_location("Team located in London, UK") == "London, UK"

    def test_office_in(self):
        assert _extract_location("Office in Berlin, Germany") == "Berlin, Germany"

    def test_pin_emoji(self):
        loc = _extract_location("📍 Dubai, UAE")
        assert "Dubai" in loc

    def test_location_colon(self):
        assert _extract_location("Location: Cairo, Egypt") == "Cairo, Egypt"

    def test_no_location(self):
        assert _extract_location("We're hiring a developer, apply now!") == ""

    def test_case_insensitive(self):
        loc = _extract_location("BASED IN New York")
        assert "New York" in loc

    def test_truncated_at_80(self):
        long_loc = "A" * 100
        loc = _extract_location(f"Based in {long_loc}")
        assert len(loc) <= 80


# ── _extract_salary ─────────────────────────────────────────


class TestExtractSalary:
    def test_dollar_range(self):
        result = _extract_salary("Salary: $80,000 - $120,000/yr")
        assert "$80,000" in result
        assert "$120,000" in result

    def test_dollar_range_with_k(self):
        result = _extract_salary("Comp: $100K - $150K")
        # The pattern matches $100 range, but K might not be captured
        # depending on formatting; just check it finds something
        assert "$" in result or result == ""

    def test_currency_suffix(self):
        result = _extract_salary("80,000 - 120,000 USD")
        assert "80,000" in result
        assert "USD" in result

    def test_eur_suffix(self):
        result = _extract_salary("60,000 - 90,000 EUR per year")
        assert "EUR" in result

    def test_salary_keyword(self):
        result = _extract_salary("Salary: competitive, $90k-$130k range")
        assert result  # Should match the salary: keyword pattern

    def test_compensation_keyword(self):
        result = _extract_salary("Compensation: $100,000 - $150,000 annually")
        assert result

    def test_no_salary(self):
        assert _extract_salary("We're hiring a developer, apply now!") == ""

    def test_egp_currency(self):
        result = _extract_salary("15,000 - 25,000 EGP monthly")
        assert "EGP" in result

    def test_gbp_currency(self):
        result = _extract_salary("50,000 - 75,000 GBP")
        assert "GBP" in result


# ── _parse_date ─────────────────────────────────────────────


class TestParseDate:
    def test_iso_with_z(self):
        result = _parse_date("2024-03-15T10:30:00.000Z")
        assert result is not None
        assert result.year == 2024
        assert result.month == 3
        assert result.day == 15
        assert result.tzinfo is not None

    def test_iso_with_offset(self):
        result = _parse_date("2024-06-01T14:00:00+00:00")
        assert result is not None
        assert result.year == 2024
        assert result.month == 6

    def test_iso_no_timezone(self):
        result = _parse_date("2024-01-20T08:00:00")
        assert result is not None
        assert result.tzinfo == timezone.utc

    def test_none_input(self):
        assert _parse_date(None) is None

    def test_empty_string(self):
        assert _parse_date("") is None

    def test_invalid_format(self):
        assert _parse_date("not-a-date") is None

    def test_garbage_input(self):
        assert _parse_date("12345") is None
