from __future__ import annotations

import time
import uuid
import logging
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

logger = logging.getLogger(__name__)


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

        self.sizer = PositionSizer(
            max_risk_fraction=settings.max_risk_per_trade_pct,
            atr_stop_multiplier=settings.atr_stop_multiplier,
            max_single_asset_fraction=settings.max_single_asset_pct,
        )
        self.exposure = ExposureGuard(
            max_positions=settings.max_open_positions,
            max_single_asset_fraction=settings.max_single_asset_pct,
        )
        self.drawdown = DrawdownCircuit(
            settings.max_daily_loss_pct,
            settings.max_drawdown_pct,
        )
        self.cooldown_after_sl_sec = settings.cooldown_after_sl_sec
        
        # --- IMPROVEMENT: Internal State Tracking ---
        # We track these internally so the guard works even if the PortfolioManager 
        # forgets to pass the exact values in the state dict.
        self._peak_equity: float = 0.0
        self._sl_cooldowns: dict[str, float] = {}

    def record_stop_loss(self, symbol: str) -> None:
        """Lock trading for a specific asset after a stop-loss is hit."""
        self._sl_cooldowns[symbol] = time.time()
        logger.info("Cooldown activated for %s: Locked for %d seconds", symbol, self.cooldown_after_sl_sec)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def evaluate(
        self,
        signal: Signal,
        state: dict[str, Any] | None = None,
        snapshot: IndicatorSnapshot | None = None,
    ) -> OrderIntent:
        state = state or {}
        signal_uuid = signal.signal_uuid or str(uuid.uuid4())

        # ── Gate 0: only act on actionable signals ─────────────────────
        if signal.direction not in {"BUY", "SELL"}:
            return self._reject(signal, signal_uuid, "NON_ACTIONABLE_SIGNAL")

        # Resolve equity early for the drawdown check
        equity = self._resolve_equity(state)

        # ── Gate 1: drawdown circuit breaker ───────────────────────────
        # IMPROVEMENT: Dynamically track peak equity internally
        if equity > self._peak_equity:
            self._peak_equity = equity
            
        computed_drawdown = 0.0
        if self._peak_equity > 0:
            computed_drawdown = (self._peak_equity - equity) / self._peak_equity

        circuit_reason = self.drawdown.check(
            float(state.get("daily_loss_fraction", state.get("daily_loss_pct", 0.0))),
            float(state.get("drawdown_fraction",   state.get("drawdown_pct", computed_drawdown))),
        )
        if circuit_reason:
            return self._reject(signal, signal_uuid, circuit_reason)

        # ── Gate 2: open position count ────────────────────────────────
        raw_positions = state.get("open_positions", 0)
        open_positions = (
            len(raw_positions)
            if isinstance(raw_positions, (list, tuple, set, dict))
            else int(raw_positions)
        )
        if open_positions >= self.exposure.max_positions:
            return self._reject(signal, signal_uuid, "MAX_OPEN_POSITIONS")

        # ── Gate 3: stop-loss cooldown ─────────────────────────────────
        # IMPROVEMENT: Check both the passed state AND our internal tracker
        sl_at = state.get("stop_loss_at", self._sl_cooldowns.get(signal.symbol, 0.0))
        if sl_at and (time.time() - float(sl_at)) < self.cooldown_after_sl_sec:
            return self._reject(signal, signal_uuid, "STOP_LOSS_COOLDOWN")

        # ── Step 4: resolve entry price ────────────────────────────────
        entry = self._resolve_entry(state, snapshot)
        if entry <= 0:
            return self._reject(signal, signal_uuid, "INVALID_ENTRY_PRICE")

        # ── Step 5: resolve ATR ────────────────────────────────────────
        atr = self._resolve_atr(state, snapshot)
        if atr <= 0:
            return self._reject(signal, signal_uuid, "INVALID_ATR")

        # ── Step 6: resolve equity (cash balance) ──────────────────────
        if equity <= 0:
            return self._reject(signal, signal_uuid, "INVALID_EQUITY")

        # ── Step 7: compute position size (capped by both risk + exposure) ──
        size = self.sizer.calculate(equity, atr, entry)
        if size.quantity <= 0:
            return self._reject(signal, signal_uuid, "ZERO_QUANTITY")

        # ── Step 8: verify available cash covers the notional cost ─────
        if signal.direction == "BUY" and size.notional > equity:
            fee_buffer = 1.0015
            affordable_qty = equity / (entry * fee_buffer)
            if affordable_qty <= 0:
                return self._reject(signal, signal_uuid, "INSUFFICIENT_BALANCE")
            quantity = min(size.quantity, affordable_qty)
            notional = quantity * entry
        else:
            quantity = size.quantity
            notional = size.notional

        # ── Step 9: compute stop loss and take profit ───────────────────
        stop = calculate_stop_loss(entry, atr, signal.direction, self.sizer.atr_stop_multiplier)
        tp1, tp2 = calculate_targets(entry, stop, signal.direction)

        return OrderIntent(
            approved=True,
            signal_uuid=signal_uuid,
            symbol=signal.symbol,
            direction=signal.direction,
            quantity=quantity,
            entry_price=entry,
            stop_loss_price=stop,
            tp1_price=tp1,
            tp2_price=tp2,
            risk_pct=size.risk_fraction,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_entry(state: dict, snapshot: IndicatorSnapshot | None) -> float:
        v = state.get("entry_price")
        if v is not None and float(v) > 0:
            return float(v)
        if snapshot is not None:
            close = getattr(snapshot, "close", None)
            if close is not None and float(close) > 0:
                return float(close)
        return 0.0

    @staticmethod
    def _resolve_atr(state: dict, snapshot: IndicatorSnapshot | None) -> float:
        v = state.get("atr")
        if v is not None and float(v) > 0:
            return float(v)
        if snapshot is not None:
            atr = getattr(snapshot, "atr_14", None)
            if atr is not None and float(atr) > 0:
                return float(atr)
        return 0.0

    @staticmethod
    def _resolve_equity(state: dict) -> float:
        for key in ("balance_usdt", "equity", "total_equity"):
            v = state.get(key)
            if v is not None:
                f = float(v)
                if f > 0:
                    return f
        return 0.0

    @staticmethod
    def _reject(signal: Signal, signal_uuid: str, reason: str) -> OrderIntent:
        return OrderIntent(
            approved=False,
            signal_uuid=signal_uuid,
            symbol=signal.symbol,
            direction=signal.direction,
            rejection_reason=reason,
        )