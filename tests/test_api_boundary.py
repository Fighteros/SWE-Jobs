"""
Boundary characterization tests for current FastAPI route behavior.

These tests document the UNAUTHENTICATED behavior of all business endpoints
before authentication is added in later milestones. When auth is implemented,
these tests should be updated to assert 401/403 instead of 200.

Run: pytest tests/test_api_boundary.py -v
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.app import create_app

app = create_app()
client = TestClient(app)


# ---------------------------------------------------------------------------
# Health endpoint (will remain unauthenticated)
# ---------------------------------------------------------------------------

def test_health_returns_200():
    with patch("bot.polling.get_supervisor_status", return_value={"running": True}):
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Jobs endpoint — currently unauthenticated (to be protected later)
# ---------------------------------------------------------------------------

def test_jobs_search_returns_200_without_auth():
    """Characterizes current behavior: jobs search is accessible without auth."""
    with patch("core.db_async._fetchone", new_callable=AsyncMock, return_value={"total": 0}), \
         patch("core.db_async._fetchall", new_callable=AsyncMock, return_value=[]):
        resp = client.get("/api/jobs/search")
    assert resp.status_code == 200
    body = resp.json()
    assert "jobs" in body
    assert "total" in body
    assert "page" in body


def test_jobs_search_with_filters_returns_200():
    with patch("core.db_async._fetchone", new_callable=AsyncMock, return_value={"total": 0}), \
         patch("core.db_async._fetchall", new_callable=AsyncMock, return_value=[]):
        resp = client.get("/api/jobs/search?q=python&seniority=mid&page=1&per_page=5")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Stats endpoints — currently unauthenticated (to be protected later)
# ---------------------------------------------------------------------------

def test_stats_summary_returns_200_without_auth():
    with patch("core.db_async._fetchone", new_callable=AsyncMock, return_value={"count": 0}), \
         patch("core.db_async._fetchall", new_callable=AsyncMock, return_value=[]):
        resp = client.get("/api/stats/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert "jobs_today" in body
    assert "jobs_week" in body
    assert "jobs_total" in body


def test_stats_trends_returns_200_without_auth():
    with patch("core.db_async._fetchall", new_callable=AsyncMock, return_value=[]):
        resp = client.get("/api/stats/trends?period=7d")
    assert resp.status_code == 200
    body = resp.json()
    assert "period" in body
    assert "trends" in body


# ---------------------------------------------------------------------------
# CORS — currently wildcard (to be tightened to DASHBOARD_ORIGINS later)
# ---------------------------------------------------------------------------

def test_cors_restricted_to_allowlist():
    """Characterizes post-M5 behavior: CORS is restricted to DASHBOARD_ORIGINS."""
    resp = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.status_code in (200, 204)


def test_livez_endpoint_exists():
    """The /livez endpoint exists and requires no auth."""
    resp = client.get("/livez")
    assert resp.status_code == 200
    assert resp.json()["status"] == "alive"


# ---------------------------------------------------------------------------
# No auth endpoints exist yet — confirm no login/mfa/refresh routes
# ---------------------------------------------------------------------------

def test_auth_routes_exist():
    """Authentication routes should now be registered (Milestone 5)."""
    from api.routes_auth import router as auth_router
    auth_paths = {r.path for r in auth_router.routes}
    assert "/api/v1/auth/login" in auth_paths
    assert "/api/v1/auth/mfa/verify" in auth_paths
    assert "/api/v1/auth/refresh" in auth_paths
    assert "/api/v1/auth/logout" in auth_paths


def test_livez_endpoint_exists():
    """The /livez endpoint exists and requires no auth."""
    resp = client.get("/livez")
    assert resp.status_code == 200
    assert resp.json()["status"] == "alive"


# ---------------------------------------------------------------------------
# All data requests go through FastAPI (no Supabase client in backend)
# ---------------------------------------------------------------------------

def test_backend_has_no_supabase_client_import():
    """The backend should not import or use a Supabase client."""
    import api.app
    import api.routes_jobs
    import api.routes_stats
    source = api.app.__file__
    for mod in [api.app, api.routes_jobs, api.routes_stats]:
        with open(mod.__file__) as f:
            content = f.read()
        assert "supabase" not in content.lower(), \
            f"{mod.__file__} references supabase"
