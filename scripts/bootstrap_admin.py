"""
Idempotent super-admin bootstrap command.

Creates the first super-admin account if none exists. The account starts in
'pending_totp' status — the admin must enroll TOTP before they can log in.

Usage:
    python -m scripts.bootstrap_admin --email admin@example.com --name "Super Admin"

If a super_admin account already exists, prints its email and exits 0.
The password is generated randomly and printed once to stdout. Argon2id is
used for hashing. The password hash is stored; the plaintext is never persisted.

Requirements:
    - Migration 009 (security schema) must be applied.
    - argon2-cffi must be installed (pip install argon2-cffi).
"""

import argparse
import logging
import secrets
import string
import sys
import uuid

logger = logging.getLogger(__name__)

def _generate_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _hash_password(password: str) -> str:
    try:
        from argon2 import PasswordHasher, Type
    except ImportError:
        raise SystemExit(
            "argon2-cffi is required: pip install argon2-cffi"
        )
    ph = PasswordHasher(
        type=Type.ID,  # Argon2id
        memory_cost=65536,
        time_cost=3,
        parallelism=4,
    )
    return ph.hash(password)


def bootstrap_admin(email: str, display_name: str, db_module=None) -> dict:
    """
    Create the first super-admin account if none exists.

    Returns a dict with:
        - created: bool — whether a new account was created
        - email: str — the super-admin email
        - password: str|None — the generated password (only if created)
        - account_id: str|None — the UUID of the account
    """
    if db_module is None:
        from core import db as db_module

    email = email.strip().lower()

    existing = db_module._fetchone(
        """SELECT a.id, a.email, a.status
           FROM security.admin_accounts a
           JOIN security.admin_account_roles ar ON ar.account_id = a.id
           JOIN security.admin_roles r ON r.id = ar.role_id
           WHERE r.name = 'super_admin'"""
    )

    if existing:
        logger.info(f"Super-admin already exists: {existing['email']} (status={existing['status']})")
        return {"created": False, "email": existing["email"], "password": None, "account_id": str(existing["id"])}

    password = _generate_password()
    password_hash = _hash_password(password)
    account_id = str(uuid.uuid4())

    db_module._execute(
        """
        INSERT INTO security.admin_accounts (id, email, display_name, password_hash, status, password_changed_at)
        VALUES (%s, %s, %s, %s, 'pending_totp', now())
        """,
        (account_id, email, display_name, password_hash),
    )

    db_module._execute(
        """
        INSERT INTO security.admin_account_roles (account_id, role_id, granted_by)
        SELECT %s, r.id, %s
        FROM security.admin_roles r WHERE r.name = 'super_admin'
        """,
        (account_id, account_id),
    )

    db_module._execute(
        """
        INSERT INTO security.admin_audit_events (account_id, event_type, detail)
        VALUES (%s, 'admin.bootstrap', %s::jsonb)
        """,
        (account_id, f'{{"email": "{email}", "display_name": "{display_name}"}}'),
    )

    logger.info(f"Created super-admin: {email} (id={account_id})")
    return {"created": True, "email": email, "password": password, "account_id": account_id}


def main():
    parser = argparse.ArgumentParser(description="Bootstrap the first super-admin account.")
    parser.add_argument("--email", required=True, help="Admin email address")
    parser.add_argument("--name", required=True, help="Display name")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    result = bootstrap_admin(args.email, args.name)

    if result["created"]:
        print("\n" + "=" * 60)
        print("  Super-admin account created successfully!")
        print(f"  Email:    {result['email']}")
        print(f"  Password: {result['password']}")
        print(f"  ID:       {result['account_id']}")
        print("=" * 60)
        print("\n  IMPORTANT: Save this password — it will NOT be shown again.")
        print("  Next step: enroll TOTP at first login.\n")
    else:
        print(f"\n  Super-admin already exists: {result['email']}")
        print(f"  Account ID: {result['account_id']}\n")


if __name__ == "__main__":
    main()
