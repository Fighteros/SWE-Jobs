"""Unit tests for core.egytech HTTP client."""

import time
from unittest.mock import patch, MagicMock
import pytest

from core.egytech import get_stats, _cache, market_salary_for_job
from core.models import Job


@pytest.fixture(autouse=True)
def _clear_cache():
    _cache.clear()
    yield
    _cache.clear()


def _mock_response(status_code: int, json_data: dict | None = None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


class TestGetStats:
    def test_returns_stats_on_200(self):
        payload = {
            "stats": {
                "totalCount": 152, "median": 33800,
                "p20Compensation": 21200, "p75Compensation": 44000, "p90Compensation": 63000,
            },
            "buckets": [{"bucket": "20-25K", "count": 19}],
        }
        with patch("core.egytech.requests.get", return_value=_mock_response(200, payload)) as mock_get:
            result = get_stats(title="backend", level="mid_level")
        assert result is not None
        assert result["stats"]["median"] == 33800
        assert result["buckets"][0]["count"] == 19
        # Pinned exclusions must be in the URL
        called_url = mock_get.call_args[0][0]
        assert "include_relocated=false" in called_url
        assert "include_remote_abroad=false" in called_url
        assert "title=backend" in called_url
        assert "level=mid_level" in called_url

    def test_returns_none_on_404(self):
        with patch("core.egytech.requests.get", return_value=_mock_response(404)):
            assert get_stats(title="backend", level="senior_principal") is None

    def test_returns_none_on_network_error(self):
        import requests as r
        with patch("core.egytech.requests.get", side_effect=r.RequestException("boom")):
            assert get_stats(title="backend") is None

    def test_caches_successful_response(self):
        payload = {"stats": {"median": 1}, "buckets": []}
        with patch("core.egytech.requests.get", return_value=_mock_response(200, payload)) as mock_get:
            get_stats(title="backend", level="mid_level")
            get_stats(title="backend", level="mid_level")
        assert mock_get.call_count == 1

    def test_caches_404_response(self):
        with patch("core.egytech.requests.get", return_value=_mock_response(404)) as mock_get:
            get_stats(title="backend", level="senior_principal")
            get_stats(title="backend", level="senior_principal")
        assert mock_get.call_count == 1

    def test_does_not_cache_network_errors(self):
        import requests as r
        with patch("core.egytech.requests.get", side_effect=r.RequestException("boom")) as mock_get:
            get_stats(title="backend")
            get_stats(title="backend")
        assert mock_get.call_count == 2

    def test_cache_expires_after_ttl(self):
        payload = {"stats": {"median": 1}, "buckets": []}
        with patch("core.egytech.requests.get", return_value=_mock_response(200, payload)) as mock_get:
            get_stats(title="backend", level="mid_level")
            # Manually expire the cache entry
            key = next(iter(_cache))
            ts, data = _cache[key]
            _cache[key] = (ts - 25 * 3600, data)
            get_stats(title="backend", level="mid_level")
        assert mock_get.call_count == 2

    def test_omits_optional_params_when_none(self):
        payload = {"stats": {}, "buckets": []}
        with patch("core.egytech.requests.get", return_value=_mock_response(200, payload)) as mock_get:
            get_stats(title="backend")
        url = mock_get.call_args[0][0]
        assert "level=" not in url
        assert "yoe_from_included=" not in url
        assert "yoe_to_excluded=" not in url


class TestMarketSalaryForJob:
    def _job(self, **kwargs) -> Job:
        defaults = {
            "title": "Backend Engineer", "company": "X", "location": "Cairo",
            "url": "http://x", "source": "test",
            "country": "EG", "seniority": "mid", "topics": ["backend"],
        }
        defaults.update(kwargs)
        return Job(**defaults)

    def test_returns_none_for_non_egypt(self):
        job = self._job(country="US")
        assert market_salary_for_job(job) is None

    def test_returns_none_when_seniority_unmappable(self):
        job = self._job(seniority="unknown_level")
        assert market_salary_for_job(job) is None

    def test_returns_none_when_topic_unmappable(self):
        job = self._job(topics=["gamedev"])
        assert market_salary_for_job(job) is None

    def test_returns_formatted_range_when_data_present(self):
        payload = {
            "stats": {"totalCount": 152, "median": 33800,
                      "p20Compensation": 21200, "p75Compensation": 44000, "p90Compensation": 63000},
            "buckets": [],
        }
        with patch("core.egytech.requests.get", return_value=_mock_response(200, payload)):
            job = self._job()
            result = market_salary_for_job(job)
        assert result == "EGP 21k–44k/mo"

    def test_returns_none_when_egytech_returns_none(self):
        with patch("core.egytech.requests.get", return_value=_mock_response(404)):
            job = self._job()
            assert market_salary_for_job(job) is None
