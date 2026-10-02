"""
api/auth/totp.py — TOTP generation and verification for admin accounts.

Uses the standard TOTP algorithm (RFC 6238) with HMAC-SHA1.
Secrets are encrypted at rest using a symmetric key from the environment.
"""

import base64
import hashlib
import hmac
import logging
import os
import struct
import time
from typing import Optional

logger = logging.getLogger(__name__)


_encryption_key: Optional[bytes] = None

def _get_encryption_key() -> bytes:
    """Get the TOTP encryption key from env. Must be 32 bytes (256-bit)."""
    global _encryption_key
    if _encryption_key is not None:
        return _encryption_key
    key_hex = os.getenv("TOTP_ENCRYPTION_KEY", "")
    if key_hex:
        _encryption_key = bytes.fromhex(key_hex)
    else:
        logger.warning(
            "TOTP_ENCRYPTION_KEY not set — using a generated key (not persistent). "
            "Set TOTP_ENCRYPTION_KEY env var for production."
        )
        _encryption_key = os.urandom(32)
    return _encryption_key


def _xor_encrypt(data: bytes, key: bytes) -> bytes:
    """Simple XOR encryption for TOTP secrets (adequate for at-rest protection)."""
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def encrypt_secret(secret: str) -> bytes:
    """Encrypt a TOTP secret for storage."""
    key = _get_encryption_key()
    return _xor_encrypt(secret.encode("utf-8"), key)


def decrypt_secret(encrypted: bytes) -> str:
    """Decrypt a stored TOTP secret."""
    key = _get_encryption_key()
    return _xor_encrypt(encrypted, key).decode("utf-8")


def generate_totp_secret() -> str:
    """Generate a new TOTP secret (base32-encoded 20 bytes)."""
    return base64.b32encode(os.urandom(20)).decode("utf-8")


def _hotp(secret: str, counter: int, digits: int = 6) -> str:
    """HOTP (RFC 4226) — HMAC-based one-time password."""
    key = base64.b32decode(secret, casefold=True)
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code = struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    """
    Verify a TOTP code against the secret within the time window.
    window=1 allows ±30 seconds drift.
    """
    if not code or not secret:
        return False

    now = int(time.time() // 30)
    for offset in range(-window, window + 1):
        expected = _hotp(secret, now + offset)
        if hmac.compare_digest(expected, code):
            return True
    return False


def get_totp_uri(secret: str, email: str, issuer: str = "SWE-Jobs Admin") -> str:
    """Generate the otpauth:// URI for QR code enrollment."""
    label = f"{issuer}:{email}"
    return (
        f"otpauth://totp/{label}?secret={secret}"
        f"&issuer={issuer}&algorithm=SHA1&digits=6&period=30"
    )
