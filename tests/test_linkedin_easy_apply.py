"""
Tests for LinkedIn Easy Apply detection and how it renders in the
Telegram message body. Easy Apply is surfaced for both group topics
and DM notifications (both paths share `format_job_message`).
"""
from core.models import Job
from sources.linkedin import _parse_search_html
from bot.sender import format_job_message


def _card(body: str) -> str:
    """Wrap a card body with the minimal attributes the parser needs."""
    return (
        '<li>'
        '<h3 class="base-search-card__title">Backend Engineer</h3>'
        '<h4 class="base-search-card__subtitle">Acme</h4>'
        '<span class="job-search-card__location">Cairo, Egypt</span>'
        '<a href="https://www.linkedin.com/jobs/view/123/">link</a>'
        f'{body}'
        '</li>'
    )


class TestLinkedinParserEasyApply:
    def test_easy_apply_label_detected(self):
        html = _card('<span class="job-search-card__easy-apply-label">Easy Apply</span>')
        jobs = _parse_search_html(html, {})
        assert len(jobs) == 1
        assert jobs[0].is_easy_apply is True

    def test_easy_apply_text_detected(self):
        html = _card('<span>Easy Apply</span>')
        jobs = _parse_search_html(html, {})
        assert len(jobs) == 1
        assert jobs[0].is_easy_apply is True

    def test_no_easy_apply_defaults_false(self):
        html = _card('<span>Some other label</span>')
        jobs = _parse_search_html(html, {})
        assert len(jobs) == 1
        assert jobs[0].is_easy_apply is False


class TestMessageRendersEasyApply:
    def _base_job(self, is_easy_apply: bool) -> Job:
        return Job(
            title="Backend Engineer",
            company="Acme",
            location="Cairo, Egypt",
            url="https://www.linkedin.com/jobs/view/123",
            source="linkedin",
            is_easy_apply=is_easy_apply,
        )

    def test_easy_apply_line_shown_when_true(self):
        msg = format_job_message(self._base_job(True))
        assert "⚡ Easy Apply on LinkedIn" in msg

    def test_apply_link_label_upgraded_when_easy_apply(self):
        msg = format_job_message(self._base_job(True))
        assert ">⚡ Easy Apply on LinkedIn</a>" in msg
        assert ">Apply Now</a>" not in msg

    def test_standard_apply_when_not_easy_apply(self):
        msg = format_job_message(self._base_job(False))
        assert "Easy Apply" not in msg
        assert ">Apply Now</a>" in msg
