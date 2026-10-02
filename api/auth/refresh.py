"""
api/auth/refresh.py — Refresh token rotation with family revocation.

Refresh tokens are stored as hashes. Each refresh belongs to a family.
Reusing an old (rotated) token revokes the entire family and creates an audit event.
"""

import hashlib
import logging
import uuid
from typing import Optional

logger = logging.getLogger(__name__)


def hash_token(token: str) -> str:
    """SHA-256 hash a refresh token for storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_refresh_session(
    account_id: str,
    family_id: Optional[str] = None,
    ttl_seconds: int = 8 * 3600,
    db_module=None,
) -> tuple[str, str]:
    """
    Create a new refresh session. Returns (token, session_id).
    If family_id is None, a new family is started.
    """
    from api.auth.jwt import sign_jwt, TYPE_REFRESH, REFRESH_TTL
    from datetime import datetime, timezone, timedelta

    if db_module is None:
        from core import db as db_module

    family_id = family_id or str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    token = sign_jwt(
        sub=account_id,
        typ=TYPE_REFRESH,
        sid=session_id,
        ttl=REFRESH_TTL,
    )
    token_h = hash_token(token)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

    db_module._execute(
        """
        INSERT INTO security.admin_refresh_sessions
            (id, account_id, family_id, token_hash, expires_at)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (session_id, account_id, family_id, token_h, expires_at),
    )

    return token, session_id


def rotate_refresh_session(
    old_token: str,
    account_id: str,
    db_module=None,
) -> tuple[str, str]:
    """
    Rotate a refresh token: validate the old one, mark it used, create a new one
    in the same family. If the old token was already used, revoke the entire
    family (token theft detected) and create an audit event.

    Returns (new_token, session_id).

    Raises ValueError if the old token is invalid, expired, or revoked.
    """
    if db_module is None:
        from core import db as db_module

    old_hash = hash_token(old_token)

    session = db_module._fetchone(
        """
        SELECT id, family_id, account_id, revoked, reused, expires_at
        FROM security.admin_refresh_sessions
        WHERE token_hash = %s
        """,
        (old_hash,),
    )

    if session is None:
        raise ValueError("Invalid refresh token")

    if session["revoked"]:
        raise ValueError("Refresh token has been revoked")

    if session["expires_at"] and session["expires_at"] < datetime.now(timezone.utc):
        raise ValueError("Refresh token has expired")

    if session["reused"]:
        # Token theft detected — revoke the entire family.
        logger.warning(
            f"Refresh token reuse detected for family {session['family_id']} "
            f"account {session['account_id']} — revoking family"
        )
        db_module._execute(
            """
            UPDATE security.admin_refresh_sessions
            SET revoked = TRUE, revoked_at = now(), revoked_reason = 'token_reuse_detected'
            WHERE family_id = %s AND revoked = FALSE
            """,
            (session["family_id"],),
        )
        db_module._execute(
            """
            INSERT INTO security.admin_audit_events (account_id, event_type, detail)
            VALUES (%s, 'auth.refresh_token_reuse', %s::jsonb)
            """,
            (session["account_id"], f'{{"family_id": "{session["family_id"]}"}}'),
        )
        raise ValueError("Refresh token reuse detected — session family revoked")

    # Mark old token as used (reused flag prevents future reuse).
    db_module._execute(
        """
        UPDATE security.admin_refresh_sessions
        SET reused = TRUE
        WHERE id = %s
        """,
        (session["id"],),
    )

    # Create new token in the same family.
    new_token, new_session_id = create_refresh_session(
        account_id=account_id,
        family_id=session["family_id"],
        db_module=db_module,
    )

    return new_token, new_session_id


def revoke_refresh_family(family_id: str, reason: str = "manual", db_module=None):
    """Revoke all tokens in a refresh family."""
    if db_module is None:
        from core import db as db_module

    db_module._execute(
        """
        UPDATE security.admin_refresh_sessions
        SET revoked = TRUE, revoked_at = now(), revoked_reason = %s
        WHERE family_id = %s AND revoked = FALSE
        """,
        (reason, family_id),
    )
