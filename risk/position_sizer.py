from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PositionSize:
    quantity: float
    risk_amount: float
    risk_fraction: float


class PositionSizer:
    def __init__(self, max_risk_fraction: float = 0.01, atr_stop_multiplier: float = 1.5) -> None:
        self.max_risk_fraction = max_risk_fraction
        self.atr_stop_multiplier = atr_stop_multiplier

    def half_kelly(self, win_rate: float, average_win_loss: float) -> float:
        loss_rate = 1 - win_rate
        if average_win_loss <= 0:
            return 0.0
        return max(0.0, ((win_rate * average_win_loss - loss_rate) / average_win_loss) * 0.5)

    def calculate(self, equity: float, atr: float, entry_price: float, *, win_rate: float = 0.5, average_win_loss: float = 2.0) -> PositionSize:
        if equity <= 0 or atr <= 0 or entry_price <= 0:
            return PositionSize(0.0, 0.0, 0.0)
        risk_fraction = min(self.half_kelly(win_rate, average_win_loss), self.max_risk_fraction)
        risk_amount = equity * risk_fraction
        return PositionSize(risk_amount / (atr * self.atr_stop_multiplier), risk_amount, risk_fraction)

    def size(self, equity: float, risk_pct: float, stop_distance: float) -> float:
        if stop_distance <= 0:
            return 0.0
        return equity * min(risk_pct / 100, self.max_risk_fraction) / stop_distance
