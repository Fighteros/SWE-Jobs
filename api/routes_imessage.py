"""
api/routes_imessage.py — inbound iMessage webhook from the Photon Spectrum sidecar.

The sidecar (sidecar/) holds the persistent spectrum-ts connection and posts
each inbound iMessage here as JSON:
  {"from": "+15551234567", "text": "...", "space_id": "...", "message_id": "..."}

The sender is registered as an iMessage user (synthetic negative telegram_id,
address in users.username), the text is dispatched to the command handler,
and the reply is sent back through the sidecar.

Always returns HTTP 200: a non-2xx would make the sidecar treat the inbound
message as failed and retry it, and a user-facing error belongs in the reply
message, not the HTTP status.
"""

import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()
log = logging.getLogger(__name__)


@router.post("/imessage/inbound")
async def imessage_inbound(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": True, "handled": False, "reason": "invalid_json"})

    address = str(payload.get("from") or "").strip()
    text = str(payload.get("text") or "").strip()
    if not address or not text:
        return JSONResponse({"ok": True, "handled": False, "reason": "missing_from_or_text"})

    from bot.imessage_commands import handle_inbound
    from core import imessage

    try:
        reply = await handle_inbound(address, text)
    except Exception as e:
        log.error(f"iMessage inbound handling failed for a sender: {e}")
        return JSONResponse({"ok": True, "handled": False, "reason": "handler_error"})

    if reply:
        try:
            await asyncio.to_thread(imessage.send_text, address, reply)
        except Exception as e:
            log.error(f"iMessage reply send failed: {e}")
            return JSONResponse({"ok": True, "handled": False, "reason": "reply_send_failed"})

    return JSONResponse({"ok": True, "handled": True})
