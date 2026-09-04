from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PositionSize:
    quantity: float
    risk_amount: float
    risk_fraction: float
    notional: float          # added: qty * entry_price, useful for callers
    capped_by_exposure: bool # added: flag so callers know which limit bound the size


class PositionSizer:
    def __init__(
        self,
        max_risk_fraction: float = 0.01,
        atr_stop_multiplier: float = 2.5,
        max_single_asset_fraction: float = 0.20,  # FIX: sizer owns this limit now
    ) -> None:
        self.max_risk_fraction = max_risk_fraction
        self.atr_stop_multiplier = atr_stop_multiplier
        self.max_single_asset_fraction = max_single_asset_fraction

    def half_kelly(self, win_rate: float, average_win_loss: float) -> float:
        """
        Half-Kelly fraction. With default params (wr=0.5, awl=2.0) this returns
        0.125, which gets capped by max_risk_fraction (0.01) in practice.
        """
        if average_win_loss <= 0:
            return 0.0
        loss_rate = 1.0 - win_rate
        return max(0.0, ((win_rate * average_win_loss - loss_rate) / average_win_loss) * 0.5)

    def calculate(
        self,
        equity: float,
        atr: float,
        entry_price: float,
        *,
        win_rate: float = 0.5,
        average_win_loss: float = 2.0,
    ) -> PositionSize:
        """
        Returns the position size bounded by BOTH:
          1. ATR-based risk (risk_fraction × equity / (atr × multiplier))
          2. Max notional exposure (max_single_asset_fraction × equity / entry_price)

        The smaller of the two is used. This means the exposure check in
        RiskGuard no longer needs to REJECT the order — the sizer already
        caps quantity so it fits within the exposure limit.

        BUG THAT WAS FIXED:
          Old code: computed qty from ATR risk, then RiskGuard checked
            notional > equity * 0.20 and REJECTED, blocking all BTC trades
            (BTC notional is almost always > 20% of a $10k account).
          New code: qty = min(qty_from_risk, qty_from_exposure), so the
            order always passes and is sized correctly.
        """
        if equity <= 0 or atr <= 0 or entry_price <= 0:
            return PositionSize(0.0, 0.0, 0.0, 0.0, False)

        risk_fraction = min(self.half_kelly(win_rate, average_win_loss), self.max_risk_fraction)
        risk_amount = equity * risk_fraction

        # Path 1: size from ATR-based risk
        qty_from_risk = risk_amount / (atr * self.atr_stop_multiplier)

        # Path 2: size from max notional cap
        max_notional = equity * self.max_single_asset_fraction
        qty_from_exposure = max_notional / entry_price

        # Take the more conservative quantity
        quantity = min(qty_from_risk, qty_from_exposure)
        capped = qty_from_exposure < qty_from_risk

        notional = quantity * entry_price
        return PositionSize(quantity, risk_amount, risk_fraction, notional, capped)

    def size(self, equity: float, risk_pct: float, stop_distance: float) -> float:
        """Simple % risk sizing (alternative helper, unchanged)."""
        if stop_distance <= 0:
            return 0.0
        return equity * min(risk_pct / 100.0, self.max_risk_fraction) / stop_distance