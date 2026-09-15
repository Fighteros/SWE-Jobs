import importlib
import os
from datetime import timezone

import core.config as config
from sources.wuzzuf import (
    _extract_state,
    _job_id,
    _parse_html,
    _parse_relative_date,
    _parse_state_timestamp,
)


HTML = """
<html><body>
<div class="e1v1l3u10">
  <h2><a href="/jobs/p/123456-senior-python-engineer">Senior Python Engineer</a></h2>
  <a class="css-ipsyv7">Acme Labs</a>
  <span class="css-16x61xq">Cairo, Egypt</span>
  <div class="css-eg55jf">2 days ago</div>
  <div class="css-5jhz9n"><a><span>Python</span></a><a><span>Backend</span></a></div>
</div>
<script>
window.Wuzzuf = {"initialStoreState":{"job":{"collection":{
  "123456":{"attributes":{"slug":"123456-senior-python-engineer",
    "postedAt":"09/13/2026 16:48:58",
    "description":"<p>Build reliable services.</p>",
    "salary":{"additionalDetails":"EGP 40K - 60K monthly"},
    "careerLevel":{"name":"Senior"},
    "workplaceArrangement":{"displayedName":"Hybrid"},
    "workTypes":[{"displayedName":"Full Time"}]}}
}}}};
</script>
</body></html>
"""


def test_extract_state_and_parse_rich_job():
    state = _extract_state(HTML)
    assert state["123456"]["attributes"]["careerLevel"]["name"] == "Senior"

    jobs = _parse_html(HTML)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Senior Python Engineer"
    assert job.company == "Acme Labs"
    assert job.location == "Cairo, Egypt"
    assert job.salary_raw == "EGP 40K - 60K monthly"
    assert job.job_type == "Full Time"
    assert job.seniority == "senior"
    assert job.tags == ["Python", "Backend", "Full Time"]
    assert job.posted_at.tzinfo == timezone.utc


def test_duplicate_links_are_removed():
    jobs = _parse_html(HTML.replace("</body>", HTML.split("<body>", 1)[1].split("<script>", 1)[0] + "</body>"))
    assert len(jobs) == 1


def test_timestamp_and_relative_date_parsing():
    timestamp = _parse_state_timestamp("09/15/2026 10:20:30")
    assert timestamp.isoformat() == "2026-09-15T07:20:30+00:00"
    assert _parse_state_timestamp("not a date") is None
    assert _parse_relative_date("2 days ago") is not None


def test_job_id_accepts_wuzzuf_slug_or_url():
    assert _job_id("/jobs/p/123456-senior-python-engineer") == "123456"
    assert _job_id("https://wuzzuf.net/jobs/p/123456-senior-python-engineer") == "123456"
    assert _job_id("/jobs/p/not-a-number") == ""


def test_blank_profile_env_uses_persistent_default(monkeypatch):
    monkeypatch.setenv("WUZZUF_PROFILE_DIR", "")
    importlib.reload(config)
    assert config.WUZZUF_PROFILE_DIR == ".wuzzuf-profile"
    monkeypatch.setenv("WUZZUF_PROFILE_DIR", os.getenv("WUZZUF_PROFILE_DIR", ""))
