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

        # 3. Filter ACTIVE strategies (conviction >= 0.15 threshold)
        # This prevents silent strategies from diluting high-conviction signals
        min_conviction_threshold = 0.15
        active_strategies = {
            sid: score
            for sid, score in child_scores.items()
            if abs(score) >= min_conviction_threshold
        }

        # Log active strategy decisions for debugging
        self._file_logger.info(
            "[ACTIVE_STRATEGIES] %s %s | active=%s | all=%s",
            ltf.symbol, ltf.timeframe,
            list(active_strategies.keys()),
            list(child_scores.keys()),
        )

        # 4. Detect regime upfront (needed for all paths)
        regime = self.regime_detector.detect(htf)

        # 5. If no active strategies, return pure HOLD
        if not active_strategies:
            direction = "HOLD"
            confidence = 0.0
            final_score = 0.0
        else:
            # 6. Reweight among ACTIVE strategies only (they should sum to 1.0)
            active_weights = {
                sid: self.strategy_weights.get(sid, 0.0)
                for sid in active_strategies
            }
            total_active_weight = sum(active_weights.values())

            if total_active_weight <= 0:
                final_score = 0.0
            else:
                # Normalize active weights to 1.0 (not 0.90!)
                normalized_weights = {
                    sid: active_weights[sid] / total_active_weight
                    for sid in active_strategies
                }

                # 7. Weighted aggregation among active strategies
                final_score = sum(
                    active_strategies[sid] * normalized_weights[sid]
                    for sid in active_strategies
                )
            
            # 8. Regime and modifiers as ADDITIVE OFFSETS (not multiplicative cuts)
            
            regime_modifier = 0.0
            size_reduction_flag = False
            
            if regime == "HIGH_VOL":
                regime_modifier = -0.05  # Slight caution (not 60% cut!)
                size_reduction_flag = True
            elif regime == "TRENDING_UP":
                regime_modifier = +0.10
            elif regime == "TRENDING_DOWN":
                regime_modifier = -0.10
            elif regime == "LOW_VOL_COIL":
                regime_modifier = +0.05  # Squeeze = energy for breakout
            # regime == "NEUTRAL": no adjustment (default, was "RANGING" before)

            final_score += regime_modifier

            # 8. HTF confluence as additive modifier
            htf_bias = self._htf_bias(htf)
            if has_distinct_htf:
                if htf_bias == "BUY":
                    final_score += 0.12
                elif htf_bias == "SELL":
                    final_score -= 0.12

            # 9. On-chain modifiers
            netflow = getattr(ltf, "exchange_netflow", None)
            if netflow is not None:
                if netflow < -1000:  # Significant outflow
                    final_score += 0.08
                elif netflow > 1000:  # Significant inflow
                    final_score -= 0.08

            final_score = clamp(final_score)

            # 10. Position-aware decision (EXIT has priority)
            if position is not None:
                if position.side == "LONG" and (
                    final_score <= -0.40
                    or active_strategies.get("trend_following", 0.0) < -0.40
                ):
                    direction = "EXIT"
                    confidence = abs(final_score)
                elif position.side == "SHORT" and (
                    final_score >= 0.40
                    or active_strategies.get("trend_following", 0.0) > 0.40
                ):
                    direction = "EXIT"
                    confidence = abs(final_score)
                else:
                    direction = "HOLD"
                    confidence = abs(final_score)
            else:
                # Pure threshold decision (adjusted to 0.25 from 0.20)
                if final_score >= 0.25:
                    direction = "BUY"
                    confidence = final_score
                elif final_score <= -0.25:
                    direction = "SELL"
                    confidence = abs(final_score)
                else:
                    direction = "HOLD"
                    confidence = abs(final_score)

        # 11. Logging
        score_parts = " | ".join(
            f"{sid}={score:+.3f}" for sid, score in child_scores.items()
        )
        self._file_logger.info(
            "[SCORING] %s %s | %s",
            ltf.symbol, ltf.timeframe, score_parts,
        )
        self._file_logger.info(
            "[SCORING] Final Score=%+.3f | BUY≥0.25 | SELL≤-0.25 → %s (confidence=%.3f)",
            final_score, direction, confidence,
        )

        # Prepare reasoning dict
        reasoning = {
            "final_score": final_score,
            "buy_threshold": 0.25,
            "sell_threshold": -0.25,
            "child_scores": child_scores,
            "active_strategies": list(active_strategies.keys()),
            "regime": regime if not active_strategies else self.regime_detector.detect(htf),
            "htf_bias": self._htf_bias(htf),
            "components": {
                sid: sig.confidence for sid, sig in child_signals.items()
            },
        }
        if active_strategies:
            normalized_weights_dict = {
                sid: active_weights[sid] / sum(active_weights.values())
                for sid in active_strategies
            }
            reasoning["normalized_weights"] = normalized_weights_dict

        return Signal(
            ltf.symbol,
            ltf.timeframe,
            direction,
            confidence,
            reasoning,
            self.strategy_id,
            ltf.candle_time,
            market_regime=regime if active_strategies else "NEUTRAL",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _signal_to_score(signal: Signal) -> float:
        """
        Convert a child Signal into a continuous score in [-1, +1].
        
        CRITICAL: Preserve confidence magnitude even for HOLD signals.
        A HOLD with confidence=0.25 means "weak signal" and should not
        be zeroed out—only signals below 0.15 absolute conviction are filtered.
        """
        # Priority 1: Extract explicitly computed final_score from sub-strategy
        if isinstance(signal.reasoning, dict):
            if "final_score" in signal.reasoning:
                # Sub-strategy already computed signed score (e.g., TrendFollowing)
                return clamp(float(signal.reasoning["final_score"]))
            if "score" in signal.reasoning:
                # Fallback for older composite style (always positive)
                raw = float(signal.reasoning["score"])
                if signal.direction == "SELL":
                    return -raw
                if signal.direction == "BUY":
                    return raw
                # HOLD with legacy score: preserve sign implicitly
                return clamp(raw) if signal.direction in ("BUY", "HOLD") else clamp(-raw)

        # Priority 2: Use direction + confidence to infer signed score
        # CRITICAL FIX: HOLD signals preserve confidence magnitude!
        conf = float(signal.confidence or 0.0)
        if conf < 0.001:  # Near-zero: truly indecisive
            return 0.0
        
        if signal.direction == "BUY":
            return clamp(conf)       # Positive score for bullish
        elif signal.direction == "SELL":
            return clamp(-conf)      # Negative score for bearish
        else:  # HOLD
            # Preserve magnitude but sign remains ambiguous.
            # The conviction gate (0.15) will decide if it's active enough.
            # Return positive (slight bullish lean) for weak HOLD signals,
            # treating HOLD as "weak BUY" rather than "truly neutral".
            # This prevents valid-but-weak trend setups from being suppressed.
            return clamp(conf * 0.5)  # 50% of stated confidence, still directional

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