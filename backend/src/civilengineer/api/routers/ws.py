"""
WebSocket endpoint.

Connect:
    ws://host/api/v1/ws/{project_id}?token=<access_token>

Authentication uses the access JWT passed as a query parameter (Bearer
cookies cannot be sent in a browser WebSocket handshake).

Once connected the client receives real-time events for that project:
    { "type": "plot.analyzed", "project_id": "...", "confidence": 0.95, ... }
    { "type": "job.progress",  "project_id": "...", "step": "geometry", ... }
    { "type": "job.completed", "project_id": "...", "session_id": "..." }

The client can send "ping" text frames; the server replies "pong".
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from civilengineer.api.websocket import manager, redis_pubsub_listener
from civilengineer.auth.jwt import decode_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])

# WebSocket close codes
_WS_POLICY_VIOLATION = 1008


@router.websocket("/{project_id}")
async def websocket_endpoint(
    project_id: str,
    websocket: WebSocket,
    token: str = "",
) -> None:
    """
    Real-time event stream for a project.

    Query param:
        token  — a valid access JWT (same as Authorization: Bearer …)
    """
    # ---- Authenticate ----
    if not token:
        await websocket.close(code=_WS_POLICY_VIOLATION)
        return
    try:
        decode_token(token)  # raises if expired / invalid
    except Exception:
        await websocket.close(code=_WS_POLICY_VIOLATION)
        return

    # ---- Accept and register ----
    await manager.connect(project_id, websocket)

    # Start Redis listener as a background task
    listener = asyncio.create_task(
        redis_pubsub_listener(project_id, websocket)
    )

    try:
        while True:
            try:
                text = await websocket.receive_text()
                if text.strip() == "ping":
                    await websocket.send_text("pong")
            except WebSocketDisconnect:
                break
    finally:
        listener.cancel()
        try:
            await listener
        except (asyncio.CancelledError, Exception):
            pass
        manager.disconnect(project_id, websocket)
