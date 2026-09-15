"""Tests for weighted keyword scoring and geo filtering."""

from core.filtering import score_job, is_programming_job, passes_geo_filter
from core.models import Job


def _make_job(**kwargs) -> Job:
    defaults = {"title": "", "company": "", "location": "", "url": "http://x.com", "source": "test"}
    defaults.update(kwargs)
    return Job(**defaults)


class TestScoreJob:
    def test_exact_word_match_scores_10(self):
        job = _make_job(title="Senior Python Developer")
        score = score_job(job)
        assert score >= 10  # "developer" exact word match

    def test_tag_match_scores_8(self):
        job = _make_job(title="Something", tags=["python developer"])
        score = score_job(job)
        assert score >= 8

    def test_partial_match_scores_3(self):
        job = _make_job(title="Software Engineering Team")
        score = score_job(job)
        assert score >= 3

    def test_exclude_rejects(self):
        job = _make_job(title="Civil Engineer")
        assert is_programming_job(job) is False

    def test_marketing_passes(self):
        job = _make_job(title="Marketing Manager")
        assert is_programming_job(job) is True

    def test_real_job_passes(self):
        job = _make_job(title="Senior Python Developer", tags=["python", "django"])
        assert is_programming_job(job) is True

    def test_react_developer_passes(self):
        job = _make_job(title="React Developer", tags=["react", "javascript"])
        assert is_programming_job(job) is True

    def test_no_keywords_fails(self):
        job = _make_job(title="Registered Nurse")
        assert is_programming_job(job) is False

    def test_non_tech_roles_pass(self):
        examples = [
            "HR Manager",
            "Accountant",
            "Office Manager",
            "Customer Support Specialist",
            "Product Manager",
            "Sales Representative",
        ]
        for title in examples:
            job = _make_job(title=title)
            assert is_programming_job(job) is True, f"{title} should pass"

    def test_medical_and_hardware_still_rejected(self):
        for title in ("Registered Nurse", "Mechanical Engineer", "Physician"):
            job = _make_job(title=title)
            assert is_programming_job(job) is False

    def test_threshold_boundary(self):
        """A single exact word match should pass (score=10, threshold=10)."""
        job = _make_job(title="Software Developer")
        assert is_programming_job(job) is True


class TestGeoFilter:
    def test_egypt_passes(self):
        job = _make_job(title="Dev", location="Cairo, Egypt")
        assert passes_geo_filter(job) is True

    def test_saudi_passes(self):
        job = _make_job(title="Dev", location="Riyadh, Saudi Arabia")
        assert passes_geo_filter(job) is True

    def test_remote_passes(self):
        job = _make_job(title="Dev", location="Remote", is_remote=True)
        assert passes_geo_filter(job) is True

    def test_remote_only_source_passes(self):
        job = _make_job(title="Dev", location="", source="remotive")
        assert passes_geo_filter(job) is True

    def test_onsite_us_fails(self):
        job = _make_job(title="Dev", location="New York, USA", source="jsearch")
        assert passes_geo_filter(job) is False

    def test_remote_keyword_in_location(self):
        job = _make_job(title="Dev", location="Remote - Worldwide")
        assert passes_geo_filter(job) is True
