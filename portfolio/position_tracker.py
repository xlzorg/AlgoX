from __future__ import annotations

import uuid
from dataclasses import dataclass

from broker.paper_broker import Fill
from strategy.base_strategy import Signal
import time
import uuid
from logs.file_logger import get_file_logger


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
        self._file_logger = get_file_logger("position_tracker")


    def update_fill(self, fill: Fill, *, stop_loss_price: float | None = None, tp1_price: float | None = None, tp2_price: float | None = None) -> Position:
        existing = next((item for item in self.open_positions() if item.symbol == fill.symbol), None)
        incoming_side = "LONG" if fill.side.upper() == "BUY" else "SHORT"
        if existing and existing.side != incoming_side:
            existing.exit_price = fill.avg_price
            existing.exit_fill_uuid = fill.fill_uuid
            direction = 1 if existing.side == "LONG" else -1
            existing.realized_pnl = (
                (fill.avg_price - existing.entry_price) * existing.quantity * direction
                - existing.total_fees - fill.fee
            )
            existing.total_fees += fill.fee
            existing.status = "CLOSED"
            self.closed.append(existing)
            # IMPORTANT: remove from active map
            self._positions.pop(existing.position_uuid, None)
            return existing
        position = Position(
            str(uuid.uuid4()), fill.symbol, incoming_side, fill.filled_qty,
            fill.avg_price, fill.fill_uuid, fill.signal_uuid, fill.timestamp,
            fill.avg_price, total_fees=fill.fee,
            stop_loss_price=stop_loss_price, tp1_price=tp1_price, tp2_price=tp2_price,
        )
        self._positions[position.position_uuid] = position
        self._file_logger.info(
            "NEW POSITION %s %s | SL=%s TP1=%s TP2=%s",
            position.symbol, position.side,
            position.stop_loss_price, position.tp1_price, position.tp2_price,
        )
        return position

    def check_exits(
        self,
        symbol: str,
        current_price: float,
        timeframe: str = "",
        high: float | None = None,
        low: float | None = None,
        is_raw_tick: bool = False,
    ) -> list[Signal]:
        signals: list[Signal] = []
        if is_raw_tick:
            # Hanya pakai harga tick, jangan andalkan high/low
            px_high = current_price
            px_low = current_price
        else:
            px_high = high if high is not None else current_price
            px_low = low if low is not None else current_price

        for position in self.open_positions():
            if position.symbol != symbol:
                continue
            position.current_price = current_price

            hit_stop = position.stop_loss_price is not None and (
                (position.side == "LONG" and px_low <= position.stop_loss_price)
                or (position.side == "SHORT" and px_high >= position.stop_loss_price)
            )
            hit_tp1 = position.tp1_price is not None and (
                (position.side == "LONG" and px_high >= position.tp1_price)
                or (position.side == "SHORT" and px_low <= position.tp1_price)
            )
            hit_tp2 = position.tp2_price is not None and (
                (position.side == "LONG" and px_high >= position.tp2_price)
                or (position.side == "SHORT" and px_low <= position.tp2_price)
            )

            self._file_logger.info(
                "CHECK %s %s | price=%.2f high=%.2f low=%.2f | SL=%.2f | TP1=%.2f | TP2=%.2f | hit_SL=%s | hit_TP1=%s | hit_TP2=%s | open=%d",
                position.symbol, position.side, current_price,
                px_high, px_low,
                position.stop_loss_price or 0,
                position.tp1_price or 0,
                position.tp2_price or 0,
                hit_stop, hit_tp1, hit_tp2,
                len(self.open_positions()),
            )

            if hit_stop or hit_tp1 or hit_tp2:
                if hit_stop:
                    reason = "STOP_LOSS"
                elif hit_tp2:
                    reason = "TAKE_PROFIT_2"
                else:
                    reason = "TAKE_PROFIT_1"

                signals.append(Signal(
                    symbol=position.symbol,
                    timeframe=timeframe,
                    direction="EXIT",
                    confidence=1.0,
                    reasoning={"exit": reason, "position_uuid": position.position_uuid},
                    strategy_id="position_manager",
                    signal_uuid=str(uuid.uuid4()),          # ← force new UUID
                    timestamp=int(time.time() * 1000),      # ← use current time, not entry_time
                ))
                self._file_logger.info(
                    "EXIT TRIGGERED %s %s reason=%s price=%.2f SL=%s TP1=%s TP2=%s",
                    position.symbol, position.side, reason, current_price,
                    position.stop_loss_price, position.tp1_price, position.tp2_price,
                )
        return signals

    def mark_price(self, symbol: str, price: float) -> None:
        for position in self.open_positions():
            if position.symbol == symbol:
                position.current_price = price

    def open_positions(self) -> list[Position]:
        return [item for item in self._positions.values() if item.status == "OPEN"]

    def positions(self) -> list[Position]:
        return list(self._positions.values())

    def restore_positions(self, rows: list) -> None:
        """Load open positions from DB rows back into memory."""
        self._positions.clear()
        self.closed.clear()          # optional – only if you also restore closed ones later

        for row in rows:
            # Adjust field names if your PositionRow uses different ones
            pos = Position(
                position_uuid=row.position_uuid,
                symbol=row.symbol,
                side=row.side,
                quantity=row.quantity,
                entry_price=row.entry_price,
                entry_fill_uuid=row.entry_fill_uuid,
                entry_signal_uuid=getattr(row, "entry_signal_uuid", "") or "",
                entry_time=row.entry_time,
                current_price=row.entry_price,          # will be updated on first tick
                exit_price=row.exit_price,
                exit_fill_uuid=row.exit_fill_uuid,
                realized_pnl=row.realized_pnl,
                total_fees=row.total_fees or 0.0,
                status=row.status,
                stop_loss_price=getattr(row, "stop_loss_price", None),
                tp1_price=getattr(row, "tp1_price", None),
                tp2_price=getattr(row, "tp2_price", None),
            )
            if pos.status == "OPEN":
                self._positions[pos.position_uuid] = pos
            else:
                self.closed.append(pos)

        self._file_logger.info(
            "Restored %d open positions from DB", len(self.open_positions())
        )
