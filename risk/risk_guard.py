from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from config.settings import get_settings
from indicators.base_indicator import IndicatorSnapshot
from risk.drawdown_circuit import DrawdownCircuit
from risk.exposure_guard import ExposureGuard
from risk.position_sizer import PositionSizer
from risk.stop_loss import calculate_stop_loss
from risk.take_profit import calculate_targets
from strategy.base_strategy import Signal


@dataclass(slots=True)
class OrderIntent:
    approved: bool
    signal_uuid: str
    symbol: str
    direction: str
    quantity: float = 0.0
    entry_price: float | None = None
    stop_loss_price: float | None = None
    tp1_price: float | None = None
    tp2_price: float | None = None
    risk_pct: float = 0.0
    rejection_reason: str | None = None
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))


class RiskGuard:
    def __init__(self) -> None:
        settings = get_settings()
        self.sizer = PositionSizer(settings.max_risk_per_trade_pct, settings.atr_stop_multiplier)
        self.exposure = ExposureGuard(settings.max_open_positions, settings.max_single_asset_pct)
        self.drawdown = DrawdownCircuit(settings.max_daily_loss_pct, settings.max_drawdown_pct)
        self.cooldown_after_sl_sec = settings.cooldown_after_sl_sec

    def evaluate(self, signal: Signal, state: dict[str, Any] | None = None, snapshot: IndicatorSnapshot | None = None) -> OrderIntent:
        state = state or {}
        signal_uuid = signal.signal_uuid or str(uuid.uuid4())
        
        if signal.direction not in {"BUY", "SELL"}:
            return self._reject(signal, signal_uuid, "NON_ACTIONABLE_SIGNAL")
        
        # 1. Check Drawdown Circuit Breaker
        circuit_reason = self.drawdown.check(
            float(state.get("daily_loss_fraction", state.get("daily_loss_pct", 0.0))),
            float(state.get("drawdown_fraction", state.get("drawdown_pct", 0.0)))
        )
        if circuit_reason:
            return self._reject(signal, signal_uuid, circuit_reason)
        
        # 2. Check Open Position Count Limit
        open_positions_value = state.get("open_positions", 0)
        open_positions = len(open_positions_value) if isinstance(open_positions_value, (list, tuple, set, dict)) else int(open_positions_value)
        exposure_reason = self.exposure.check(open_positions, float(state.get("asset_exposure_fraction", state.get("asset_exposure_pct", 0.0))))
        if exposure_reason:
            return self._reject(signal, signal_uuid, exposure_reason)
        
        # 3. Check Cooldown
        if state.get("stop_loss_at") is not None and time.time() - float(state["stop_loss_at"]) < self.cooldown_after_sl_sec:
            return self._reject(signal, signal_uuid, "STOP_LOSS_COOLDOWN")
        
        # 4. Extract Pricing, ATR, and Equity
# 4. Extract Pricing, ATR, and Equity
        # FIXED: Fallback to the live candle close price if state doesn't have it
        entry = float(state.get("entry_price", snapshot.close if snapshot and hasattr(snapshot, "close") else 0.0))
        atr = float(state.get("atr", snapshot.atr_14 if snapshot and getattr(snapshot, "atr_14", None) is not None else 0.0))
        
        # FIXED: Check multiple possible dictionary keys for your cash balance
        equity = float(state.get("total_equity", state.get("equity", state.get("balance_usdt", 10000.0))))
        
        if equity <= 0 or entry <= 0 or atr <= 0:
            return self._reject(signal, signal_uuid, f"INVALID_SIZING_INPUT: equity={equity}, entry={entry}, atr={atr}")
        
        # 5. Calculate Sizing First
        size = self.sizer.calculate(equity, atr, entry)
        if size.quantity <= 0:
            return self._reject(signal, signal_uuid, "INVALID_SIZING_INPUT")
        
        # 6. Check Single-Asset Exposure Limit
        notional = size.quantity * entry
        if notional > equity * self.exposure.max_single_asset_fraction:
            return self._reject(signal, signal_uuid, "MAX_SINGLE_ASSET_EXPOSURE")
        
        # 7. Compute SL and TP Targets
        stop = calculate_stop_loss(entry, atr, signal.direction, self.sizer.atr_stop_multiplier)
        tp1, tp2 = calculate_targets(entry, stop, signal.direction)
        
        return OrderIntent(True, signal_uuid, signal.symbol, signal.direction, size.quantity, entry, stop, tp1, tp2, size.risk_fraction)

    @staticmethod
    def _reject(signal: Signal, signal_uuid: str, reason: str) -> OrderIntent:
        return OrderIntent(False, signal_uuid, signal.symbol, signal.direction, rejection_reason=reason)