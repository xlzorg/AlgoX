from broker.paper_broker import Fill
from portfolio.position_tracker import PositionTracker

def test_take_profit_execution():
    # 1. ARRANGE: Mock an open LONG position on BTCUSDT
    tracker = PositionTracker()
    tracker.update_fill(
        Fill(
            fill_uuid="entry-fill",
            order_uuid="entry-order",
            signal_uuid="entry-signal",
            symbol="BTCUSDT",
            side="BUY",
            filled_qty=1.0,
            avg_price=58000.0,
            fee=0.0,
        ),
        stop_loss_price=56000.0,
        tp1_price=60000.0,
    )
    
    # 2. ACT: Simulate a live WebSocket tick coming in at $60,500
    exit_signals = tracker.check_exits("BTCUSDT", current_price=60500, timeframe="1h")
    
    # 3. ASSERT: The manager MUST intercept this and fire a market sell
    assert exit_signals, "Position Manager failed to catch the Take Profit"
    assert exit_signals[0].direction == "EXIT"
    assert exit_signals[0].reasoning["exit"] == "TAKE_PROFIT_1"