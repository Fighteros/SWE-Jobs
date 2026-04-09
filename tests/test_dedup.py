"""Tests for fuzzy deduplication."""

from core.dedup import deduplicate_batch, is_duplicate_url, normalize_url
from core.models import Job


def _make_job(**kwargs) -> Job:
    defaults = {"title": "", "company": "", "location": "", "url": "http://x.com", "source": "test"}
    defaults.update(kwargs)
    return Job(**defaults)


class TestNormalizeUrl:
    def test_strips_utm(self):
        assert normalize_url("http://x.com/job?utm_source=email") == "http://x.com/job"

    def test_strips_trailing_slash(self):
        assert normalize_url("http://x.com/job/") == "http://x.com/job"

    def test_lowercases(self):
        assert normalize_url("HTTP://X.COM/Job") == "http://x.com/job"


class TestIsDuplicateUrl:
    def test_exact_match(self):
        seen = {"http://x.com/job/1", "http://x.com/job/2"}
        assert is_duplicate_url("http://x.com/job/1", seen) is True

    def test_no_match(self):
        seen = {"http://x.com/job/1"}
        assert is_duplicate_url("http://x.com/job/99", seen) is False

    def test_normalized_match(self):
        seen = {"http://x.com/job/1"}
        assert is_duplicate_url("http://x.com/job/1?utm_source=email", seen) is True


class TestDeduplicateBatch:
    def test_removes_within_batch_dupes(self):
        jobs = [
            _make_job(title="Dev", url="http://x.com/1"),
            _make_job(title="Dev", url="http://x.com/1"),
        ]
        result = deduplicate_batch(jobs, seen_ids=set())
        assert len(result) == 1

    def test_removes_seen_jobs(self):
        jobs = [
            _make_job(title="Dev", url="http://x.com/1"),
            _make_job(title="Dev 2", url="http://x.com/2"),
        ]
        result = deduplicate_batch(jobs, seen_ids={"http://x.com/1"})
        assert len(result) == 1
        assert result[0].url == "http://x.com/2"

    def test_empty_batch(self):
        assert deduplicate_batch([], set()) == []
