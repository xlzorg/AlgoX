from __future__ import annotations

from broker.paper_broker import Fill
from broker.virtual_wallet import VirtualWallet
from portfolio.performance import Performance
from portfolio.position_tracker import Position, PositionTracker
from portfolio.trade_journal import PortfolioTradeJournal
from logs.file_logger import get_file_logger


class PortfolioManager:
    def __init__(self, wallet: VirtualWallet | None = None) -> None:
        self.wallet = wallet or VirtualWallet()
        self.position_tracker = PositionTracker()
        self.performance = Performance(self.wallet, self.position_tracker)
        self.journal = PortfolioTradeJournal()
        self.prices: dict[str, float] = {}
        self.realized_pnl_total = 0.0
        self._file_logger = get_file_logger("portofolio_manager")

    def update(self, fill: Fill, *, stop_loss_price: float | None = None, tp1_price: float | None = None, tp2_price: float | None = None) -> Position:
        self.prices[fill.symbol] = fill.avg_price
        position = self.position_tracker.update_fill(
            fill,
            stop_loss_price=stop_loss_price,
            tp1_price=tp1_price,
            tp2_price=tp2_price,
        )
        if position.status == "CLOSED" and position.realized_pnl is not None:
            self.realized_pnl_total += position.realized_pnl
        return position

    def check_exits(self, symbol: str, current_price: float, timeframe: str = "", high: float | None = None, low: float | None = None,):
        self._file_logger.info(
            "CHECK EXITS PORTOFOLIO MANAGER TRIGGERED"
        )
        return self.position_tracker.check_exits(symbol, current_price, timeframe, high=high, low=low,)

    def mark_price(self, symbol: str, price: float) -> None:
        self.prices[symbol] = price
        self.position_tracker.mark_price(symbol, price)

    def snapshot(self) -> object:
        return self.performance.snapshot(self.prices)
    
    # in VirtualWallet or PortfolioManager
    def restore_from_snapshot(self, cash: float, realized_pnl: float = 0.0) -> None:
        self.cash = cash
        # if you track realized_pnl_total on PortfolioManager:
        self.realized_pnl_total = realized_pnl

    def summary(self) -> dict:
        open_positions = self.position_tracker.open_positions()
        unrealized = sum(item.unrealized_pnl for item in open_positions)
        # Position market value = cost basis + unrealized PnL
        position_market_value = sum(item.entry_price * item.quantity + item.unrealized_pnl for item in open_positions)
        
        return {
            "balance_usdt": self.wallet.cash,
            "total_equity": self.wallet.cash + position_market_value,
            "open_positions": len(open_positions),
            "unrealized_pnl": unrealized,
            "realized_pnl_today": self.realized_pnl_total,
            "realized_pnl_total": self.realized_pnl_total,
        }