from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from broker.fee_model import FeeModel
from broker.order_executor import OrderExecutor, PendingOrder
from broker.slippage_model import SlippageModel
from broker.virtual_wallet import VirtualWallet
from risk.risk_guard import OrderIntent


@dataclass(slots=True)
class Fill:
    fill_uuid: str
    order_uuid: str
    signal_uuid: str
    symbol: str
    side: str
    filled_qty: float
    avg_price: float
    fee: float
    fee_asset: str = "USDT"
    slippage_pct: float = 0.0
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass(slots=True)
class PaperOrder:
    order_uuid: str
    signal_uuid: str
    symbol: str
    order_type: str
    side: str
    quantity: float
    limit_price: float | None
    stop_price: float | None
    status: str = "PENDING"
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))


class PaperBroker:
    def __init__(self, wallet: VirtualWallet | None = None) -> None:
        self.wallet = wallet or VirtualWallet()
        self.slippage = SlippageModel()
        self.fees = FeeModel()
        self.executor = OrderExecutor()
        self.orders: dict[str, PaperOrder] = {}
        self.fills: list[Fill] = []

    async def submit(self, intent: OrderIntent, *, price: float | None = None, avg_volume_24h: float = 1_000_000.0, order_type: str = "MARKET") -> Fill | None:
        if not intent.approved or price is None and intent.entry_price is None:
            return None
        order_type = order_type.upper()
        order_uuid = str(uuid.uuid4())
        order = PaperOrder(order_uuid, intent.signal_uuid, intent.symbol, order_type, intent.direction, intent.quantity, intent.entry_price if order_type == "LIMIT" else None, intent.stop_loss_price if order_type == "STOP_MARKET" else None)
        self.orders[order_uuid] = order
        if order_type.upper() != "MARKET":
            self.executor.submit(PendingOrder(order_uuid, order.signal_uuid, order.symbol, order.order_type, order.side, order.quantity, order.limit_price, order.stop_price))
            return None
        return self._fill(order, price or intent.entry_price or 0.0, avg_volume_24h)

    async def submit_order(self, order: dict) -> dict:
        return {**order, "status": "accepted"}

    def process_tick(self, symbol: str, bid: float, ask: float, last_price: float, avg_volume_24h: float = 1_000_000.0) -> list[Fill]:
        fills = []
        for order in self.executor.match(symbol, bid, ask, last_price):
            fills.append(self._fill(self.orders[order.order_uuid], last_price, avg_volume_24h))
        return fills

    def _fill(self, order: PaperOrder, price: float, avg_volume_24h: float) -> Fill:
        fill_price, slippage = self.slippage.apply(price, order.side, order.order_type, order.quantity, avg_volume_24h)
        fee = self.fees.calculate(order.quantity * fill_price, order.order_type)
        self.wallet.apply_fill(order.symbol, order.side, order.quantity, fill_price, fee)
        order.status = "FILLED"
        fill = Fill(str(uuid.uuid4()), order.order_uuid, order.signal_uuid, order.symbol, order.side, order.quantity, fill_price, fee, slippage_pct=slippage)
        self.fills.append(fill)
        return fill
