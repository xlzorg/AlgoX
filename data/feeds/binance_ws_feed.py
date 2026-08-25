from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

import websockets

from config.settings import get_settings
from config.symbols import WS_TIMEFRAMES
from data.feeds.base_feed import BaseFeed
from data.normalizer import Candle

logger = logging.getLogger(__name__)


class BinanceWebSocketFeed(BaseFeed):
    def __init__(
        self,
        symbols: list[str] | None = None,
        timeframes: list[str] | None = None,
        *,
        url: str | None = None,
        reconnect_initial: float = 1.0,
        reconnect_max: float = 30.0,
        websocket_factory: Callable[..., Any] | None = None,
        queue_size: int = 10_000,
    ) -> None:
        super().__init__(queue_size=queue_size)
        settings = get_settings()
        self.symbols = [symbol.lower() for symbol in (symbols or settings.symbols)]
        self.timeframes = timeframes or WS_TIMEFRAMES
        self.url = url or settings.binance_ws_url
        self.reconnect_initial = reconnect_initial
        self.reconnect_max = reconnect_max
        self.websocket_factory = websocket_factory or websockets.connect
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    async def close(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def connect(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="binance-ws-feed")

    def stream_names(self) -> list[str]:
        streams = [
            f"{symbol}@kline_{timeframe}"
            for symbol in self.symbols
            for timeframe in self.timeframes
        ]
        streams.extend(f"{symbol}@aggTrade" for symbol in self.symbols)
        return streams

    def stream_url(self) -> str:
        return f"{self.url}?streams={ '/'.join(self.stream_names())}"

    async def _run(self) -> None:
        delay = self.reconnect_initial
        while not self._stopping:
            try:
                async with self.websocket_factory(self.stream_url(), ping_interval=20, ping_timeout=20) as socket:
                    delay = self.reconnect_initial
                    async for raw_message in socket:
                        await self._handle_message(raw_message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Binance WebSocket disconnected: %s", exc)
                if not self._stopping:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, self.reconnect_max)

    async def _handle_message(self, raw_message: str | bytes | dict[str, Any]) -> None:
        payload = raw_message if isinstance(raw_message, dict) else json.loads(raw_message)
        data = payload.get("data", payload)
        if data.get("e") == "kline":
            candle = Candle.from_binance_ws(payload)
            logger.info(
                "FEED yield %s %s closed=%s t=%s",
                candle.symbol, candle.timeframe, candle.is_closed, candle.open_time,
            )
    
            await self._emit(candle)
            return
        if data.get("e") == "aggTrade":
            await self._emit(
                {
                    "event_type": "trade",
                    "symbol": str(data.get("s", "")).upper(),
                    "trade_id": data.get("a"),
                    "price": float(data["p"]),
                    "quantity": float(data["q"]),
                    "timestamp": int(data["T"]),
                    "is_buyer_maker": bool(data.get("m", False)),
                }
            )