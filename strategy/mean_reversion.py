from indicators.base_indicator import IndicatorSnapshot
from strategy.base_strategy import BaseStrategy, Signal


class MeanReversionStrategy(BaseStrategy):
    strategy_id = "mean_reversion"

    def evaluate(self, snapshot: IndicatorSnapshot) -> Signal:
        below_band = snapshot.bb_lower is not None and snapshot.vwap is not None and snapshot.vwap < snapshot.bb_lower
        oversold = snapshot.rsi_14 is not None and snapshot.rsi_14 < 30
        direction = "BUY" if below_band and oversold else "HOLD"
        return Signal(snapshot.symbol, snapshot.timeframe, direction, 1.0 if direction == "BUY" else 0.0, {"below_lower_band": below_band, "rsi_oversold": oversold}, self.strategy_id, snapshot.candle_time)
from indicators.base_indicator import IndicatorSnapshot
from strategy.base_strategy import BaseStrategy, Signal

class MeanReversionStrategy(BaseStrategy):
    strategy_id = "mean_reversion"

    def evaluate(self, snapshot: IndicatorSnapshot) -> Signal:
        price = snapshot.vwap
        lower_band = snapshot.bb_lower
        oversold = snapshot.rsi_14 is not None and snapshot.rsi_14 < 30
        below_band = price is not None and lower_band is not None and price < lower_band
        direction = "BUY" if below_band and oversold else "HOLD"
        return Signal(snapshot.symbol, snapshot.timeframe, direction, 1.0 if direction == "BUY" else 0.0, {"below_lower_band": below_band, "rsi_oversold": oversold}, self.strategy_id, snapshot.candle_time)
