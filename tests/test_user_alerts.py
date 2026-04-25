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


# ---------------------------------------------------------------------------
# update_user_alert
# ---------------------------------------------------------------------------

class TestUpdateUserAlert:
    def test_updates_filter_fields(self):
        from core.db import update_user_alert
        with patch("core.db._execute", return_value={"id": 1}) as mock_exec:
            ok = update_user_alert(
                user_id=7,
                position=2,
                alert={
                    "topics": ["frontend"],
                    "seniority": ["mid"],
                    "locations": ["remote"],
                    "sources": ["linkedin"],
                    "keywords": ["react"],
                    "min_salary": 80000,
                },
            )
            assert ok is True
            sql = mock_exec.call_args[0][0]
            params = mock_exec.call_args[0][1]
            assert "UPDATE user_alerts" in sql
            assert "RETURNING id" in sql
            # Last two params are the WHERE clause: user_id, position
            assert params[-2] == 7
            assert params[-1] == 2

    def test_returns_false_when_no_row_matched(self):
        from core.db import update_user_alert
        with patch("core.db._execute", return_value=None):
            assert update_user_alert(user_id=7, position=99, alert={"topics": []}) is False


# ---------------------------------------------------------------------------
# set_alert_dm_enabled
# ---------------------------------------------------------------------------

class TestSetAlertDmEnabled:
    def test_returns_true_when_alert_exists(self):
        from core.db import set_alert_dm_enabled
        with patch("core.db._execute", return_value={"id": 5}) as mock_exec:
            ok = set_alert_dm_enabled(user_id=7, position=1, enabled=False)
            assert ok is True
            sql = mock_exec.call_args[0][0]
            params = mock_exec.call_args[0][1]
            assert "UPDATE user_alerts" in sql
            assert "dm_enabled" in sql
            assert params == (False, 7, 1)

    def test_returns_false_when_alert_missing(self):
        from core.db import set_alert_dm_enabled
        with patch("core.db._execute", return_value=None):
            assert set_alert_dm_enabled(user_id=7, position=99, enabled=True) is False


# ---------------------------------------------------------------------------
# delete_user_alert (with position re-pack)
# ---------------------------------------------------------------------------

class TestDeleteUserAlert:
    def test_deletes_and_repacks_higher_positions(self):
        """Deleting alert #2 of 3 must shift #3 → #2 in the same transaction."""
        from core.db import delete_user_alert

        # Mock the connection context-manager + cursor so we can observe the
        # ordered statements executed in one TX.
        executed = []

        class FakeCursor:
            def __init__(self):
                self.rowcount = 0
                self.description = None

            def execute(self, sql, params=()):
                executed.append((sql.strip().split()[0].upper(), params))
                # Pretend the DELETE matched one row
                if sql.strip().upper().startswith("DELETE"):
                    self.rowcount = 1

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class FakeConn:
            def cursor(self, cursor_factory=None):
                return FakeCursor()

            def commit(self): pass
            def rollback(self): pass

        from contextlib import contextmanager

        @contextmanager
        def fake_conn():
            yield FakeConn()

        with patch("core.db._get_conn", fake_conn):
            ok = delete_user_alert(user_id=7, position=2)

        assert ok is True
        # First op must be DELETE, second must be UPDATE (re-pack)
        assert executed[0][0] == "DELETE"
        assert executed[1][0] == "UPDATE"
        # The UPDATE must scope to the same user and positions > 2
        assert executed[1][1] == (7, 2)

    def test_returns_false_when_alert_missing(self):
        from core.db import delete_user_alert

        class FakeCursor:
            def __init__(self):
                self.rowcount = 0
                self.description = None
            def execute(self, sql, params=()):
                pass
            def __enter__(self): return self
            def __exit__(self, *args): return False

        class FakeConn:
            def cursor(self, cursor_factory=None):
                return FakeCursor()
            def commit(self): pass
            def rollback(self): pass

        from contextlib import contextmanager

        @contextmanager
        def fake_conn():
            yield FakeConn()

        with patch("core.db._get_conn", fake_conn):
            assert delete_user_alert(user_id=7, position=99) is False
