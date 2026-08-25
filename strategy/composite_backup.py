from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from indicators.base_indicator import IndicatorSnapshot
from strategy.base_strategy import BaseStrategy, Signal
from strategy.regime_detector import RegimeDetector


class CompositeStrategy(BaseStrategy):
    strategy_id = "composite"

    def __init__(
        self, 
        strategies: list[BaseStrategy], 
        regime_detector: RegimeDetector | None = None, 
        *, 
        htf_timeframes: tuple[str, ...] = ("1h", "4h")
    ) -> None:
        self.strategies = strategies
        self.regime_detector = regime_detector or RegimeDetector()
        self.htf_timeframes = htf_timeframes
        self.strategy_weights = {"trend_following": 0.40, "mean_reversion": 0.25, "breakout": 0.25}

    def adjust_strategy_weight(self, strategy_id: str, multiplier: float) -> None:
        if strategy_id in self.strategy_weights:
            self.strategy_weights[strategy_id] = max(0.0, min(1.0, self.strategy_weights[strategy_id] * multiplier))

    def evaluate(
        self, 
        snapshot: IndicatorSnapshot | Mapping[str, IndicatorSnapshot] | Sequence[IndicatorSnapshot], 
        position: Any | None = None
    ) -> Signal:
        snapshots = self._snapshots(snapshot)
        ltf = snapshots.get("5m") or snapshots.get("1m") or next(iter(snapshots.values()))
        htf = next((item for timeframe, item in snapshots.items() if timeframe in self.htf_timeframes), ltf)
        has_distinct_htf = htf is not ltf
        
        signals = {strategy.strategy_id: strategy.evaluate(ltf, position) for strategy in self.strategies}
        regime = self.regime_detector.detect(htf)
        
        trend = signals.get("trend_following", Signal(ltf.symbol, ltf.timeframe, "HOLD", 0.0))
        reversion = signals.get("mean_reversion", Signal(ltf.symbol, ltf.timeframe, "HOLD", 0.0))
        breakout = signals.get("breakout", Signal(ltf.symbol, ltf.timeframe, "HOLD", 0.0))
        
        w_trend = self.strategy_weights["trend_following"]
        w_rev = self.strategy_weights["mean_reversion"]
        w_brk = self.strategy_weights["breakout"]
        
        # 1. Normalize BASE weights
        total_w = w_trend + w_rev + w_brk
        if total_w > 0:
            w_trend = (w_trend / total_w) * 0.90
            w_rev = (w_rev / total_w) * 0.90
            w_brk = (w_brk / total_w) * 0.90

        size_reduction_flag = False

        # 2. Apply regime penalties
        if regime == "HIGH_VOL":
            w_trend *= 0.6
            w_rev *= 0.6
            w_brk *= 0.6
            size_reduction_flag = True
        elif regime == "RANGING":
            w_trend *= 0.5

        # 3. Calculate Bullish and Bearish Scores Separately
        bull_score = 0.0
        bear_score = 0.0

        if trend.direction == "BUY":
            bull_score += trend.confidence * w_trend
        elif trend.direction == "SELL":
            bear_score += trend.confidence * w_trend

        # Reversion and Breakout sub-strategies are long-only
        if reversion.direction == "BUY":
            bull_score += reversion.confidence * w_rev
        if breakout.direction == "BUY":
            bull_score += breakout.confidence * w_brk

        # 4. On-chain modifier
        if getattr(ltf, "exchange_netflow", None) is not None:
            if ltf.exchange_netflow < 0:
                bull_score += 0.10
            elif ltf.exchange_netflow > 0:
                bear_score += 0.10

        # 5. HTF Confluence modifier
        htf_bias = self._htf_bias(htf)
        if has_distinct_htf:
            if htf_bias == "BUY":
                bull_score += 0.15
            elif htf_bias == "SELL":
                bear_score += 0.15

        bull_score = max(0.0, min(1.0, bull_score))
        bear_score = max(0.0, min(1.0, bear_score))

        # 6. Determine final direction and confidence
        if position is not None:
            if position.side == "LONG" and (bear_score >= 0.35 or trend.direction == "SELL"):
                direction = "EXIT"
                final_confidence = bear_score
            elif position.side == "SHORT" and (bull_score >= 0.65 or trend.direction == "BUY"):
                direction = "EXIT"
                final_confidence = bull_score
            else:
                direction = "HOLD"
                final_confidence = max(bull_score, bear_score)
        else:
            if bull_score >= 0.05:
                direction = "BUY"
                final_confidence = bull_score
            elif bear_score >= 0.50 and bear_score >= bull_score:
                direction = "SELL"
                final_confidence = bear_score
            else:
                direction = "HOLD"
                final_confidence = max(bull_score, bear_score)

        reasoning = {
            "score": final_confidence,
            "bull_score": bull_score,
            "bear_score": bear_score,
            "regime": regime,
            "htf_bias": htf_bias,
            "components": {key: value.confidence for key, value in signals.items()}
        }

        if size_reduction_flag:
            reasoning["size_reduction_flag"] = True

        return Signal(
            ltf.symbol, 
            ltf.timeframe, 
            direction, 
            final_confidence, 
            reasoning, 
            self.strategy_id, 
            ltf.candle_time, 
            market_regime=regime
        )

    @staticmethod
    def _snapshots(value: IndicatorSnapshot | Mapping[str, IndicatorSnapshot] | Sequence[IndicatorSnapshot]) -> dict[str, IndicatorSnapshot]:
        if isinstance(value, IndicatorSnapshot):
            return {value.timeframe: value}
        if isinstance(value, Mapping):
            return dict(value)
        return {item.timeframe: item for item in value}

    @staticmethod
    def _htf_bias(snapshot: IndicatorSnapshot) -> str:
        close = getattr(snapshot, "close", None)
        ema_50 = getattr(snapshot, "ema_50", None)
        ema_200 = getattr(snapshot, "ema_200", None)

        if close is None or ema_50 is None or ema_200 is None:
            return "HOLD"

        if close > ema_50 and ema_50 > ema_200:
            return "BUY"
        elif close < ema_50 and ema_50 < ema_200:
            return "SELL"
        else:
            return "HOLD"