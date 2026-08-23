from __future__ import annotations

import uuid
from dataclasses import dataclass

from broker.paper_broker import Fill
from strategy.base_strategy import Signal


@dataclass(slots=True)
class Position:
    position_uuid: str
    symbol: str
    side: str
    quantity: float
    entry_price: float
    entry_fill_uuid: str
    entry_signal_uuid: str
    entry_time: int
    current_price: float | None = None
    exit_price: float | None = None
    exit_fill_uuid: str | None = None
    realized_pnl: float | None = None
    total_fees: float = 0.0
    status: str = "OPEN"
    stop_loss_price: float | None = None
    tp1_price: float | None = None
    tp2_price: float | None = None

    @property
    def unrealized_pnl(self) -> float:
        if self.current_price is None:
            return 0.0
        direction = 1 if self.side == "LONG" else -1
        return (self.current_price - self.entry_price) * self.quantity * direction

    @property
    def pnl_pct(self) -> float:
        denominator = self.entry_price * self.quantity
        return self.unrealized_pnl / denominator * 100 if denominator else 0.0


class PositionTracker:
    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}
        self.closed: list[Position] = []

    def update_fill(self, fill: Fill, *, stop_loss_price: float | None = None, tp1_price: float | None = None, tp2_price: float | None = None) -> Position:
        existing = next((item for item in self.open_positions() if item.symbol == fill.symbol), None)
        incoming_side = "LONG" if fill.side.upper() == "BUY" else "SHORT"
        if existing and existing.side != incoming_side:
            existing.exit_price = fill.avg_price
            existing.exit_fill_uuid = fill.fill_uuid
            direction = 1 if existing.side == "LONG" else -1
            existing.realized_pnl = (fill.avg_price - existing.entry_price) * existing.quantity * direction - existing.total_fees - fill.fee
            existing.total_fees += fill.fee
            existing.status = "CLOSED"
            self.closed.append(existing)
            return existing
        position = Position(
            str(uuid.uuid4()), fill.symbol, incoming_side, fill.filled_qty,
            fill.avg_price, fill.fill_uuid, fill.signal_uuid, fill.timestamp,
            fill.avg_price, total_fees=fill.fee,
            stop_loss_price=stop_loss_price, tp1_price=tp1_price, tp2_price=tp2_price,
        )
        self._positions[position.position_uuid] = position
        return position

    def check_exits(self, symbol: str, current_price: float, timeframe: str = "") -> list[Signal]:
        signals: list[Signal] = []
        for position in self.open_positions():
            if position.symbol != symbol:
                continue
            position.current_price = current_price
            hit_stop = position.stop_loss_price is not None and (
                (position.side == "LONG" and current_price <= position.stop_loss_price)
                or (position.side == "SHORT" and current_price >= position.stop_loss_price)
            )
            hit_target = position.tp1_price is not None and (
                (position.side == "LONG" and current_price >= position.tp1_price)
                or (position.side == "SHORT" and current_price <= position.tp1_price)
            )
            if hit_stop or hit_target:
                reason = "STOP_LOSS" if hit_stop else "TAKE_PROFIT_1"
                signals.append(Signal(
                    symbol=position.symbol,
                    timeframe=timeframe,
                    direction="EXIT",
                    confidence=1.0,
                    reasoning={"exit": reason, "position_uuid": position.position_uuid},
                    strategy_id="position_manager",
                    timestamp=position.entry_time,
                ))
        return signals

    def mark_price(self, symbol: str, price: float) -> None:
        for position in self.open_positions():
            if position.symbol == symbol:
                position.current_price = price

    def open_positions(self) -> list[Position]:
        return [item for item in self._positions.values() if item.status == "OPEN"]

    def positions(self) -> list[Position]:
        return list(self._positions.values())
