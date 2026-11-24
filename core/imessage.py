"""
core/imessage.py — iMessage delivery via the Photon Advanced iMessage HTTP API.

Photon exposes a small REST surface (see photon.codes/docs, "Advanced iMessage
SDK", HTTP transport): bearer-token auth, chats are created once per recipient
to obtain a server chat guid, then text messages are posted to that chat.

This module is synchronous (requests) so it works from async code via
asyncio.to_thread and from sync crash-alert paths alike.
"""

import html
import logging
import re

import requests

from core.config import (
    IMESSAGE_RECIPIENTS,
    PHOTON_REQUEST_TIMEOUT,
    PHOTON_SERVER_ADDRESS,
    PHOTON_TOKEN,
)

log = logging.getLogger(__name__)

# Photon chat service type for iMessage (CHAT_SERVICE_TYPE_IMESSAGE).
_CHAT_SERVICE_IMESSAGE = 1

# Per-process cache: recipient address -> Photon chat guid.
_chat_guid_cache: dict[str, str] = {}


def configured() -> bool:
    """True when iMessage delivery has everything it needs to run."""
    return bool(PHOTON_SERVER_ADDRESS and PHOTON_TOKEN and IMESSAGE_RECIPIENTS)


def _base_url() -> str:
    address = PHOTON_SERVER_ADDRESS.strip().rstrip("/")
    if not address.startswith(("http://", "https://")):
        # Bare host[:port] defaults to https, matching the Photon SDK.
        address = f"https://{address}"
    return address


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {PHOTON_TOKEN}",
        "Content-Type": "application/json",
    }


def get_chat_guid(address: str) -> str:
    """
    Resolve a recipient (phone or email) to a Photon chat guid, creating the
    chat on first use. Cached for the process lifetime.
    """
    cached = _chat_guid_cache.get(address)
    if cached:
        return cached

    resp = requests.post(
        f"{_base_url()}/v1/chats",
        headers=_headers(),
        json={"addresses": [address], "service": _CHAT_SERVICE_IMESSAGE},
        timeout=PHOTON_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    chat = payload.get("chat") or {}
    guid = chat.get("guid")
    if not guid:
        raise RuntimeError(f"Photon chat create returned no chat.guid: {payload!r:.200}")
    _chat_guid_cache[address] = guid
    return guid


def send_text(address: str, text: str) -> str:
    """Send one plain-text iMessage to a recipient. Returns the message guid."""
    chat_guid = get_chat_guid(address)
    resp = requests.post(
        f"{_base_url()}/v1/messages:sendText",
        headers=_headers(),
        json={"chatGuid": chat_guid, "text": text},
        timeout=PHOTON_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    message = payload.get("message") or {}
    return message.get("guid", "")


def send_to_recipients(text: str) -> dict:
    """
    Send a plain-text message to every configured iMessage recipient.

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
