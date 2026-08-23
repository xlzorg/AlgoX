from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from indicators.base_indicator import IndicatorSnapshot


@dataclass(slots=True)
class Signal:
    symbol: str
    timeframe: str
    direction: str
    confidence: float
    reasoning: dict[str, Any] = field(default_factory=dict)
    strategy_id: str = "unknown"
    timestamp: int = 0
    signal_uuid: str = ""
    market_regime: str | None = None


class BaseStrategy(ABC):
    strategy_id = "base"

    @abstractmethod
    def evaluate(self, snapshot: IndicatorSnapshot) -> Signal:
        raise NotImplementedError
from abc import ABC, abstractmethod


class BaseStrategy(ABC):
    @abstractmethod
    def evaluate(self, market: dict) -> dict | None:
        raise NotImplementedError
