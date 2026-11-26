"""Parser tests for the sources added with the Scrapling migration."""

from datetime import datetime, timezone
from unittest.mock import patch

from sources import hackernews, jobscollider, jobspresso, landingjobs, nodesk


def test_hackernews_parses_header_line():
    now = datetime(2026, 11, 20, tzinfo=timezone.utc)
    good = {"id": 1, "created_at": "2026-11-02T10:00:00Z",
            "text": "Acme | Backend Engineer | REMOTE (EU) | Full-time<p>More details"}
    junk = {"id": 2, "created_at": "2026-11-02T10:00:00Z", "text": "Just a reply, no header"}
    job = hackernews._parse_comment(good, now)
    assert job.company == "Acme" and job.title == "Backend Engineer"
    assert job.is_remote and job.url.endswith("id=1") and job.job_type == "Full-time"
    assert hackernews._parse_comment(junk, now) is None


def test_hackernews_skips_old_threads():
    now = datetime(2027, 1, 30, tzinfo=timezone.utc)
    old = {"id": 1, "created_at": "2026-11-02T10:00:00Z", "text": "A | B | Remote"}
    assert hackernews._parse_comment(old, now) is None


def test_jobscollider_maps_fields():
    payload = {"jobs": [{
        "id": "x", "url": "https://remotefirstjobs.com/j/x", "company_name": "Nanit",
        "title": "Backend Developer", "category": "software_development",
        "seniority": "middle", "salary_min": "0", "salary_max": "0",
        "locations": "['Israel']", "published_at": "2026-11-25T10:03:08",
    }]}
    with patch.object(jobscollider, "get_json", side_effect=[payload, None] * 4):
        jobs = jobscollider.fetch_jobscollider()
    assert len(jobs) == 1
    assert jobs[0].location == "Remote - Israel" and jobs[0].is_remote
    assert jobs[0].source == "jobscollider"


def test_landingjobs_maps_fields():
    item = {"title": "Dev", "url": "https://landing.jobs/at/some-co/dev-1", "type": "Full-time",
            "remote": False, "tags": "['Java']", "locations": "[{'city': 'Lisbon', 'country_code': 'PT'}]",
            "gross_salary_low": 1, "gross_salary_high": 2, "currency_code": "EUR",
            "published_at": "2026-03-17T10:23:40.667Z"}
    with patch.object(landingjobs, "get_json", return_value=[item]):
        jobs = landingjobs.fetch_landingjobs()
    assert jobs[0].company == "Some Co" and jobs[0].location == "Lisbon, PT"
    assert jobs[0].tags == ["Java"]


RSS = """<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item>
<title>{title}</title><link>https://example.com/j/1</link>
<dc:creator><![CDATA[Wikimedia<br>⚲&nbsp;Worldwide]]></dc:creator>
<pubDate>Thu, 26 Nov 2026 05:13:54 +0000</pubDate></item></channel></rss>"""


def test_jobspresso_rss():
    with patch.object(jobspresso, "get_text", return_value=RSS.format(title="Engineer")):
        jobs = jobspresso.fetch_jobspresso()
    assert jobs[0].company == "Wikimedia" and jobs[0].location == "Worldwide"


def test_nodesk_splits_company():
    with patch.object(nodesk, "get_text", return_value=RSS.format(title="Lead Dev at Acme at Home")):
        jobs = nodesk.fetch_nodesk()
    assert jobs[0].title == "Lead Dev at Acme" and jobs[0].company == "Home"
