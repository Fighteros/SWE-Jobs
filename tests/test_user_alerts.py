"""
Tests for user_alerts CRUD in core/db.py — mock-based, no real DB.
"""
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# create_user_alert
# ---------------------------------------------------------------------------

class TestCreateUserAlert:
    def test_returns_inserted_id_using_atomic_insert(self):
        """Single atomic INSERT...SELECT computes position; returns new id."""
        from core.db import create_user_alert

        with patch("core.db._fetchone", return_value={"id": 42}) as mock_fone:
            alert_id = create_user_alert(
                user_id=7,
                alert={
                    "topics": ["backend"],
                    "seniority": ["senior"],
                    "locations": ["remote"],
                    "sources": [],
                    "keywords": [],
                    "min_salary": None,
                },
            )

            assert alert_id == 42
            assert mock_fone.call_count == 1
            sql = mock_fone.call_args[0][0]
            params = mock_fone.call_args[0][1]
            assert "INSERT INTO user_alerts" in sql
            assert "COALESCE" in sql  # atomic position computation
            assert "MAX(position)" in sql
            # params: (user_id, user_id_for_subquery, topics, seniority, locations, sources, keywords, min_salary)
            assert params[0] == 7
            assert params[1] == 7

    def test_passes_alert_fields_in_correct_order(self):
        """All alert fields are forwarded to the INSERT in the right positions."""
        from core.db import create_user_alert

        with patch("core.db._fetchone", return_value={"id": 1}) as mock_fone:
            create_user_alert(
                user_id=5,
                alert={
                    "topics": ["devops"],
                    "seniority": ["mid"],
                    "locations": ["EG"],
                    "sources": ["linkedin"],
                    "keywords": ["python"],
                    "min_salary": 100000,
                },
            )
            params = mock_fone.call_args[0][1]
            # (user_id, user_id_for_subquery, topics, seniority, locations, sources, keywords, min_salary)
            assert params[2] == ["devops"]
            assert params[3] == ["mid"]
            assert params[4] == ["EG"]
            assert params[5] == ["linkedin"]
            assert params[6] == ["python"]
            assert params[7] == 100000


# ---------------------------------------------------------------------------
# get_user_alerts / get_user_alert
# ---------------------------------------------------------------------------

class TestGetUserAlerts:
    def test_returns_list_ordered_by_position(self):
        from core.db import get_user_alerts
        rows = [
            {"id": 1, "user_id": 7, "position": 1, "topics": ["backend"]},
            {"id": 2, "user_id": 7, "position": 2, "topics": ["devops"]},
        ]
        with patch("core.db._fetchall", return_value=rows) as mock_all:
            result = get_user_alerts(user_id=7)
            assert result == rows
            sql = mock_all.call_args[0][0]
            assert "ORDER BY position" in sql

    def test_empty_when_user_has_no_alerts(self):
        from core.db import get_user_alerts
        with patch("core.db._fetchall", return_value=[]):
            assert get_user_alerts(user_id=99) == []


class TestGetUserAlert:
    def test_returns_single_alert(self):
        from core.db import get_user_alert
        with patch("core.db._fetchone", return_value={"id": 1, "position": 1}):
            assert get_user_alert(user_id=7, position=1) == {"id": 1, "position": 1}

    def test_returns_none_when_missing(self):
        from core.db import get_user_alert
        with patch("core.db._fetchone", return_value=None):
            assert get_user_alert(user_id=7, position=99) is None
