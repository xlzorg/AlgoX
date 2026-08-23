from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from data.data_bus import DataBus, DataEvent

router = APIRouter(tags=["live"])


class ConnectionManager:
    def __init__(self) -> None:
        self.active: list[WebSocket] = []
        self._event_task: asyncio.Task[None] | None = None
        self._event_bus: DataBus | None = None

    async def connect(self, websocket: WebSocket, event_bus: DataBus | None = None) -> None:
        await websocket.accept()
        self.active.append(websocket)
        if event_bus is not None:
            self._event_bus = event_bus
            if self._event_task is None or self._event_task.done():
                self._event_task = asyncio.create_task(self._consume_events(), name="ws-broadcaster")

    async def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active:
            self.active.remove(websocket)
        if not self.active and self._event_task is not None:
            self._event_task.cancel()
            await asyncio.gather(self._event_task, return_exceptions=True)
            self._event_task = None

    async def broadcast(self, message: dict[str, Any]) -> None:
        disconnected: list[WebSocket] = []
        for websocket in tuple(self.active):
            try:
                await websocket.send_json(message)
            except Exception:
                disconnected.append(websocket)
        for websocket in disconnected:
            if websocket in self.active:
                self.active.remove(websocket)

    async def _consume_events(self) -> None:
        if self._event_bus is None:
            return
        queue = self._event_bus.subscribe("*")
        try:
            while self.active:
                event = await queue.get()
                await self.broadcast(self._message_for(event))
        except asyncio.CancelledError:
            raise
        finally:
            self._event_bus.unsubscribe("*", queue)

    @staticmethod
    def _message_for(event: DataEvent) -> dict[str, Any]:
        payload = event.payload
        if isinstance(payload, BaseModel):
            payload = payload.model_dump(mode="json")
        elif is_dataclass(payload):
            payload = asdict(payload)
        return {"type": event.topic, "payload": payload, "ts": event.timestamp}


manager = ConnectionManager()


@router.websocket("/ws/live")
async def live_feed(websocket: WebSocket) -> None:
    engine = websocket.app.state.engine
    await manager.connect(websocket, engine.event_bus)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
