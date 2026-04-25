"""
Integration test that hits the real egytech.fyi API.
Skipped by default; run with: pytest -m integration tests/test_egytech_integration.py
"""

import pytest

from core.egytech import _cache, get_stats


@pytest.mark.integration
def test_live_backend_mid_level_returns_data():
    _cache.clear()
    data = get_stats(title="backend", level="mid_level")
    assert data is not None
    stats = data["stats"]
    assert stats["totalCount"] > 0
    assert stats["median"] > 0
    assert stats["p20Compensation"] < stats["median"] < stats["p75Compensation"]
