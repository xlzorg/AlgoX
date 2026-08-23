from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from typing import Any

import httpx

from config.settings import get_settings
from data.feeds.base_feed import BaseFeed
from data.normalizer import OnChainSnapshot

logger = logging.getLogger(__name__)


class CoinGeckoFeed(BaseFeed):
    def __init__(
        self,
        pools: Mapping[str, tuple[str, str]] | None = None,
        *,
        base_url: str | None = None,
        poll_interval: int | None = None,
        rate_limit_per_min: int | None = None,
        client: httpx.AsyncClient | None = None,
        queue_size: int = 10_000,
    ) -> None:
        super().__init__(queue_size=queue_size)
        settings = get_settings()
        self.pools = dict(pools or {})
        self.base_url = (base_url or settings.coingecko_base_url).rstrip("/")
        self.poll_interval = poll_interval or settings.coingecko_poll_interval
        self.rate_limit_per_min = rate_limit_per_min or settings.coingecko_rate_limit_per_min
        self._client = client
        self._owns_client = client is None
        self._request_times: list[float] = []
        self._rate_lock = asyncio.Lock()
        self._cache: dict[str, tuple[float, OnChainSnapshot]] = {}
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    async def connect(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=20.0)
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = asyncio.create_task(self._run(), name="coingecko-poller")

    async def close(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def fetch_onchain(
        self,
        symbol: str,
        *,
        chain: str,
        pool_address: str,
    ) -> OnChainSnapshot:
        now = time.monotonic()
        cached = self._cache.get(symbol.upper())
        if cached and now - cached[0] < max(self.poll_interval - 5, 1):
            return cached[1]
        await self.connect()
        await self._acquire_rate_slot()
        assert self._client is not None
        response = await self._client.get(f"{self.base_url}/networks/{chain}/pools/{pool_address}")
        response.raise_for_status()
        snapshot = OnChainSnapshot.from_coingecko_terminal(
            response.json(), symbol=symbol, chain=chain
        )
        self._cache[symbol.upper()] = (time.monotonic(), snapshot)
        return snapshot

    async def poll_once(self) -> None:
        for symbol, (chain, pool_address) in self.pools.items():
            try:
                await self._emit(
                    await self.fetch_onchain(symbol, chain=chain, pool_address=pool_address)
                )
            except httpx.HTTPStatusError as exc:
                logger.warning("CoinGecko request failed for %s: %s", symbol, exc.response.status_code)
                if exc.response.status_code == 429:
                    raise
            except Exception as exc:
                logger.warning("CoinGecko poll failed for %s: %s", symbol, exc)

    async def _run(self) -> None:
        delay = 1.0
        while not self._stopping:
            try:
                await self.poll_once()
                delay = 1.0
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                raise
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, self.poll_interval)
                else:
                    await asyncio.sleep(self.poll_interval)

    async def _acquire_rate_slot(self) -> None:
        while True:
            async with self._rate_lock:
                now = time.monotonic()
                self._request_times = [stamp for stamp in self._request_times if now - stamp < 60]
                if len(self._request_times) < self.rate_limit_per_min:
                    self._request_times.append(now)
                    return
                wait_for = 60 - (now - self._request_times[0])
            await asyncio.sleep(max(wait_for, 0.01))
