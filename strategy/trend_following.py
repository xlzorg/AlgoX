from indicators.base_indicator import IndicatorSnapshot
from strategy.base_strategy import BaseStrategy, Signal

class TrendFollowingStrategy(BaseStrategy):
    strategy_id = "trend_following"

    def evaluate(self, snapshot: IndicatorSnapshot) -> Signal:
        bullish = (
            snapshot.ema_50 is not None and snapshot.ema_200 is not None
            and snapshot.ema_9 is not None and snapshot.ema_21 is not None
            and snapshot.macd_hist is not None and snapshot.rsi_14 is not None
            and snapshot.ema_50 > snapshot.ema_200
            and snapshot.ema_9 > snapshot.ema_21
            and snapshot.macd_hist > 0
            and 45 <= snapshot.rsi_14 <= 65
        )
        bearish = (
            snapshot.ema_50 is not None and snapshot.ema_200 is not None
            and snapshot.ema_9 is not None and snapshot.ema_21 is not None
            and snapshot.macd_hist is not None and snapshot.rsi_14 is not None
            and snapshot.ema_50 < snapshot.ema_200
            and snapshot.ema_9 < snapshot.ema_21
            and snapshot.macd_hist < 0
            and 35 <= snapshot.rsi_14 <= 55
        )
        direction = "BUY" if bullish else "SELL" if bearish else "HOLD"
        return Signal(snapshot.symbol, snapshot.timeframe, direction, 1.0 if direction != "HOLD" else 0.0, {"ema_alignment": direction}, self.strategy_id, snapshot.candle_time)
