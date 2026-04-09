import pytest
from core.models import Job

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
        tags=["python", "django", "backend"],
        is_remote=True,
    )

@pytest.fixture
def minimal_job():
    return Job(title="Developer", company="", location="", url="https://example.com/jobs/456", source="linkedin")
