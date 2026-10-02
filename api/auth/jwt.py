"""
api/auth/jwt.py — JWT signing and verification using Ed25519/EdDSA.

Supports key IDs and rotation. Token types: access, mfa_challenge, refresh,
invitation. Each type has distinct claims and expiry.

Keys are generated on first use and stored in the database (security.admin_*)
or loaded from environment variables for development.
"""

import logging
import os
import time
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

# Token type constants
TYPE_ACCESS = "access"
TYPE_MFA_CHALLENGE = "mfa_challenge"
TYPE_REFRESH = "refresh"
TYPE_INVITATION = "invitation"

# Expiry in seconds
ACCESS_TTL = 600           # 10 minutes
MFA_CHALLENGE_TTL = 300     # 5 minutes
REFRESH_TTL = 8 * 3600     # 8 hours
INVITATION_TTL = 24 * 3600  # 24 hours


class JWTKeyManager:
    """Manages Ed25519 signing keys with key IDs and rotation support."""

    def __init__(self):
        self._current_kid: Optional[str] = None
        self._keys: dict[str, bytes] = {}  # kid -> private key bytes
        self._public_keys: dict[str, bytes] = {}  # kid -> public key bytes

    def _generate_keypair(self) -> tuple[bytes, bytes]:
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import (
                Encoding, PrivateFormat, PublicFormat, NoEncryption
            )
        except ImportError:
            raise SystemExit("cryptography is required: pip install cryptography")
        priv = Ed25519PrivateKey.generate()
        pub = priv.public_key()
        # Store keys in PEM format (what PyJWT expects for EdDSA).
        priv_pem = priv.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        pub_pem = pub.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
        return priv_pem, pub_pem

    def load_or_generate(self, kid: Optional[str] = None) -> str:
        """Load keys from env or generate new ones. Returns the active key ID."""
        if kid is None:
            kid = f"kid-{uuid.uuid4().hex[:8]}"

        env_priv = os.getenv("JWT_SIGNING_KEY")
        if env_priv:
            kid = os.getenv("JWT_KEY_ID", "env-key")
            try:
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
                from cryptography.hazmat.primitives.serialization import (
                    Encoding, PrivateFormat, PublicFormat, NoEncryption, load_pem_private_key
                )
                raw = bytes.fromhex(env_priv)
                priv = Ed25519PrivateKey.from_private_bytes(raw)
                priv_pem = priv.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
                pub_pem = priv.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
                self._keys[kid] = priv_pem
                self._public_keys[kid] = pub_pem
            except Exception as e:
                raise SystemExit(f"Invalid JWT_SIGNING_KEY: {e}")
        else:
            priv, pub = self._generate_keypair()
            self._keys[kid] = priv
            self._public_keys[kid] = pub
            logger.warning(
                "JWT signing key generated in memory (not persistent). "
                "Set JWT_SIGNING_KEY env var for production."
            )

        self._current_kid = kid
        return kid

    @property
    def current_kid(self) -> str:
        if self._current_kid is None:
            self.load_or_generate()
        return self._current_kid

    def get_private_key(self, kid: Optional[str] = None) -> bytes:
        kid = kid or self.current_kid
        if kid not in self._keys:
            raise KeyError(f"Unknown key ID: {kid}")
        return self._keys[kid]

    def get_public_key(self, kid: str) -> bytes:
        if kid not in self._public_keys:
            raise KeyError(f"Unknown key ID: {kid}")
        return self._public_keys[kid]


_key_manager = JWTKeyManager()


def sign_jwt(
    sub: str,
    typ: str,
    sid: Optional[str] = None,
    authz_version: Optional[int] = None,
    amr: Optional[list[str]] = None,
    auth_time: Optional[int] = None,
    extra_claims: Optional[dict] = None,
    ttl: Optional[int] = None,
) -> str:
    """Sign a JWT with Ed25519/EdDSA. Returns the compact JWT string."""
    try:
        import jwt as pyjwt
    except ImportError:
        raise SystemExit("PyJWT is required: pip install PyJWT[crypto]")

    kid = _key_manager.current_kid
    priv_key = _key_manager.get_private_key(kid)

    now = int(time.time())
    ttl = ttl if ttl is not None else ACCESS_TTL
    jti = str(uuid.uuid4())
    iss = os.getenv("JWT_ISSUER", "swe-jobs-api")
    aud = os.getenv("JWT_AUDIENCE", "swe-jobs-dashboard")

    payload = {
        "iss": iss,
        "aud": aud,
        "sub": sub,
        "jti": jti,
        "iat": now,
        "nbf": now,
        "exp": now + ttl,
        "typ": typ,
    }
    if sid:
        payload["sid"] = sid
    if authz_version is not None:
        payload["authz_version"] = authz_version
    if amr:
        payload["amr"] = amr
    if auth_time:
        payload["auth_time"] = auth_time
    if extra_claims:
        payload.update(extra_claims)

    headers = {"kid": kid}
    token = pyjwt.encode(payload, priv_key, algorithm="EdDSA", headers=headers)
    return token


def verify_jwt(token: str, expected_type: Optional[str] = None) -> dict:
    """
    Verify a JWT signature, issuer, audience, type, and timestamps.
    Returns the decoded claims dict.
    Raises jwt.InvalidTokenError on any failure.
    """
    try:
        import jwt as pyjwt
    except ImportError:
        raise SystemExit("PyJWT is required: pip install PyJWT[crypto]")

    # Decode header to get kid
    unverified_header = pyjwt.get_unverified_header(token)
    kid = unverified_header.get("kid")
    if not kid:
        raise pyjwt.InvalidTokenError("Missing kid in header")

    pub_key = _key_manager.get_public_key(kid)

    iss = os.getenv("JWT_ISSUER", "swe-jobs-api")
    aud = os.getenv("JWT_AUDIENCE", "swe-jobs-dashboard")

    payload = pyjwt.decode(
        token,
        pub_key,
        algorithms=["EdDSA"],
        issuer=iss,
        audience=aud,
    )

    if expected_type and payload.get("typ") != expected_type:
        raise pyjwt.InvalidTokenError(
            f"Wrong token type: expected {expected_type}, got {payload.get('typ')}"
        )

    return payload
