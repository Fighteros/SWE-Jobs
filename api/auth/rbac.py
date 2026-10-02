"""
api/auth/rbac.py — Role-Based Access Control for admin endpoints.

Provides FastAPI dependency functions for requiring permissions on endpoints.
The backend database is the authority for account status, roles, and permissions.
JWT role claims alone never authorize privileged operations.
"""

import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request, status

logger = logging.getLogger(__name__)


async def get_current_account(request: Request) -> dict:
    """
    Extract and verify the access JWT from the Authorization header.
    Returns the account dict (id, email, authz_version, status).

    Raises 401 if no token, invalid token, or wrong token type.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header[7:]
    try:
        from api.auth.jwt import verify_jwt, TYPE_ACCESS
        claims = verify_jwt(token, expected_type=TYPE_ACCESS)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "id": claims["sub"],
        "authz_version": claims.get("authz_version", 1),
        "sid": claims.get("sid"),
        "amr": claims.get("amr", []),
    }


async def get_account_permissions(account_id: str, db_module=None) -> set[str]:
    """Look up the account's permissions from the database (union of all roles)."""
    if db_module is None:
        from core import db as db_module

    rows = db_module._fetchall(
        """
        SELECT p.key
        FROM security.admin_account_roles ar
        JOIN security.admin_role_permissions rp ON rp.role_id = ar.role_id
        JOIN security.admin_permissions p ON p.id = rp.permission_id
        WHERE ar.account_id = %s
        """,
        (account_id,),
    )
    return {row["key"] for row in rows} if rows else set()


def require_permission(*permissions: str):
    """
    FastAPI dependency factory that requires the caller to have ALL the given
    permissions. Checks the database (not JWT claims) for authorization.

    Usage:
        @router.get("/api/v1/jobs")
        async def list_jobs(account=Depends(require_permission("jobs.read"))):
            ...
    """
    async def _check(account: dict = Depends(get_current_account)) -> dict:
        account_perms = await get_account_permissions(account["id"])
        missing = set(permissions) - account_perms
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permissions: {', '.join(sorted(missing))}",
            )
        return account

    return _check
