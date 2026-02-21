"""
WebSocket connection manager + Redis pub/sub bridge.

Each project has a Redis pub/sub channel:
    project:{project_id}:events

Events published by Celery workers are forwarded to all connected WebSocket
clients watching that project.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Tracks active WebSocket connections keyed by project_id."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, project_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[project_id].add(websocket)
        logger.info(
            "WS connected project=%s total=%d",
            project_id,
            len(self._connections[project_id]),
        )

    def disconnect(self, project_id: str, websocket: WebSocket) -> None:
        self._connections[project_id].discard(websocket)
        if not self._connections[project_id]:
            del self._connections[project_id]
        logger.info("WS disconnected project=%s", project_id)

    async def broadcast(self, project_id: str, message: dict[str, Any]) -> None:
        """Send message to all sockets watching project_id; remove dead ones."""
        dead: set[WebSocket] = set()
        for ws in list(self._connections.get(project_id, [])):
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._connections[project_id].discard(ws)


# Singleton used by the WebSocket router and tests
manager = ConnectionManager()


async def redis_pubsub_listener(project_id: str, websocket: WebSocket) -> None:
    """
    Subscribe to project:{project_id}:events on Redis and forward every
    message to the given WebSocket.  Runs as an asyncio task.
    """
    import redis.asyncio as aioredis

    from civilengineer.core.config import get_settings

    settings = get_settings()
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = r.pubsub()
    channel = f"project:{project_id}:events"
    try:
        await pubsub.subscribe(channel)
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    await websocket.send_json(data)
                except Exception as exc:
                    logger.warning("WS forward error project=%s: %s", project_id, exc)
                    break
    finally:
        try:
            await pubsub.unsubscribe(channel)
        except Exception:
            pass
        await r.aclose()
