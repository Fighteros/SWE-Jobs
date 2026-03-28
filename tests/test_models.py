"""
Tests for core/models.py — written first (TDD).
"""
import psycopg2.extras
import pytest
from core.models import Job


class TestJobUniqueId:
    def test_unique_id_from_url(self):
        job = Job(title="Dev", company="X", location="", url="https://example.com/jobs/1", source="remotive")
        assert job.unique_id == "https://example.com/jobs/1"

    def test_unique_id_strips_utm(self):
        job = Job(
            title="Dev", company="X", location="",
            url="https://example.com/jobs/1?utm_source=email",
            source="remotive",
        )
        assert job.unique_id == "https://example.com/jobs/1"

    def test_unique_id_strips_trailing_slash(self):
        job = Job(
            title="Dev", company="X", location="",
            url="https://example.com/jobs/1/",
            source="remotive",
        )
        assert job.unique_id == "https://example.com/jobs/1"

    def test_unique_id_lowercased(self):
        job = Job(
            title="Dev", company="X", location="",
            url="https://Example.COM/Jobs/1",
            source="remotive",
        )
        assert job.unique_id == "https://example.com/jobs/1"

    def test_unique_id_fallback_to_title_company(self):
        job = Job(title="Python Dev", company="Acme", location="", url="", source="remotive")
        assert job.unique_id == "python dev|acme"


class TestJobEmoji:
    def test_emoji_python(self):
        job = Job(title="Python Developer", company="X", location="", url="https://example.com/1", source="remotive")
        assert job.emoji == "🐍"

    def test_emoji_default(self):
        job = Job(title="Something Unusual", company="X", location="", url="https://example.com/1", source="remotive")
        assert job.emoji == "💻"


class TestJobDisplaySource:
    def test_display_source_known(self):
        job = Job(title="Dev", company="X", location="", url="https://example.com/1", source="remotive")
        assert job.display_source == "Remotive"

    def test_display_source_original(self):
        job = Job(
            title="Dev", company="X", location="",
            url="https://example.com/1",
            source="jsearch",
            original_source="LinkedIn",
        )
        assert job.display_source == "LinkedIn"


class TestJobToDbRow:
    def test_to_db_row_contains_all_fields(self, sample_job):
        row = sample_job.to_db_row()

        assert row["title"] == "Senior Python Developer"
        assert row["company"] == "Acme Corp"
        assert row["location"] == "Cairo, Egypt"
        assert row["url"] == "https://example.com/jobs/123"
        assert row["source"] == "remotive"
        assert row["salary_raw"] == "$80,000 - $120,000"
        assert row["job_type"] == "Full Time"
        assert row["tags"] == ["python", "django", "backend"]
        assert row["is_remote"] is True
        assert "unique_id" in row

    def test_to_db_row_telegram_message_ids_is_json(self, sample_job):
        row = sample_job.to_db_row()
        assert isinstance(row["telegram_message_ids"], psycopg2.extras.Json)


class TestJobFromDbRow:
    def test_from_db_row_roundtrip(self, sample_job):
        row = sample_job.to_db_row()
        # Simulate what psycopg2 returns: unwrap the Json wrapper back to a dict
        row["telegram_message_ids"] = sample_job.telegram_message_ids
        restored = Job.from_db_row(row)

        assert restored.title == sample_job.title
        assert restored.company == sample_job.company
        assert restored.location == sample_job.location
        assert restored.url == sample_job.url
        assert restored.source == sample_job.source
        assert restored.salary_raw == sample_job.salary_raw
        assert restored.job_type == sample_job.job_type
        assert restored.tags == sample_job.tags
        assert restored.is_remote == sample_job.is_remote
        assert restored.telegram_message_ids == sample_job.telegram_message_ids
