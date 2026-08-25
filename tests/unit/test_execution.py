import pytest
import uuid

from strategy.base_strategy import Signal
from indicators.base_indicator import IndicatorSnapshot
from risk.risk_guard import RiskGuard, OrderIntent
from broker.paper_broker import PaperBroker
from portfolio.portfolio_manager import PortfolioManager

# Tell pytest that these tests use async/await
pytestmark = pytest.mark.asyncio

class MockSnapshot(IndicatorSnapshot):
    """Simulates an IndicatorSnapshot for the RiskGuard to read."""
    def __init__(self, **kwargs):
        self.symbol = "BTCUSDT"
        self.timeframe = "1h"
        self.candle_time = 1600000000
        self.atr_14 = 500.0  # RiskGuard usually needs ATR to calculate Stop Loss!
        for k, v in kwargs.items():
            setattr(self, k, v)

@pytest.fixture
def setup_env():
    """Spins up a fresh RiskGuard, Broker, and Portfolio for each test."""
    broker = PaperBroker()
    
    # Inject 10,000 USDT so the RiskGuard doesn't reject us for INSUFFICIENT_FUNDS
    if hasattr(broker, 'wallet') and hasattr(broker.wallet, 'balances'):
        broker.wallet.balances["USDT"] = 10000.0
        
    portfolio = PortfolioManager(broker.wallet)
    risk_guard = RiskGuard()
    
    return broker, portfolio, risk_guard


async def test_buy_signal_opens_position(setup_env):
    """Test 1: Does a BUY signal successfully flow through the RiskGuard and open a position?"""
    broker, portfolio, risk_guard = setup_env
    
    # 1. The Strategy Engine emits a strong BUY signal
    signal = Signal(
        symbol="BTCUSDT", timeframe="1h", direction="BUY",
        confidence=0.85, strategy_id="composite", signal_uuid=str(uuid.uuid4())
    )
    snapshot = MockSnapshot()
    
    # 2. The RiskGuard evaluates the signal against our portfolio
    portfolio_state = {
        "entry_price": 50000.0,
        "atr": snapshot.atr_14,
        "balance_usdt": 10000.0,
        "open_positions": 0
    }
    intent = risk_guard.evaluate(signal, portfolio_state, snapshot)
    
    # Verify the RiskGuard approved the trade
    assert intent.approved is True, f"RiskGuard rejected the trade: {intent.rejection_reason}"
    assert intent.quantity > 0, "RiskGuard calculated a position size of 0"
    
    # 3. The Paper Broker simulates the exchange execution
    fill = await broker.submit(intent, price=50000.0)
    assert fill is not None, "Broker failed to generate a fill"
    
    # 4. The Portfolio Manager tracks the new asset
    portfolio.update(
        fill, stop_loss_price=intent.stop_loss_price,
        tp1_price=intent.tp1_price, tp2_price=intent.tp2_price
    )
    
    # Verify the position is officially open in our tracker
    open_positions = portfolio.position_tracker.open_positions()
    assert len(open_positions) == 1, "Position was not tracked by PortfolioManager!"
    assert open_positions[0].side == "LONG", "Expected a LONG position"
# Verify the entry price is 50000 with up to 0.1% slippage allowance
    assert open_positions[0].entry_price == pytest.approx(50000.0, rel=0.001)

async def test_exit_signal_closes_position(setup_env):
    """Test 2: Does an EXIT intent successfully close an existing position?"""
    broker, portfolio, risk_guard = setup_env
    
    # --- SETUP: Manually inject an open LONG position ---
    entry_intent = OrderIntent(
        approved=True, signal_uuid=str(uuid.uuid4()), symbol="BTCUSDT",
        direction="BUY", quantity=0.1, entry_price=50000.0
    )
    entry_fill = await broker.submit(entry_intent, price=50000.0)
    portfolio.update(entry_fill)
    
    # Verify we are holding the asset
    open_positions = portfolio.position_tracker.open_positions()
    assert len(open_positions) == 1
    current_position = open_positions[0]
    
    # --- ACTION: Simulate the Trading Engine firing an EXIT Market Order ---
    exit_intent = OrderIntent(
        approved=True,
        signal_uuid=str(uuid.uuid4()),
        symbol="BTCUSDT",
        direction="SELL",  # To close a LONG position, we execute a SELL order
        quantity=current_position.quantity,
        entry_price=48000.0
    )
    
    exit_fill = await broker.submit(exit_intent, price=48000.0, order_type="MARKET")
    portfolio.update(exit_fill)
    
    # --- ASSERTION ---
    # Verify the position is no longer active
    assert len(portfolio.position_tracker.open_positions()) == 0, "Position is still open!"
    
    # Verify it was successfully moved to the archive with the correct exit price
    closed_positions = [p for p in portfolio.position_tracker.positions() if p.status == "CLOSED"]
    assert len(closed_positions) == 1, "Position was not moved to CLOSED status"
# Verify the exit price is 48000 with up to 0.1% slippage allowance
    assert closed_positions[0].exit_price == pytest.approx(48000.0, rel=0.001)