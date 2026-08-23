from __future__ import annotations

from collections import defaultdict, deque
from threading import RLock
from typing import overload

from data.normalizer import Candle, OnChainSnapshot


class MarketStore:
    def __init__(self, max_window: int = 500, maxlen: int | None = None) -> None:
        self.max_window = maxlen if maxlen is not None else max_window
        if self.max_window <= 0:
            raise ValueError("max_window must be greater than zero")
        self._lock = RLock()
        self._windows: dict[tuple[str, str], deque[Candle]] = defaultdict(
            lambda: deque(maxlen=self.max_window)
        )
        self._onchain: dict[str, deque[OnChainSnapshot]] = defaultdict(
            lambda: deque(maxlen=self.max_window)
        )

    @overload
    def append(self, candle: Candle) -> None: ...

    @overload
    def append(self, key: str, candle: Candle) -> None: ...

    def append(self, candle_or_key: Candle | str, candle: Candle | None = None) -> None:
        """Append a canonical candle, retaining the old ``append(key, candle)`` form."""
        item = candle if candle is not None else candle_or_key
        if not isinstance(item, Candle):
            raise TypeError("append expects a Candle")
        key = (item.symbol, item.timeframe)
        with self._lock:
            self._windows[key].append(item)

    def append_onchain(self, snapshot: OnChainSnapshot) -> None:
        with self._lock:
            self._onchain[snapshot.symbol].append(snapshot)

    def get_candles(self, symbol: str, timeframe: str) -> list[Candle]:
        with self._lock:
            return list(self._windows[(symbol.upper(), timeframe)])

    def latest_candle(self, symbol: str, timeframe: str) -> Candle | None:
        with self._lock:
            window = self._windows[(symbol.upper(), timeframe)]
            return window[-1] if window else None

    def get_onchain(self, symbol: str) -> list[OnChainSnapshot]:
        with self._lock:
            return list(self._onchain[symbol.upper()])

    def get(self, key: str) -> list[Candle]:
        """Compatibility accessor for keys formatted as ``SYMBOL:TIMEFRAME``."""
        symbol, separator, timeframe = key.partition(":")
        if not separator:
            raise ValueError("market key must be formatted as SYMBOL:TIMEFRAME")
        return self.get_candles(symbol, timeframe)

    def clear(self) -> None:
        with self._lock:
            self._windows.clear()
            self._onchain.clear()
