from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PendingOrder:
    order_uuid: str
    signal_uuid: str
    symbol: str
    order_type: str
    side: str
    quantity: float
    limit_price: float | None = None
    stop_price: float | None = None


class OrderExecutor:
    def __init__(self) -> None:
        self.pending: dict[str, PendingOrder] = {}

    def submit(self, order: PendingOrder) -> None:
        self.pending[order.order_uuid] = order

    def match(self, symbol: str, bid: float, ask: float, last_price: float) -> list[PendingOrder]:
        matched: list[PendingOrder] = []
        for order in list(self.pending.values()):
            if order.symbol != symbol:
                continue
            price = ask if order.side.upper() == "BUY" else bid
            if order.order_type.upper() == "LIMIT":
                filled = price <= order.limit_price if order.side.upper() == "BUY" else price >= order.limit_price
            elif order.order_type.upper() == "STOP_MARKET":
                filled = last_price >= order.stop_price if order.side.upper() == "BUY" else last_price <= order.stop_price
            else:
                filled = True
            if filled:
                matched.append(order)
                self.pending.pop(order.order_uuid, None)
        return matched
