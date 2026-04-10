"""Tests for subscription matching with location and source filters."""

from core.models import Job
from bot.notifications import _job_matches_subscription


def _make_job(**kwargs) -> Job:
    defaults = {
        "title": "Software Engineer",
        "company": "Acme",
        "location": "Cairo, Egypt",
        "url": "http://x.com",
        "source": "test",
        "topics": ["backend"],
        "country": "EG",
    }
    defaults.update(kwargs)
    return Job(**defaults)


class TestJobMatchesSubscription:
    def test_empty_subs_returns_false(self):
        assert not _job_matches_subscription(_make_job(), {})

    def test_topic_match(self):
        subs = {"topics": ["backend"]}
        assert _job_matches_subscription(_make_job(), subs)

    def test_topic_mismatch(self):
        subs = {"topics": ["mobile"]}
        assert not _job_matches_subscription(_make_job(), subs)

    def test_location_egypt_match(self):
        subs = {"topics": ["backend"], "locations": ["EG"]}
        assert _job_matches_subscription(_make_job(country="EG"), subs)

    def test_location_mismatch(self):
        subs = {"topics": ["backend"], "locations": ["US"]}
        assert not _job_matches_subscription(_make_job(country="EG"), subs)

    def test_location_remote_match(self):
        subs = {"topics": ["backend"], "locations": ["remote"]}
        assert _job_matches_subscription(_make_job(is_remote=True), subs)

    def test_location_remote_mismatch(self):
        subs = {"topics": ["backend"], "locations": ["remote"]}
        assert not _job_matches_subscription(_make_job(is_remote=False, country="EG"), subs)

    def test_location_multiple_any_match(self):
        subs = {"topics": ["backend"], "locations": ["EG", "SA"]}
        assert _job_matches_subscription(_make_job(country="SA"), subs)

    def test_no_location_filter_matches_all(self):
        subs = {"topics": ["backend"]}
        assert _job_matches_subscription(_make_job(country="EG"), subs)
        assert _job_matches_subscription(_make_job(country="US"), subs)

    def test_remote_plus_country(self):
        subs = {"topics": ["backend"], "locations": ["remote", "EG"]}
        # Remote job from US should match (remote selected)
        assert _job_matches_subscription(_make_job(country="US", is_remote=True), subs)
        # Onsite Egypt job should match (EG selected)
        assert _job_matches_subscription(_make_job(country="EG", is_remote=False), subs)
        # Onsite US job should NOT match
        assert not _job_matches_subscription(_make_job(country="US", is_remote=False), subs)


class TestSourceFilter:
    def test_source_match(self):
        subs = {"topics": ["backend"], "sources": ["remotive"]}
        assert _job_matches_subscription(_make_job(source="remotive"), subs)

    def test_source_mismatch(self):
        subs = {"topics": ["backend"], "sources": ["remotive"]}
        assert not _job_matches_subscription(_make_job(source="himalayas"), subs)

    def test_no_source_filter_matches_all(self):
        subs = {"topics": ["backend"]}
        assert _job_matches_subscription(_make_job(source="remotive"), subs)
        assert _job_matches_subscription(_make_job(source="himalayas"), subs)

    def test_jsearch_linkedin_match(self):
        """JSearch jobs with original_source=LinkedIn should match 'linkedin' filter."""
        subs = {"topics": ["backend"], "sources": ["linkedin"]}
        assert _job_matches_subscription(
            _make_job(source="jsearch", original_source="LinkedIn"), subs
        )

    def test_jsearch_indeed_no_match_when_linkedin_only(self):
        subs = {"topics": ["backend"], "sources": ["linkedin"]}
        assert not _job_matches_subscription(
            _make_job(source="jsearch", original_source="Indeed"), subs
        )

    def test_multiple_sources(self):
        subs = {"topics": ["backend"], "sources": ["remotive", "linkedin"]}
        assert _job_matches_subscription(_make_job(source="remotive"), subs)
        assert _job_matches_subscription(
            _make_job(source="jsearch", original_source="LinkedIn"), subs
        )
        assert not _job_matches_subscription(_make_job(source="himalayas"), subs)
