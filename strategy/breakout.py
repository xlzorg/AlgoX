from __future__ import annotations

from typing import Any

from indicators.base_indicator import IndicatorSnapshot
from strategy.base_strategy import BaseStrategy, Signal
from logs.file_logger import get_file_logger


def clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


class BreakoutStrategy(BaseStrategy):
    strategy_id = "breakout"

    def __init__(
        self,
        *,
        buy_threshold: float = 0.35,
        sell_threshold: float = -0.35,
    ) -> None:
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self._file_logger = get_file_logger("breakout")

    def evaluate(self, snapshot: IndicatorSnapshot, position: Any | None = None) -> Signal:
        scores = self._compute_scores(snapshot)
        final_score = self._aggregate(scores)
        direction, confidence = self._decide(final_score)

        # Logging
        score_str = " | ".join(f"{name}={score:+.3f}" for name, score in scores.items())
        self._file_logger.info(
            "[SCORING] %s %s | %s",
            snapshot.symbol, snapshot.timeframe, score_str,
        )
        self._file_logger.info(
            "[SCORING] Weighted Score=%+.3f | BUY≥%+.2f | SELL≤%+.2f → %s",
            final_score, self.buy_threshold, self.sell_threshold, direction,
        )

        return Signal(
            snapshot.symbol,
            snapshot.timeframe,
            direction,
            confidence,
            {
                "final_score": final_score,
                "buy_threshold": self.buy_threshold,
                "sell_threshold": self.sell_threshold,
                "indicator_scores": scores,
            },
            self.strategy_id,
            snapshot.candle_time,
        )

    # ------------------------------------------------------------------
    # Continuous scoring
    # ------------------------------------------------------------------
    def _compute_scores(self, snap: IndicatorSnapshot) -> dict[str, float]:
        close = getattr(snap, "close", None)
        kc_upper = getattr(snap, "kc_upper", None)
        kc_lower = getattr(snap, "kc_lower", None)
        bb_upper = getattr(snap, "bb_upper", None)
        atr = getattr(snap, "atr_14", None)

        scores = {}

        # 1. Keltner Channel breakout strength
        #    Above kc_upper → bullish, below kc_lower → bearish
        if close is not None and kc_upper is not None and kc_lower is not None:
            mid = (kc_upper + kc_lower) / 2
            half_width = (kc_upper - kc_lower) / 2
            if half_width > 0:
                pos = (close - mid) / half_width
                scores["kc_breakout"] = clamp(pos)          # >1 = strong breakout up
            else:
                scores["kc_breakout"] = 0.0
        else:
            scores["kc_breakout"] = 0.0

        # 2. ATR regime (higher volatility supports breakout continuation)
        #    We treat “ATR is meaningful” as a soft positive contribution.
        #    (You can later normalize against a rolling ATR average if available)
        if atr is not None and atr > 0:
            scores["atr_regime"] = 0.4                      # mild positive bias when ATR exists
        else:
            scores["atr_regime"] = 0.0

        # 3. Squeeze release (Keltner inside Bollinger = compression → energy)
        #    When kc_upper < bb_upper we are in/near a squeeze.
        #    Stronger when the channels are closer.
        if kc_upper is not None and bb_upper is not None and bb_upper > 0:
            ratio = kc_upper / bb_upper
            # ratio < 1.0 means squeeze; the smaller the ratio, the stronger the compression
            if ratio < 1.0:
                scores["squeeze"] = clamp((1.0 - ratio) * 3.0)   # 0 → 1 as squeeze tightens
            else:
                scores["squeeze"] = 0.0
        else:
            scores["squeeze"] = 0.0

        return scores

    def _aggregate(self, scores: dict[str, float]) -> float:
        # Weighted toward the actual breakout, squeeze as confirmation
        weights = {
            "kc_breakout": 0.60,
            "atr_regime": 0.15,
            "squeeze": 0.25,
        }
        total_weight = 0.0
        weighted_sum = 0.0
        for name, score in scores.items():
            w = weights.get(name, 0.0)
            weighted_sum += score * w
            total_weight += w
        if total_weight <= 0:
            return 0.0
        return clamp(weighted_sum / total_weight)

    def _decide(self, score: float) -> tuple[str, float]:
        if score >= self.buy_threshold:
            return "BUY", abs(score)
        if score <= self.sell_threshold:
            return "SELL", abs(score)
        return "HOLD", abs(score)