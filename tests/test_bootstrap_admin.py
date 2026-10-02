"""
Unit tests for the super-admin bootstrap command.

Tests mock the DB layer so they run without a live database.
"""

from unittest.mock import patch, MagicMock
import pytest

from scripts.bootstrap_admin import bootstrap_admin, _generate_password, _hash_password


class TestGeneratePassword:
    def test_generates_reasonable_length(self):
        pw = _generate_password()
        assert len(pw) == 24

    def test_generates_different_each_time(self):
        pw1 = _generate_password()
        pw2 = _generate_password()
        assert pw1 != pw2


class TestHashPassword:
    def test_hash_is_not_plaintext(self):
        pw = "testpassword123"
        h = _hash_password(pw)
        assert h != pw
        assert h.startswith("$argon2id$")


class TestBootstrapAdmin:
    def test_creates_new_admin_when_none_exists(self):
        mock_db = MagicMock()
        mock_db._fetchone.return_value = None
        mock_db._execute.return_value = None

        result = bootstrap_admin("admin@example.com", "Super Admin", db_module=mock_db)

        assert result["created"] is True
        assert result["email"] == "admin@example.com"
        assert result["password"] is not None
        assert result["account_id"] is not None
        assert mock_db._execute.call_count == 3

    def test_is_idempotent_when_admin_exists(self):
        mock_db = MagicMock()
        mock_db._fetchone.return_value = {
            "id": "existing-uuid",
            "email": "existing@example.com",
            "status": "active",
        }

        result = bootstrap_admin("new@example.com", "New Admin", db_module=mock_db)

        assert result["created"] is False
        assert result["email"] == "existing@example.com"
        assert result["password"] is None
        assert mock_db._execute.call_count == 0

    def test_normalizes_email_to_lowercase(self):
        mock_db = MagicMock()
        mock_db._fetchone.return_value = None

        result = bootstrap_admin("ADMIN@EXAMPLE.COM", "Admin", db_module=mock_db)

        assert result["email"] == "admin@example.com"
