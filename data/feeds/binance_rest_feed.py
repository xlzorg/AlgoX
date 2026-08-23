from __future__ import annotations

from typing import Any

import httpx

from config.settings import get_settings
from data.normalizer import Candle


class BinanceRestFeed:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        history_candles: int | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.binance_rest_url).rstrip("/")
        self.history_candles = history_candles or settings.history_candles
        self._client = client
        self._owns_client = client is None

    async def connect(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        *,
        limit: int | None = None,
    ) -> list[Candle]:
        await self.connect()
        assert self._client is not None
        response = await self._client.get(
            f"{self.base_url}/api/v3/klines",
            params={"symbol": symbol.upper(), "interval": timeframe, "limit": limit or self.history_candles},
        )
        response.raise_for_status()
        payload: list[list[Any]] = response.json()
        return [
            Candle.from_binance_rest(item, symbol=symbol, timeframe=timeframe)
            for item in payload
        ]

    async def bootstrap(
        self,
        symbols: list[str],
        timeframes: list[str],
    ) -> list[Candle]:
        candles: list[Candle] = []
        for symbol in symbols:
            for timeframe in timeframes:
                candles.extend(await self.fetch_candles(symbol, timeframe))
        return candles
