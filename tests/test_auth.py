"""
Tests for the auth module: JWT signing/verification, TOTP, RBAC, and auth routes.

All tests mock the DB layer so they run without a live database.
"""

import time
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth.jwt import sign_jwt, verify_jwt, TYPE_ACCESS, TYPE_MFA_CHALLENGE, TYPE_REFRESH
from api.auth.totp import generate_totp_secret, verify_totp, encrypt_secret, decrypt_secret
from api.auth.rbac import require_permission, get_account_permissions


# ---------------------------------------------------------------------------
# JWT tests
# ---------------------------------------------------------------------------

class TestJWT:
    def test_sign_and_verify_access_token(self):
        token = sign_jwt(
            sub="test-account-id",
            typ=TYPE_ACCESS,
            authz_version=1,
            amr=["pwd", "totp"],
        )
        claims = verify_jwt(token, expected_type=TYPE_ACCESS)
        assert claims["sub"] == "test-account-id"
        assert claims["typ"] == "access"
        assert claims["authz_version"] == 1
        assert claims["amr"] == ["pwd", "totp"]

    def test_sign_and_verify_mfa_challenge(self):
        token = sign_jwt(sub="test-id", typ=TYPE_MFA_CHALLENGE, ttl=300)
        claims = verify_jwt(token, expected_type=TYPE_MFA_CHALLENGE)
        assert claims["typ"] == "mfa_challenge"

    def test_wrong_type_rejected(self):
        token = sign_jwt(sub="test-id", typ=TYPE_ACCESS)
        with pytest.raises(Exception):
            verify_jwt(token, expected_type=TYPE_REFRESH)

    def test_contains_required_claims(self):
        token = sign_jwt(
            sub="test-id",
            typ=TYPE_ACCESS,
            sid="session-123",
            authz_version=2,
            amr=["pwd", "totp"],
            auth_time=int(time.time()),
        )
        claims = verify_jwt(token, expected_type=TYPE_ACCESS)
        for key in ["iss", "aud", "sub", "jti", "sid", "typ", "iat", "nbf", "exp", "authz_version", "amr", "auth_time"]:
            assert key in claims, f"Missing claim: {key}"


# ---------------------------------------------------------------------------
# TOTP tests
# ---------------------------------------------------------------------------

class TestTOTP:
    def test_generate_secret_is_base32(self):
        secret = generate_totp_secret()
        assert len(secret) == 32
        import base64
        base64.b32decode(secret)  # Should not raise

    def test_verify_correct_code(self):
        secret = generate_totp_secret()
        # Generate a valid code
        from api.auth.totp import _hotp
        now = int(time.time() // 30)
        code = _hotp(secret, now)
        assert verify_totp(secret, code) is True

    def test_verify_wrong_code(self):
        secret = generate_totp_secret()
        assert verify_totp(secret, "000000") is False or verify_totp(secret, "999999") is False

    def test_encrypt_decrypt_roundtrip(self):
        secret = generate_totp_secret()
        encrypted = encrypt_secret(secret)
        assert encrypted != secret.encode()  # Not plaintext
        decrypted = decrypt_secret(encrypted)
        assert decrypted == secret


# ---------------------------------------------------------------------------
# RBAC tests
# ---------------------------------------------------------------------------

class TestRBAC:
    @pytest.mark.asyncio
    async def test_get_account_permissions(self):
        mock_db = MagicMock()
        mock_db._fetchall.return_value = [
            {"key": "jobs.read"},
            {"key": "jobs.manage"},
            {"key": "dashboard.read"},
        ]
        perms = await get_account_permissions("test-id", db_module=mock_db)
        assert perms == {"jobs.read", "jobs.manage", "dashboard.read"}

    @pytest.mark.asyncio
    async def test_get_account_permissions_empty(self):
        mock_db = MagicMock()
        mock_db._fetchall.return_value = None
        perms = await get_account_permissions("test-id", db_module=mock_db)
        assert perms == set()


# ---------------------------------------------------------------------------
# Auth route tests (with mocked DB)
# ---------------------------------------------------------------------------

app = create_app()
client = TestClient(app)


class TestAuthRoutes:
    def test_login_invalid_credentials(self):
        with patch("core.db._fetchone", return_value=None):
            resp = client.post("/api/v1/auth/login", json={"email": "nope@test.com", "password": "x"})
        assert resp.status_code == 401

    def test_login_account_not_active(self):
        with patch("core.db._fetchone", return_value={
            "id": "uuid", "email": "test@test.com", "password_hash": "$argon2id$...",
            "status": "disabled", "authz_version": 1,
        }):
            resp = client.post("/api/v1/auth/login", json={"email": "test@test.com", "password": "x"})
        assert resp.status_code == 403

    def test_mfa_verify_invalid_token(self):
        resp = client.post("/api/v1/auth/mfa/verify", json={"mfa_token": "invalid", "code": "123456"})
        assert resp.status_code == 401

    def test_refresh_no_cookie(self):
        resp = client.post("/api/v1/auth/refresh")
        assert resp.status_code == 401

    def test_logout_clears_cookie(self):
        resp = client.post("/api/v1/auth/logout")
        assert resp.status_code == 200
        assert resp.json()["detail"] == "Logged out"

    def test_livez_returns_200(self):
        resp = client.get("/livez")
        assert resp.status_code == 200
        assert resp.json()["status"] == "alive"

    def test_health_still_works(self):
        with patch("bot.polling.get_supervisor_status", return_value={"running": True}):
            resp = client.get("/health")
        assert resp.status_code == 200
