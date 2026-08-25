from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from indicators.base_indicator import IndicatorSnapshot
from strategy.base_strategy import BaseStrategy, Signal
from strategy.regime_detector import RegimeDetector
from logs.file_logger import get_file_logger


logger = logging.getLogger(__name__)


def clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


class CompositeStrategy(BaseStrategy):
    strategy_id = "composite"

    def __init__(
        self,
        strategies: list[BaseStrategy],
        regime_detector: RegimeDetector | None = None,
        *,
        htf_timeframes: tuple[str, ...] = ("1h", "4h"),
        weights: dict[str, float] | None = None,
        buy_threshold: float = 0.20,
        sell_threshold: float = -0.20,
    ) -> None:
        self.strategies = strategies
        self.regime_detector = regime_detector or RegimeDetector()
        self.htf_timeframes = htf_timeframes

        # Configurable base weights
        self.strategy_weights = dict(weights or {
            "trend_following": 0.46,
            "mean_reversion": 0.35,
            "breakout": 0.45,
        })

        # Configurable decision thresholds
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self._file_logger = get_file_logger("composite")
       



    def adjust_strategy_weight(self, strategy_id: str, multiplier: float) -> None:
        if strategy_id in self.strategy_weights:
            self.strategy_weights[strategy_id] = max(
                0.0, min(1.0, self.strategy_weights[strategy_id] * multiplier)
            )

    def evaluate(
        self,
        snapshot: IndicatorSnapshot | Mapping[str, IndicatorSnapshot] | Sequence[IndicatorSnapshot],
        position: Any | None = None,
    ) -> Signal:
        snapshots = self._snapshots(snapshot)
        ltf = snapshots.get("5m") or snapshots.get("1m") or next(iter(snapshots.values()))
        htf = next(
            (item for timeframe, item in snapshots.items() if timeframe in self.htf_timeframes),
            ltf,
        )
        has_distinct_htf = htf is not ltf

        # 1. Evaluate all child strategies
        child_signals = {
            strategy.strategy_id: strategy.evaluate(ltf, position)
            for strategy in self.strategies
        }

        # 2. Convert each child Signal into a continuous score [-1, +1]
        child_scores = {
            sid: self._signal_to_score(sig)
            for sid, sig in child_signals.items()
        }

        # 3. Normalize base weights
        w_trend = self.strategy_weights.get("trend_following", 0.0)
        w_rev = self.strategy_weights.get("mean_reversion", 0.0)
        w_brk = self.strategy_weights.get("breakout", 0.0)

        total_w = w_trend + w_rev + w_brk
        if total_w > 0:
            w_trend = (w_trend / total_w) * 0.90
            w_rev = (w_rev / total_w) * 0.90
            w_brk = (w_brk / total_w) * 0.90

        size_reduction_flag = False

        # 4. Regime adjustments (continuous multipliers)
        regime = self.regime_detector.detect(htf)
        if regime == "HIGH_VOL":
            w_trend *= 0.6
            w_rev *= 0.6
            w_brk *= 0.6
            size_reduction_flag = True
        elif regime == "RANGING":
            w_trend *= 0.5

        # 5. Weighted aggregation
        final_score = (
            child_scores.get("trend_following", 0.0) * w_trend
            + child_scores.get("mean_reversion", 0.0) * w_rev
            + child_scores.get("breakout", 0.0) * w_brk
        )

        # 6. Continuous modifiers
        # On-chain
        netflow = getattr(ltf, "exchange_netflow", None)
        if netflow is not None:
            if netflow < 0:
                final_score += 0.10
            elif netflow > 0:
                final_score -= 0.10

        # HTF confluence
        htf_bias = self._htf_bias(htf)
        if has_distinct_htf:
            if htf_bias == "BUY":
                final_score += 0.15
            elif htf_bias == "SELL":
                final_score -= 0.15

        final_score = clamp(final_score)

        # 7. Position-aware decision (EXIT has priority)
        if position is not None:
            if position.side == "LONG" and (
                final_score <= -0.35
                or child_scores.get("trend_following", 0.0) < -0.40
            ):
                direction = "EXIT"
                confidence = abs(final_score)
            elif position.side == "SHORT" and (
                final_score >= 0.35
                or child_scores.get("trend_following", 0.0) > 0.40
            ):
                direction = "EXIT"
                confidence = abs(final_score)
            else:
                direction = "HOLD"
                confidence = abs(final_score)
        else:
            # Pure threshold decision
            if final_score >= self.buy_threshold:
                direction = "BUY"
                confidence = abs(final_score)
            elif final_score <= self.sell_threshold:
                direction = "SELL"
                confidence = abs(final_score)
            else:
                direction = "HOLD"
                confidence = abs(final_score)

        # 8. Logging
        score_parts = " | ".join(
            f"{sid}={score:+.3f}" for sid, score in child_scores.items()
        )
        self._file_logger.info(
            "[SCORING] %s %s | %s",
            ltf.symbol, ltf.timeframe, score_parts,
        )
        self._file_logger.info(
            "[SCORING] Weighted Score=%+.3f | BUY≥%+.2f | SELL≤%+.2f → %s",
            final_score, self.buy_threshold, self.sell_threshold, direction,
        )

        reasoning = {
            "final_score": final_score,
            "buy_threshold": self.buy_threshold,
            "sell_threshold": self.sell_threshold,
            "child_scores": child_scores,
            "weights": {
                "trend_following": w_trend,
                "mean_reversion": w_rev,
                "breakout": w_brk,
            },
            "regime": regime,
            "htf_bias": htf_bias,
            "components": {
                sid: sig.confidence for sid, sig in child_signals.items()
            },
        }
        if size_reduction_flag:
            reasoning["size_reduction_flag"] = True

        return Signal(
            ltf.symbol,
            ltf.timeframe,
            direction,
            confidence,
            reasoning,
            self.strategy_id,
            ltf.candle_time,
            market_regime=regime,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _signal_to_score(signal: Signal) -> float:
        """Convert a child Signal into a continuous score in [-1, +1]."""
        # Prefer explicit continuous score if the child already provides it
        if isinstance(signal.reasoning, dict):
            if "final_score" in signal.reasoning:
                return clamp(float(signal.reasoning["final_score"]))
            if "score" in signal.reasoning:
                # Older discrete composite style (always positive)
                raw = float(signal.reasoning["score"])
                if signal.direction == "SELL":
                    return -raw
                if signal.direction == "BUY":
                    return raw
                return 0.0

        # Fallback: map discrete direction + confidence
        conf = float(signal.confidence or 0.0)
        if signal.direction == "BUY":
            return clamp(conf)
        if signal.direction == "SELL":
            return clamp(-conf)
        return 0.0

    @staticmethod
    def _snapshots(
        value: IndicatorSnapshot | Mapping[str, IndicatorSnapshot] | Sequence[IndicatorSnapshot],
    ) -> dict[str, IndicatorSnapshot]:
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
        if close < ema_50 and ema_50 < ema_200:
            return "SELL"
        return "HOLD"