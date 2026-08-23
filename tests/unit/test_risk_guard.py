from risk.risk_guard import RiskGuard
from strategy.base_strategy import Signal

def test_drawdown_circuit_breaker():
    guard = RiskGuard()
    
    # 1. ARRANGE: A valid 90% confidence BUY signal, but a wrecked portfolio
    valid_signal = Signal(
        symbol="BTCUSDT",
        timeframe="1h",
        direction="BUY",
        confidence=0.90,
        strategy_id="trend_following",
    )
    
    ruined_portfolio = {
        "equity": 8500.0,
        "drawdown_fraction": 0.15,
    }
    
    # 2. ACT: Ask the RiskGuard for permission to trade
    intent = guard.evaluate(valid_signal, ruined_portfolio)
    
    # 3. ASSERT: The RiskGuard MUST reject the order to protect capital
    assert intent.approved is False, "RiskGuard dangerously approved a trade during a severe drawdown"
    assert "DRAWDOWN" in intent.rejection_reason.upper(), "Wrong rejection reason given"