"""
Tests for core/db.py — written first (TDD).

All tests use mocks; no real DB connection required.
"""
import json
from unittest.mock import patch, MagicMock, call

import pytest

from core.db import (
    insert_job,
    get_job_by_unique_id,
    get_unsent_jobs,
    mark_job_sent,
    job_exists,
    start_run,
    finish_run,
)
from core.models import Job


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_job():
    return Job(
        title="Senior Python Developer",
        company="Acme Corp",
        location="Cairo, Egypt",
        url="https://example.com/jobs/123",
        source="remotive",
        salary_raw="$80,000 - $120,000",
        job_type="Full Time",
        tags=["python", "django"],
        is_remote=True,
    )


# ---------------------------------------------------------------------------
# TestInsertJob
# ---------------------------------------------------------------------------

class TestInsertJob:
    def test_insert_job_calls_execute(self, sample_job):
        """_execute is called and result containing id is returned."""
        with patch("core.db._execute", return_value={"id": 1}) as mock_exec:
            result = insert_job(sample_job)
            assert mock_exec.called
            assert result == {"id": 1}

    def test_insert_job_passes_all_fields(self, sample_job):
        """SQL passed to _execute contains INSERT INTO jobs."""
        with patch("core.db._execute", return_value={"id": 1}) as mock_exec:
            insert_job(sample_job)
            sql_arg = mock_exec.call_args[0][0]
            assert "INSERT INTO jobs" in sql_arg


# ---------------------------------------------------------------------------
# TestJobExists
# ---------------------------------------------------------------------------

class TestJobExists:
    def test_job_exists_true(self):
        """Returns True when _fetchone finds a row."""
        with patch("core.db._fetchone", return_value={"id": 1}):
            assert job_exists("https://example.com/jobs/123") is True

    def test_job_exists_false(self):
        """Returns False when _fetchone returns None."""
        with patch("core.db._fetchone", return_value=None):
            assert job_exists("https://example.com/jobs/999") is False


# ---------------------------------------------------------------------------
# TestGetJobByUniqueId
# ---------------------------------------------------------------------------

class TestGetJobByUniqueId:
    def test_returns_none_when_not_found(self):
        with patch("core.db._fetchone", return_value=None):
            assert get_job_by_unique_id("nonexistent") is None

    def test_returns_job_when_found(self):
        row = {
            "id": 7,
            "unique_id": "https://example.com/jobs/123",
            "title": "Senior Python Developer",
            "company": "Acme Corp",
            "location": "Cairo, Egypt",
            "url": "https://example.com/jobs/123",
            "source": "remotive",
            "salary_raw": "",
            "salary_min": None,
            "salary_max": None,
            "salary_currency": "",
            "job_type": "",
            "seniority": "mid",
            "is_remote": False,
            "country": "",
            "tags": [],
            "topics": [],
            "original_source": "",
            "telegram_message_ids": {},
        }
        with patch("core.db._fetchone", return_value=row):
            job = get_job_by_unique_id("https://example.com/jobs/123")
            assert isinstance(job, Job)
            assert job.title == "Senior Python Developer"


# ---------------------------------------------------------------------------
# TestGetUnsentJobs
# ---------------------------------------------------------------------------

class TestGetUnsentJobs:
    def test_returns_list_of_jobs(self):
        rows = [
            {
                "id": 1,
                "unique_id": "https://example.com/jobs/1",
                "title": "Dev A",
                "company": "Co",
                "location": "Remote",
                "url": "https://example.com/jobs/1",
                "source": "remotive",
                "salary_raw": "",
                "salary_min": None,
                "salary_max": None,
                "salary_currency": "",
                "job_type": "",
                "seniority": "mid",
                "is_remote": True,
                "country": "",
                "tags": [],
                "topics": [],
                "original_source": "",
                "telegram_message_ids": {},
            }
        ]
        with patch("core.db._fetchall", return_value=rows):
            jobs = get_unsent_jobs(limit=10)
            assert len(jobs) == 1
            assert isinstance(jobs[0], Job)

    def test_sql_contains_sent_at_is_null(self):
        with patch("core.db._fetchall", return_value=[]) as mock_fa:
            get_unsent_jobs()
            sql_arg = mock_fa.call_args[0][0]
            assert "sent_at IS NULL" in sql_arg


# ---------------------------------------------------------------------------
# TestMarkJobSent
# ---------------------------------------------------------------------------

class TestMarkJobSent:
    def test_mark_job_sent_calls_execute(self):
        with patch("core.db._execute") as mock_exec:
            mark_job_sent(42, {"main": 99})
            assert mock_exec.called

    def test_mark_job_sent_sql_contains_update(self):
        with patch("core.db._execute") as mock_exec:
            mark_job_sent(1, {})
            sql_arg = mock_exec.call_args[0][0]
            assert "UPDATE jobs" in sql_arg
            assert "sent_at" in sql_arg


# ---------------------------------------------------------------------------
# TestBotRuns
# ---------------------------------------------------------------------------

class TestBotRuns:
    def test_start_run_returns_id(self):
        """start_run returns the integer id from _fetchone."""
        with patch("core.db._fetchone", return_value={"id": 42}):
            run_id = start_run()
            assert run_id == 42

    def test_finish_run_updates(self):
        """finish_run calls _execute with SQL that contains UPDATE bot_runs."""
        with patch("core.db._execute") as mock_exec:
            finish_run(
                run_id=42,
                jobs_fetched=10,
                jobs_filtered=5,
                jobs_new=3,
                jobs_sent=3,
            )
            assert mock_exec.called
            sql_arg = mock_exec.call_args[0][0]
            assert "UPDATE bot_runs" in sql_arg

    def test_finish_run_with_source_stats_and_errors(self):
        """finish_run serialises source_stats and errors as JSON."""
        with patch("core.db._execute") as mock_exec:
            finish_run(
                run_id=1,
                source_stats={"remotive": 5},
                errors=["something went wrong"],
            )
            params = mock_exec.call_args[0][1]
            # source_stats and errors should be JSON strings in the params
            assert any(isinstance(p, str) and "remotive" in p for p in params)
            assert any(isinstance(p, str) and "something went wrong" in p for p in params)
