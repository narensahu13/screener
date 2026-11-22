from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
ws_router = APIRouter()


class ConnectionManager:
    def __init__(self) -> None:
        self.active: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self.active.append(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self.active:
                self.active.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message, default=str)
        dead: list[WebSocket] = []
        async with self._lock:
            peers = list(self.active)
        for ws in peers:
            try:
                await ws.send_text(payload)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


manager = ConnectionManager()


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    app = websocket.app
    scheduler = app.state.scheduler
    # send current snapshot
    status = scheduler.status().model_dump(mode="json")
    await websocket.send_text(
        json.dumps(
            {
                "type": "status",
                "data": status,
            },
            default=str,
        )
    )
    if scheduler.last_scan:
        await websocket.send_text(
            json.dumps(
                {"type": "scan", "data": scheduler.last_scan.model_dump(mode="json")},
                default=str,
            )
        )
    try:
        while True:
            # Keepalive / client messages (strategy switch etc.)
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            elif msg.get("type") == "set_strategy":
                name = msg.get("name")
                params = msg.get("params") or {}
                if name:
                    scheduler.set_strategy(name, params)
                    await websocket.send_text(
                        json.dumps({"type": "strategy", "data": {"name": name, "params": params}})
                    )
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as exc:  # noqa: BLE001
        logger.debug("ws closed: %s", exc)
        await manager.disconnect(websocket)


async def broadcast_scan(result) -> None:
    await manager.broadcast({"type": "scan", "data": result.model_dump(mode="json")})


async def broadcast_status(status) -> None:
    await manager.broadcast({"type": "status", "data": status.model_dump(mode="json")})
