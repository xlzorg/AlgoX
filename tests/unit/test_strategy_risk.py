from indicators.base_indicator import IndicatorSnapshot
from risk.risk_guard import RiskGuard
from strategy.base_strategy import BaseStrategy, Signal
from strategy.composite import CompositeStrategy


class FixedStrategy(BaseStrategy):
    def __init__(self, strategy_id: str, confidence: float, direction: str = "BUY") -> None:
        self.strategy_id = strategy_id
        self.confidence = confidence
        self.direction = direction

    def evaluate(self, snapshot: IndicatorSnapshot) -> Signal:
        return Signal(snapshot.symbol, snapshot.timeframe, self.direction, self.confidence, strategy_id=self.strategy_id)


class FixedRegime:
    def __init__(self, regime: str) -> None:
        self.regime = regime

    def detect(self, snapshot: IndicatorSnapshot) -> str:
        return self.regime


def snapshot(**overrides: float | str | None) -> IndicatorSnapshot:
    values = {
        "symbol": "BTCUSDT", "timeframe": "1h", "candle_time": 1,
        "exchange_netflow": -10.0,
    }
    values.update(overrides)
    return IndicatorSnapshot(**values)


def test_composite_applies_reference_weights_and_onchain_modifier() -> None:
    strategy = CompositeStrategy(
        [FixedStrategy("trend_following", 1.0), FixedStrategy("mean_reversion", 0.4), FixedStrategy("breakout", 0.2)],
        FixedRegime("TRENDING_UP"),
    )
    result = strategy.evaluate(snapshot())
    assert result.direction == "BUY"
    assert result.confidence == 0.40 + 0.25 * 0.4 + 0.25 * 0.2 + 0.10


def test_composite_suppresses_trend_weight_in_ranging_regime() -> None:
    strategy = CompositeStrategy(
        [FixedStrategy("trend_following", 1.0), FixedStrategy("mean_reversion", 0.0), FixedStrategy("breakout", 0.0)],
        FixedRegime("RANGING"),
    )
    result = strategy.evaluate(snapshot(exchange_netflow=None))
    assert result.confidence == 0.20
    assert result.direction == "SELL"


def test_risk_guard_rejects_circuit_breakers_and_exposure() -> None:
    guard = RiskGuard()
    signal = Signal("BTCUSDT", "1h", "BUY", 0.9)
    assert guard.evaluate(signal, {"daily_loss_fraction": 0.03}).rejection_reason == "MAX_DAILY_LOSS"
    assert guard.evaluate(signal, {"drawdown_fraction": 0.10}).rejection_reason == "MAX_DRAWDOWN"
    assert guard.evaluate(signal, {"open_positions": 5}).rejection_reason == "MAX_OPEN_POSITIONS"
    assert guard.evaluate(signal, {"asset_exposure_fraction": 0.20}).rejection_reason == "MAX_SINGLE_ASSET_EXPOSURE"


def test_risk_guard_caps_half_kelly_at_one_percent() -> None:
    guard = RiskGuard()
    signal = Signal("BTCUSDT", "1h", "BUY", 0.9)
    intent = guard.evaluate(signal, {"equity": 10_000, "entry_price": 100, "atr": 2})
    assert intent.approved
    assert intent.risk_pct == 0.01
    assert intent.stop_loss_price == 97.0
    assert intent.tp1_price == 104.5
    assert intent.tp2_price == 107.5
