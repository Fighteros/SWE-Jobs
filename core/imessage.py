"""
core/imessage.py — iMessage delivery via the Photon Spectrum sidecar.

Sending iMessages through Photon Spectrum requires the spectrum-ts SDK's
persistent connection (TypeScript only), so this repo ships a small Node
sidecar (sidecar/) that holds that connection and exposes a loopback HTTP
API. This module is the Python client for it — the same sidecar pattern the
Hermes agent uses to talk to Photon.

This module is synchronous (requests) so it works from async code via
asyncio.to_thread and from sync crash-alert paths alike.
"""

import hashlib
import html
import logging
import re

import requests

from core.config import (
    IMESSAGE_RECIPIENTS,
    IMESSAGE_REQUEST_TIMEOUT,
    IMESSAGE_SIDECAR_URL,
)

log = logging.getLogger(__name__)


def configured() -> bool:
    """True when iMessage admin alerts have somewhere to go."""
    return bool(IMESSAGE_SIDECAR_URL and IMESSAGE_RECIPIENTS)


def send_text(address: str, text: str) -> None:
    """Send one plain-text iMessage to a recipient via the sidecar."""
    resp = requests.post(
        f"{IMESSAGE_SIDECAR_URL.rstrip('/')}/send",
        json={"to": address, "text": text},
        timeout=IMESSAGE_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("ok"):
        raise RuntimeError(f"sidecar send failed: {payload!r:.200}")


def send_to_recipients(text: str) -> dict:
    """
    Send a plain-text message to every configured iMessage (admin) recipient.

    Never raises: per-recipient failures are logged and counted so one bad
    address does not block the rest.
    """
    stats = {"sent": 0, "failed": 0}
    for address in IMESSAGE_RECIPIENTS:
        try:
            send_text(address, text)
            stats["sent"] += 1
        except Exception as e:
            stats["failed"] += 1
            log.error(f"iMessage send failed for {address}: {e}")
    return stats


def imessage_user_telegram_id(address: str) -> int:
    """
    Stable synthetic users.telegram_id for an iMessage address.

    The users/user_alerts schema is keyed on Telegram's BIGINT ids. iMessage
    users get a deterministic NEGATIVE id derived from their address so they
    share the exact same preference and matching tables as Telegram users
    without colliding with real Telegram ids (always positive).
    """
    digest = hashlib.sha256(f"imessage:{address.strip().lower()}".encode()).digest()
    return -(int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF)


def is_imessage_user(telegram_id: int) -> bool:
    """Synthetic iMessage user ids are negative; real Telegram ids are positive."""
    return telegram_id < 0


_LINK_RE = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def html_to_plain(text: str) -> str:
    """
    Convert the bot's HTML message markup to iMessage-friendly plain text:
    links become "label: url", all other tags are dropped, entities unescaped.
    """
    text = _LINK_RE.sub(lambda m: f"{m.group(2)}: {m.group(1)}", text)
    text = _TAG_RE.sub("", text)
    return html.unescape(text)
