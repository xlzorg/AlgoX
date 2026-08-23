import asyncio

from broker.fee_model import FeeModel
from broker.order_executor import OrderExecutor, PendingOrder
from broker.paper_broker import PaperBroker
from broker.slippage_model import calculate_slippage
from portfolio.portfolio_manager import PortfolioManager
from risk.risk_guard import OrderIntent


def test_fee_model_uses_maker_and_taker_rates() -> None:
    fees = FeeModel()
    assert fees.calculate(1000, "MARKET") == 1.0
    assert fees.calculate(1000, "LIMIT") == 0.8


def test_market_slippage_includes_impact_and_is_bounded_by_inputs() -> None:
    slippage = calculate_slippage("MARKET", 10, 1000, noise_std=0.0)
    assert slippage == 0.001
    assert calculate_slippage("LIMIT", 10, 1000, noise_std=0.0) == 0.0


def test_limit_and_stop_orders_match_live_prices() -> None:
    executor = OrderExecutor()
    limit = PendingOrder("limit", "sig", "BTCUSDT", "LIMIT", "BUY", 1, limit_price=100)
    stop = PendingOrder("stop", "sig", "BTCUSDT", "STOP_MARKET", "SELL", 1, stop_price=95)
    executor.submit(limit)
    executor.submit(stop)
    assert [item.order_uuid for item in executor.match("BTCUSDT", 99, 100, 100)] == ["limit"]
    assert [item.order_uuid for item in executor.match("BTCUSDT", 94, 95, 94)] == ["stop"]


def test_portfolio_closes_position_and_calculates_pnl() -> None:
    async def scenario() -> None:
        broker = PaperBroker()
        manager = PortfolioManager(broker.wallet)
        entry = await broker.submit(OrderIntent(True, "sig-buy", "BTCUSDT", "BUY", 1, 100), price=100, avg_volume_24h=1_000_000)
        exit_intent = OrderIntent(True, "sig-sell", "BTCUSDT", "SELL", 1, 110)
        exit_fill = await broker.submit(exit_intent, price=110, avg_volume_24h=1_000_000)
        manager.update(entry)
        closed = manager.update(exit_fill)
        assert closed.status == "CLOSED"
        assert closed.realized_pnl > 9
        assert manager.summary()["open_positions"] == 0

    asyncio.run(scenario())
