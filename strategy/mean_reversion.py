from __future__ import annotations

import logging
from typing import Any

from indicators.base_indicator import IndicatorSnapshot
from strategy.base_strategy import BaseStrategy, Signal
from logs.file_logger import get_file_logger


def clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


class MeanReversionStrategy(BaseStrategy):
    strategy_id = "mean_reversion"

    def __init__(
        self,
        *,
        buy_threshold: float = 0.55,
        sell_threshold: float = -0.55,
    ) -> None:
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self._file_logger = get_file_logger("mean_reversion")

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
        bb_lower = getattr(snap, "bb_lower", None)
        bb_upper = getattr(snap, "bb_upper", None)
        bb_middle = getattr(snap, "bb_middle", None)
        rsi = getattr(snap, "rsi_14", None)
        vwap = getattr(snap, "vwap", None)

        scores = {}

        # 1. Bollinger Band position (core mean-reversion signal)
        #    Below lower band → strongly bullish (expect reversion up)
        #    Above upper band → strongly bearish
        if close is not None and bb_lower is not None and bb_upper is not None and bb_middle is not None:
            band_width = bb_upper - bb_lower
            if band_width > 0:
                # Position relative to middle, normalized by half-width
                pos = (close - bb_middle) / (band_width / 2)
                scores["bb_position"] = clamp(-pos)          # invert: below middle = positive
            else:
                scores["bb_position"] = 0.0
        else:
            scores["bb_position"] = 0.0

        # 2. RSI (oversold = bullish for mean reversion)
        if rsi is not None:
            # Map RSI 30 → +1.0, RSI 50 → 0.0, RSI 70 → -1.0
            scores["rsi"] = clamp((50 - rsi) / 20)
        else:
            scores["rsi"] = 0.0

        # 3. VWAP deviation (below VWAP = bullish for mean reversion)
        if close is not None and vwap is not None and vwap != 0:
            pct = (close - vwap) / abs(vwap)
            scores["vwap"] = clamp(-pct * 50)                # ~2% deviation → ±1.0
        else:
            scores["vwap"] = 0.0

        return scores

    def _aggregate(self, scores: dict[str, float]) -> float:
        # Simple equal-weight for now (can be made configurable later)
        if not scores:
            return 0.0
        return clamp(sum(scores.values()) / len(scores))

    def _decide(self, score: float) -> tuple[str, float]:
        if score >= self.buy_threshold:
            return "BUY", abs(score)
        if score <= self.sell_threshold:
            return "SELL", abs(score)
        return "HOLD", abs(score)