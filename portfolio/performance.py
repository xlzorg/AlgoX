from __future__ import annotations

import time
from dataclasses import dataclass

from broker.virtual_wallet import VirtualWallet
from portfolio.position_tracker import PositionTracker


@dataclass(slots=True)
class EquityPoint:
    timestamp: int
    equity: float
    drawdown_pct: float
    peak_equity: float


class Performance:
    def __init__(self, wallet: VirtualWallet, tracker: PositionTracker) -> None:
        self.wallet = wallet
        self.tracker = tracker
        self.points: list[EquityPoint] = []

    def snapshot(self, prices: dict[str, float], timestamp: int | None = None) -> EquityPoint:
        equity = self.wallet.equity(prices)
        peak = max([point.peak_equity for point in self.points] + [self.wallet.starting_balance, equity])
        point = EquityPoint(timestamp or int(time.time() * 1000), equity, (peak - equity) / peak * 100 if peak else 0.0, peak)
        self.points.append(point)
        return point

    def returns(self) -> list[float]:
        return [point.equity for point in self.points]
