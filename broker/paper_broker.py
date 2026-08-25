from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from broker.fee_model import FeeModel
from broker.order_executor import OrderExecutor, PendingOrder
from broker.slippage_model import SlippageModel
from broker.virtual_wallet import VirtualWallet
from risk.risk_guard import OrderIntent
from logs.file_logger import get_file_logger


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
        self._file_logger = get_file_logger("paper_broker")

    async def submit(self, intent: OrderIntent, *, price: float | None = None, avg_volume_24h: float = 1_000_000.0, order_type: str = "MARKET") -> Fill | None:
        self._file_logger.info("=== PaperBroker.submit ===")
        self._file_logger.info("approved=%s | price=%s | entry_price=%s | order_type=%s | direction=%s | qty=%s", intent.approved, price, intent.entry_price, order_type, intent.direction, intent.quantity,)
        if not intent.approved or price is None and intent.entry_price is None:
            self._file_logger.info("→ GUARD CLAUSE triggered → returning None")
            return None
        order_type = order_type.upper()
        self._file_logger.info("order_type after upper() = %s", order_type)
        order_uuid = str(uuid.uuid4())
        order = PaperOrder(order_uuid, intent.signal_uuid, intent.symbol, order_type, intent.direction, intent.quantity, intent.entry_price if order_type == "LIMIT" else None, intent.stop_loss_price if order_type == "STOP_MARKET" else None)
        self.orders[order_uuid] = order
        if order_type.upper() != "MARKET":
            self._file_logger.info("→ Not MARKET → sending to executor and returning None")
            self.executor.submit(PendingOrder(order_uuid, order.signal_uuid, order.symbol, order.order_type, order.side, order.quantity, order.limit_price, order.stop_price))
            return None

        self._file_logger.info("→ Calling _fill() ...")
        try:
            fill = self._fill(order, price or intent.entry_price or 0.0, avg_volume_24h)
            self._file_logger.info("→ _fill returned fill_uuid=%s", getattr(fill, "fill_uuid", None))
            return fill
        except Exception as e:
            self._file_logger.exception("→ EXCEPTION inside _fill: %s", e)
            raise
        

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
