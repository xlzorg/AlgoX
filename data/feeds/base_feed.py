from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class BaseFeed(ABC):
    def __init__(self, queue_size: int = 10_000) -> None:
        self.events_queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=queue_size)

    @abstractmethod
    async def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError

    async def events(self) -> AsyncIterator[Any]:
        while True:
            yield await self.events_queue.get()

    async def _emit(self, event: Any) -> None:
        await self.events_queue.put(event)
