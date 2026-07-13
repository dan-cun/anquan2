from __future__ import annotations

import asyncio
from collections import defaultdict

from fastapi import WebSocket

from app.schemas.events import WSMessage


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, flow_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[flow_id].add(websocket)

    async def disconnect(self, flow_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            connections = self._connections.get(flow_id)
            if not connections:
                return
            connections.discard(websocket)
            if not connections:
                self._connections.pop(flow_id, None)

    async def send_personal(self, websocket: WebSocket, event: WSMessage) -> None:
        await websocket.send_json(event.model_dump(mode="json"))

    async def broadcast(self, flow_id: str, event: WSMessage) -> None:
        async with self._lock:
            recipients = list(self._connections.get(flow_id, set()))

        stale: list[WebSocket] = []
        for websocket in recipients:
            try:
                await websocket.send_json(event.model_dump(mode="json"))
            except RuntimeError:
                stale.append(websocket)

        for websocket in stale:
            await self.disconnect(flow_id, websocket)

    async def stats(self) -> dict[str, int]:
        async with self._lock:
            return {flow_id: len(connections) for flow_id, connections in self._connections.items()}

