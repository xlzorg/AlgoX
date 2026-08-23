from strategy.base_strategy import BaseStrategy, Signal
from strategy.composite import CompositeStrategy
from indicators.base_indicator import IndicatorSnapshot
from tests.backtest.runner import BacktestRunner


class FixedStrategy(BaseStrategy):
    def __init__(self, strategy_id: str, direction: str, confidence: float) -> None:
        self.strategy_id = strategy_id
        self.direction = direction
        self.confidence = confidence

    def evaluate(self, snapshot: IndicatorSnapshot) -> Signal:
        return Signal(snapshot.symbol, snapshot.timeframe, self.direction, self.confidence, strategy_id=self.strategy_id)


def make_snapshot(**kwargs) -> IndicatorSnapshot:
    values = {"symbol": "BTCUSDT", "timeframe": "5m", "candle_time": 1, "vwap": 110, "ema_50": 100}
    values.update(kwargs)
    return IndicatorSnapshot(**values)


def test_ltf_buy_requires_htf_bullish_bias() -> None:
    strategy = CompositeStrategy([FixedStrategy("trend_following", "BUY", 1.0), FixedStrategy("mean_reversion", "BUY", 1.0), FixedStrategy("breakout", "BUY", 1.0)])
    bullish = strategy.evaluate({"1h": make_snapshot(timeframe="1h", vwap=110, ema_50=100), "5m": make_snapshot()})
    bearish = strategy.evaluate({"1h": make_snapshot(timeframe="1h", vwap=90, ema_50=100), "5m": make_snapshot()})
    assert bullish.direction == "BUY"
    assert bullish.reasoning["confluence_ok"] is True
    assert bearish.direction == "HOLD"
    assert bearish.reasoning["confluence_ok"] is False


def test_backtest_runner_processes_candles_offline() -> None:
    candles = [
        {
            "open_time": index,
            "open": 100 + index * 0.1,
            "high": 101 + index * 0.1,
            "low": 99 + index * 0.1,
            "close": 100 + index * 0.1,
            "volume": 100,
        }
        for index in range(220)
    ]
    runner = BacktestRunner()
    from data.normalizer import Candle
    result = runner.run_sync([Candle(symbol="BTCUSDT", timeframe="1h", quote_volume=row["close"] * row["volume"], is_closed=True, **row) for row in candles])
    assert result["candles_processed"] == 220
    assert result["candles_per_sec"] > 0
    assert result["equity_points"] >= 0
