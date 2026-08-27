# strategy/trend_following.py
from __future__ import annotations
import logging
from typing import Any
from collections.abc import Mapping

from indicators.base_indicator import IndicatorSnapshot
from strategy.base_strategy import BaseStrategy, Signal
from strategy.scoring import IndicatorScore, clamp, linear_score, threshold_score
from logs.file_logger import get_file_logger

logger = logging.getLogger(__name__)

class TrendFollowingStrategy(BaseStrategy):
    strategy_id = "trend_following"

    def __init__(
        self,
        *,
        weights: Mapping[str, float] | None = None,
        buy_threshold: float = 0.35,
        sell_threshold: float = -0.35,
    ) -> None:
        # Configurable weights (will be normalized later)
        self.weights = dict(weights or {
            "ema_trend":   0.40,   # ema_50 vs ema_200
            "ema_fast":    0.70,   # ema_9 vs ema_21
            "macd":        0.60,
            "rsi":         0.45,
            "volume":      0.30,
            "netflow":     0.15,
        })
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self._file_logger = get_file_logger("trend_following")


    def evaluate(self, snapshot: IndicatorSnapshot, position: Any | None = None) -> Signal:
        scores = self._compute_scores(snapshot)
        final_score = self._aggregate(scores)
        direction, confidence = self._decide(final_score)

        # Runtime visibility (no DB storage)
        score_str = " | ".join(f"{s.name}={s.score:+.2f}" for s in scores)
        self._file_logger.info(
            "[SCORING] %s %s | %s",
            snapshot.symbol, snapshot.timeframe, score_str
        )
        self._file_logger.info(
            "[SCORING] Weighted Score=%+.3f | BUY≥%+.2f | SELL≤%+.2f → %s",
            final_score, self.buy_threshold, self.sell_threshold, direction
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
                "indicator_scores": {s.name: s.score for s in scores},
                "weights": dict(self.weights),
            },
            self.strategy_id,
            snapshot.candle_time,
        )

    # ------------------------------------------------------------------
    # Continuous scoring layer
    # ------------------------------------------------------------------
    def _compute_scores(self, snap: IndicatorSnapshot) -> list[IndicatorScore]:
        ema_50 = getattr(snap, "ema_50", None)
        ema_200 = getattr(snap, "ema_200", None)
        ema_9 = getattr(snap, "ema_9", None)
        ema_21 = getattr(snap, "ema_21", None)
        macd_hist = getattr(snap, "macd_hist", None)
        rsi_14 = getattr(snap, "rsi_14", None)
        volume_ratio = getattr(snap, "volume_ratio", None)
        netflow = getattr(snap, "exchange_netflow", None)

        return [
            IndicatorScore(
                "ema_trend",
                self._ema_cross_score(ema_50, ema_200),
                self.weights["ema_trend"],
            ),
            IndicatorScore(
                "ema_fast",
                self._ema_cross_score(ema_9, ema_21),
                self.weights["ema_fast"],
            ),
            IndicatorScore(
                "macd",
                linear_score(macd_hist, center=0.0, scale=0.002),  # tune scale to your asset
                self.weights["macd"],
            ),
            IndicatorScore(
                "rsi",
                threshold_score(rsi_14, bull_threshold=52, bear_threshold=48),
                self.weights["rsi"],
            ),
            IndicatorScore(
                "volume",
                linear_score(volume_ratio, center=1.0, scale=1.0),  # >1.0 bullish
                self.weights["volume"],
            ),
            IndicatorScore(
                "netflow",
                linear_score(netflow, center=0.0, scale=100.0, invert=True),  # negative netflow = bullish
                self.weights["netflow"],
            ),
        ]

    @staticmethod
    def _ema_cross_score(fast: float | None, slow: float | None) -> float:
        if fast is None or slow is None or slow == 0:
            return 0.0
        # Percentage distance, clamped
        pct = (fast - slow) / abs(slow)
        return clamp(pct * 20.0)          # ~5% distance → ±1.0

    def _aggregate(self, scores: list[IndicatorScore]) -> float:
        total_weight = sum(s.weight for s in scores)
        if total_weight <= 0:
            return 0.0
        weighted = sum(s.score * s.weight for s in scores)
        return clamp(weighted / total_weight)

    def _decide(self, score: float) -> tuple[str, float]:
        if score >= self.buy_threshold:
            return "BUY", abs(score)
        if score <= self.sell_threshold:
            return "SELL", abs(score)
        return "HOLD", abs(score)