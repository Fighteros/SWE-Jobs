"""Tests for /api/stats/salary egytech-backed endpoint."""

from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from core.egytech import _cache


app = create_app()


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_cache():
    _cache.clear()
    yield
    _cache.clear()


def test_returns_egytech_payload_for_known_role(client):
    payload = {
        "stats": {
            "totalCount": 152, "median": 33800,
            "p20Compensation": 21200, "p75Compensation": 44000, "p90Compensation": 63000,
        },
        "buckets": [{"bucket": "20-25K", "count": 19}],
    }
    with patch("core.egytech.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = payload
        resp = client.get("/api/stats/salary?role=backend&seniority=mid")
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is True
    assert body["currency"] == "EGP"
    assert body["period"] == "monthly"
    assert body["stats"]["sample_size"] == 152
    assert body["stats"]["median"] == 33800
    assert body["stats"]["p20"] == 21200
    assert body["stats"]["p75"] == 44000
    assert body["stats"]["p90"] == 63000
    assert body["buckets"] == [{"label": "20-25K", "count": 19}]
    assert body["filters"] == {"role": "backend", "seniority": "mid", "yoe_from": None, "yoe_to": None}


def test_unmapped_role_returns_matched_false(client):
    resp = client.get("/api/stats/salary?role=xyzzy")
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is False
    assert body["stats"] is None
    assert body["buckets"] == []


def test_egytech_404_returns_matched_false(client):
    with patch("core.egytech.requests.get") as mock_get:
        mock_get.return_value.status_code = 404
        resp = client.get("/api/stats/salary?role=backend&seniority=intern")
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is False
    assert body["stats"] is None
    assert body["buckets"] == []


def test_yoe_filter_passed_through(client):
    payload = {"stats": {"totalCount": 5, "median": 100,
                         "p20Compensation": 80, "p75Compensation": 120, "p90Compensation": 140},
               "buckets": []}
    with patch("core.egytech.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = payload
        client.get("/api/stats/salary?role=backend&yoe_from=2&yoe_to=5")
    url = mock_get.call_args[0][0]
    assert "yoe_from_included=2" in url
    assert "yoe_to_excluded=5" in url
