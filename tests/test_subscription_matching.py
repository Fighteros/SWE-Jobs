from unittest.mock import MagicMock

from core.subscription_matching import job_matches_alert


def _job(**kwargs):
    job = MagicMock()
    job.topics = kwargs.get("topics", ["backend"])
    job.seniority = kwargs.get("seniority", "mid")
    job.source = kwargs.get("source", "linkedin")
    job.original_source = kwargs.get("original_source", "")
    job.is_remote = kwargs.get("is_remote", True)
    job.country = kwargs.get("country", "")
    job.title = kwargs.get("title", "Senior Python Developer")
    job.salary_min = kwargs.get("salary_min")
    job.salary_max = kwargs.get("salary_max")
    return job


def _alert(**kwargs):
    alert = {
        "topics": ["general"], "seniority": [], "locations": [],
        "sources": [], "keywords": [], "min_salary": None,
    }
    alert.update(kwargs)
    return alert


def test_min_salary_none_matches_anything():
    assert job_matches_alert(_job(salary_min=1000, salary_max=2000), _alert())


def test_min_salary_below_posted_range_matches():
    assert job_matches_alert(_job(salary_min=50000, salary_max=90000), _alert(min_salary=60000))


def test_min_salary_above_posted_range_rejects():
    assert not job_matches_alert(_job(salary_min=40000, salary_max=55000), _alert(min_salary=60000))


def test_min_salary_uses_min_when_max_absent():
    assert job_matches_alert(_job(salary_min=70000, salary_max=None), _alert(min_salary=60000))
    assert not job_matches_alert(_job(salary_min=50000, salary_max=None), _alert(min_salary=60000))


def test_min_salary_keeps_jobs_without_salary_info():
    assert job_matches_alert(_job(salary_min=None, salary_max=None), _alert(min_salary=60000))
