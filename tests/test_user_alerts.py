"""
Tests for user_alerts CRUD in core/db.py — mock-based, no real DB.
"""
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# create_user_alert
# ---------------------------------------------------------------------------

class TestCreateUserAlert:
    def test_inserts_at_next_position_when_user_has_no_alerts(self):
        """First alert for a user gets position=1."""
        from core.db import create_user_alert

        with patch("core.db._fetchone") as mock_fetchone:
            # First call: max(position) lookup → no rows
            # Second call: INSERT ... RETURNING id → {"id": 42}
            mock_fetchone.side_effect = [{"max_pos": None}, {"id": 42}]

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
            # Verify the INSERT used position=1
            insert_call = mock_fetchone.call_args_list[1]
            params = insert_call[0][1]
            # Params: (user_id, position, topics, seniority, locations, sources, keywords, min_salary)
            assert params[0] == 7
            assert params[1] == 1

    def test_inserts_at_next_position_when_user_has_existing_alerts(self):
        """Third alert for a user with two existing gets position=3."""
        from core.db import create_user_alert

        with patch("core.db._fetchone") as mock_fetchone:
            mock_fetchone.side_effect = [{"max_pos": 2}, {"id": 99}]

            alert_id = create_user_alert(
                user_id=5,
                alert={
                    "topics": ["devops"],
                    "seniority": [],
                    "locations": [],
                    "sources": [],
                    "keywords": [],
                    "min_salary": None,
                },
            )

            assert alert_id == 99
            insert_call = mock_fetchone.call_args_list[1]
            params = insert_call[0][1]
            assert params[1] == 3
