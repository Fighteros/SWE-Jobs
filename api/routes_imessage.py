"""Authenticated inbound iMessage webhook from the Photon sidecar."""

import asyncio
import hmac
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core import config, db

router = APIRouter()
log = logging.getLogger(__name__)



@router.post("/imessage/inbound")
async def imessage_inbound(request: Request) -> JSONResponse:
    if config.DELIVERY_CHANNEL != "imessage":
        return JSONResponse({"ok": False}, status_code=404)
    secret = config.IMESSAGE_WEBHOOK_SECRET
    if not secret or not hmac.compare_digest(
        request.headers.get("authorization", "").encode(), f"Bearer {secret}".encode()
    ):
        return JSONResponse({"ok": False}, status_code=401)

    try:
        payload = await request.json()
    except ValueError:
        payload = None
    if not isinstance(payload, dict) or not all(
        isinstance(payload.get(key), str) and payload[key].strip()
        for key in ("from", "text", "message_id")
    ):
        return JSONResponse({"ok": False, "reason": "invalid_event"}, status_code=400)

    try:
        await asyncio.to_thread(
            db.process_imessage_event,
            payload["from"].strip().lower(), payload["message_id"].strip(), payload["text"],
        )
    except Exception:
        log.exception("iMessage event processing failed")
        return JSONResponse({"ok": False}, status_code=503)
    return JSONResponse({"ok": True, "handled": True})
