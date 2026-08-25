import logging
from indicators.base_indicator import IndicatorSnapshot
from strategy.base_strategy import BaseStrategy, Signal
from typing import Any # <--- Add this import at the top
logger = logging.getLogger(__name__)

class TrendFollowingStrategy(BaseStrategy):
    strategy_id = "trend_following"

    def evaluate(self, snapshot: IndicatorSnapshot, position: Any | None = None) -> Signal:
        ema_50 = getattr(snapshot, "ema_50", None)
        ema_200 = getattr(snapshot, "ema_200", None)
        ema_9 = getattr(snapshot, "ema_9", None)
        ema_21 = getattr(snapshot, "ema_21", None)
        macd_hist = getattr(snapshot, "macd_hist", None)
        rsi_14 = getattr(snapshot, "rsi_14", None)
        volume_ratio = getattr(snapshot, "volume_ratio", None)
        exchange_netflow = getattr(snapshot, "exchange_netflow", None)

        bullish_conditions = [
            ema_50 is not None and ema_200 is not None and ema_50 > ema_200,
            ema_9 is not None and ema_21 is not None and ema_9 > ema_21,
            macd_hist is not None and macd_hist > 0,
            rsi_14 is not None and 45 <= rsi_14 <= 65,
            volume_ratio is not None and volume_ratio > 1.5,
            exchange_netflow is not None and exchange_netflow < 0
        ]
        
        bearish_conditions = [
            ema_50 is not None and ema_200 is not None and ema_50 < ema_200,
            ema_9 is not None and ema_21 is not None and ema_9 < ema_21,
            macd_hist is not None and macd_hist < 0,
            rsi_14 is not None and 35 <= rsi_14 <= 55,
            volume_ratio is not None and volume_ratio > 1.5,
            exchange_netflow is not None and exchange_netflow > 0
        ]

        bull_count = sum(bullish_conditions)
        bear_count = sum(bearish_conditions)

        if bull_count >= 4:
            direction = "BUY"
            confidence = bull_count / 6.0
        elif bear_count >= 4:
            direction = "SELL"
            confidence = bear_count / 6.0
        else:
            direction = "HOLD"
            confidence = max(bull_count, bear_count) / 6.0
        # --- CHECKPOINT 6 ---
        logger.debug(
            "TrendFollow %s | ema_align=%s ema9>21=%s macd_pos=%s rsi_range=%s | bull_count=%s bear_count=%s",
            snapshot.symbol,
            (ema_50 or 0) > (ema_200 or 0),
            (ema_9 or 0) > (ema_21 or 0),
            (macd_hist or 0) > 0,
            45 <= (rsi_14 or 0) <= 65,
            bull_count, bear_count
        )

        return Signal(
            snapshot.symbol, 
            snapshot.timeframe, 
            direction, 
            confidence, 
            {"bullish_count": bull_count, "bearish_count": bear_count}, 
            self.strategy_id, 
            snapshot.candle_time
        )