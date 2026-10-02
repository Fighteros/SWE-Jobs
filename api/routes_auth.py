"""
api/routes_auth.py — Admin authentication endpoints.

Endpoints:
  POST /api/v1/auth/login       — email + password -> MFA challenge JWT
  POST /api/v1/auth/mfa/verify  — MFA challenge JWT + TOTP code -> access + refresh
  POST /api/v1/auth/refresh     — refresh cookie -> new access + refresh (rotated)
  POST /api/v1/auth/logout      — revoke refresh session

All responses avoid putting JWTs in localStorage. Access tokens are in the JSON
body (in-memory only). Refresh tokens are in HttpOnly cookies.
"""

import logging
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr

from api.auth.jwt import (
    sign_jwt, verify_jwt,
    TYPE_ACCESS, TYPE_MFA_CHALLENGE, TYPE_REFRESH,
    ACCESS_TTL, MFA_CHALLENGE_TTL,
)
from api.auth.totp import verify_totp, decrypt_secret
from api.auth.refresh import hash_token, create_refresh_session, rotate_refresh_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class MfaVerifyRequest(BaseModel):
    mfa_token: str
    code: str


@router.post("/login")
async def login(req: LoginRequest):
    """
    Step 1: Verify email + password. If valid, return an MFA challenge JWT.
    The client must then call /mfa/verify with a TOTP code.
    """
    from core import db

    email = req.email.strip().lower()
    account = db._fetchone(
        """
        SELECT id, email, password_hash, status, authz_version
        FROM security.admin_accounts
        WHERE lower(email) = %s
        """,
        (email,),
    )

    if not account or not account["password_hash"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if account["status"] not in ("active", "pending_totp"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account is {account['status']}",
        )

    # Verify password
    try:
        from argon2 import PasswordHasher
        from argon2.exceptions import VerifyMismatchError
        ph = PasswordHasher()
        ph.verify(account["password_hash"], req.password)
    except VerifyMismatchError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication error",
        )

    # Issue MFA challenge JWT
    mfa_token = sign_jwt(
        sub=str(account["id"]),
        typ=TYPE_MFA_CHALLENGE,
        authz_version=account["authz_version"],
        ttl=MFA_CHALLENGE_TTL,
    )

    # Audit
    db._execute(
        """
        INSERT INTO security.admin_audit_events (account_id, event_type, detail)
        VALUES (%s, 'auth.login_attempt', '{}'::jsonb)
        """,
        (account["id"],),
    )

    return {"mfa_token": mfa_token, "expires_in": MFA_CHALLENGE_TTL}


@router.post("/mfa/verify")
async def mfa_verify(req: MfaVerifyRequest, response: Response):
    """
    Step 2: Verify TOTP code against the MFA challenge JWT.
    If valid, issue access + refresh tokens. Refresh is set as an HttpOnly cookie.
    """
    from core import db

    try:
        claims = verify_jwt(req.mfa_token, expected_type=TYPE_MFA_CHALLENGE)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid MFA challenge: {e}",
        )

    account_id = claims["sub"]

    account = db._fetchone(
        "SELECT id, status, authz_version FROM security.admin_accounts WHERE id = %s",
        (account_id,),
    )
    if not account:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account not found")

    if account["status"] not in ("active", "pending_totp"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account is {account['status']}",
        )

    # Get TOTP secret
    totp_row = db._fetchone(
        "SELECT secret_encrypted FROM security.admin_totp_credentials WHERE account_id = %s",
        (account_id,),
    )
    if not totp_row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="TOTP not enrolled for this account",
        )

    secret = decrypt_secret(totp_row["secret_encrypted"])
    if not verify_totp(secret, req.code):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid TOTP code",
        )

    # If account was pending_totp, activate it now.
    if account["status"] == "pending_totp":
        db._execute(
            "UPDATE security.admin_accounts SET status = 'active', last_login_at = now() WHERE id = %s",
            (account_id,),
        )
    else:
        db._execute(
            "UPDATE security.admin_accounts SET last_login_at = now() WHERE id = %s",
            (account_id,),
        )

    auth_time = int(time.time())
    sid = str(uuid.uuid4())

    # Issue access token
    access_token = sign_jwt(
        sub=account_id,
        typ=TYPE_ACCESS,
        sid=sid,
        authz_version=account["authz_version"],
        amr=["pwd", "totp"],
        auth_time=auth_time,
        ttl=ACCESS_TTL,
    )

    # Issue refresh token (stored as cookie)
    refresh_token, _ = create_refresh_session(account_id)

    # Set refresh cookie
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=8 * 3600,
        path="/api/v1/auth",
    )

    # Audit
    db._execute(
        """
        INSERT INTO security.admin_audit_events (account_id, event_type, detail)
        VALUES (%s, 'auth.login_success', %s::jsonb)
        """,
        (account_id, f'{{"sid": "{sid}"}}'),
    )

    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TTL,
    }


@router.post("/refresh")
async def refresh(request: Request, response: Response):
    """
    Rotate the refresh token. The old token from the cookie is invalidated;
    a new one is issued in the response cookie. A new access token is returned
    in the body.
    """
    from core import db

    old_token = request.cookies.get("refresh_token")
    if not old_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh cookie",
        )

    try:
        claims = verify_jwt(old_token, expected_type=TYPE_REFRESH)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid refresh token: {e}",
        )

    account_id = claims["sub"]

    try:
        new_refresh, _ = rotate_refresh_session(old_token, account_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )

    # Verify account is still active
    account = db._fetchone(
        "SELECT id, status, authz_version FROM security.admin_accounts WHERE id = %s",
        (account_id,),
    )
    if not account or account["status"] != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not active",
        )

    # Issue new access token
    access_token = sign_jwt(
        sub=account_id,
        typ=TYPE_ACCESS,
        sid=str(uuid.uuid4()),
        authz_version=account["authz_version"],
        amr=["pwd", "totp"],
        auth_time=claims.get("iat", int(time.time())),
        ttl=ACCESS_TTL,
    )

    response.set_cookie(
        key="refresh_token",
        value=new_refresh,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=8 * 3600,
        path="/api/v1/auth",
    )

    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TTL,
    }


@router.post("/logout")
async def logout(request: Request, response: Response):
    """Revoke the refresh session and clear the cookie."""
    from core import db

    old_token = request.cookies.get("refresh_token")
    if old_token:
        old_hash = hash_token(old_token)
        session = db._fetchone(
            "SELECT id, family_id, account_id FROM security.admin_refresh_sessions WHERE token_hash = %s",
            (old_hash,),
        )
        if session and not session.get("revoked"):
            db._execute(
                """
                UPDATE security.admin_refresh_sessions
                SET revoked = TRUE, revoked_at = now(), revoked_reason = 'logout'
                WHERE id = %s
                """,
                (session["id"],),
            )
            db._execute(
                """
                INSERT INTO security.admin_audit_events (account_id, event_type, detail)
                VALUES (%s, 'auth.logout', '{}'::jsonb)
                """,
                (session["account_id"],),
            )

    response.delete_cookie(key="refresh_token", path="/api/v1/auth")
    return {"detail": "Logged out"}
