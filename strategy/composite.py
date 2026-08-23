from collections.abc import Mapping, Sequence

from indicators.base_indicator import IndicatorSnapshot
from strategy.base_strategy import BaseStrategy, Signal
from strategy.regime_detector import RegimeDetector

class CompositeStrategy(BaseStrategy):
    strategy_id = "composite"

    def __init__(self, strategies: list[BaseStrategy], regime_detector: RegimeDetector | None = None, *, htf_timeframes: tuple[str, ...] = ("1h", "4h")) -> None:
        self.strategies = strategies
        self.regime_detector = regime_detector or RegimeDetector()
        self.htf_timeframes = htf_timeframes
        self.strategy_weights = {"trend_following": 0.40, "mean_reversion": 0.25, "breakout": 0.25}

    def adjust_strategy_weight(self, strategy_id: str, multiplier: float) -> None:
        if strategy_id in self.strategy_weights:
            self.strategy_weights[strategy_id] = max(0.0, min(1.0, self.strategy_weights[strategy_id] * multiplier))

    def evaluate(self, snapshot: IndicatorSnapshot | Mapping[str, IndicatorSnapshot] | Sequence[IndicatorSnapshot]) -> Signal:
        snapshots = self._snapshots(snapshot)
        ltf = snapshots.get("5m") or snapshots.get("1m") or next(iter(snapshots.values()))
        htf = next((item for timeframe, item in snapshots.items() if timeframe in self.htf_timeframes), ltf)
        has_distinct_htf = htf is not ltf
        signals = {strategy.strategy_id: strategy.evaluate(ltf) for strategy in self.strategies}
        regime = self.regime_detector.detect(htf)
        trend = signals.get("trend_following", Signal(ltf.symbol, ltf.timeframe, "HOLD", 0.0))
        reversion = signals.get("mean_reversion", Signal(ltf.symbol, ltf.timeframe, "HOLD", 0.0))
        breakout = signals.get("breakout", Signal(ltf.symbol, ltf.timeframe, "HOLD", 0.0))
        trend_weight = self.strategy_weights["trend_following"] * (0.5 if regime == "RANGING" else 1.0)
        score = trend.confidence * trend_weight + reversion.confidence * self.strategy_weights["mean_reversion"] + breakout.confidence * self.strategy_weights["breakout"]
        if ltf.exchange_netflow is not None:
            score += 0.10 if ltf.exchange_netflow < 0 else 0.0
        direction = "BUY" if score >= 0.65 else "SELL" if score <= 0.35 else "HOLD"
        htf_bullish = self._htf_bias(htf) == "BUY"
        htf_bearish = self._htf_bias(htf) == "SELL"
        confluence_ok = not has_distinct_htf or direction == "HOLD" or (direction == "BUY" and htf_bullish) or (direction == "SELL" and htf_bearish)
        if not confluence_ok:
            direction = "HOLD"
            score = min(score, 0.5)
        reasoning = {"score": score, "regime": regime, "htf_bias": self._htf_bias(htf), "confluence_ok": confluence_ok, "components": {key: value.confidence for key, value in signals.items()}}
        return Signal(ltf.symbol, ltf.timeframe, direction, score, reasoning, self.strategy_id, ltf.candle_time, market_regime=regime)

    @staticmethod
    def _snapshots(value: IndicatorSnapshot | Mapping[str, IndicatorSnapshot] | Sequence[IndicatorSnapshot]) -> dict[str, IndicatorSnapshot]:
        if isinstance(value, IndicatorSnapshot):
            return {value.timeframe: value}
        if isinstance(value, Mapping):
            return dict(value)
        return {item.timeframe: item for item in value}

    @staticmethod
    def _htf_bias(snapshot: IndicatorSnapshot) -> str:
        reference_price = snapshot.vwap
        if reference_price is None or snapshot.ema_50 is None:
            return "HOLD"
        return "BUY" if reference_price > snapshot.ema_50 else "SELL" if reference_price < snapshot.ema_50 else "HOLD"

