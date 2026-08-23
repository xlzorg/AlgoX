from indicators.base_indicator import IndicatorSnapshot
from strategy.base_strategy import BaseStrategy, Signal


class BreakoutStrategy(BaseStrategy):
    strategy_id = "breakout"

    def evaluate(self, snapshot: IndicatorSnapshot) -> Signal:
        breakout = snapshot.kc_upper is not None and snapshot.bb_upper is not None and snapshot.kc_upper < snapshot.bb_upper
        direction = "BUY" if breakout and (snapshot.atr_14 or 0) > 0 else "HOLD"
        return Signal(snapshot.symbol, snapshot.timeframe, direction, 1.0 if direction == "BUY" else 0.0, {"keltner_breakout": breakout}, self.strategy_id, snapshot.candle_time)
from indicators.base_indicator import IndicatorSnapshot
from strategy.base_strategy import BaseStrategy, Signal

class BreakoutStrategy(BaseStrategy):
    strategy_id = "breakout"

    def evaluate(self, snapshot: IndicatorSnapshot) -> Signal:
        breakout = snapshot.kc_upper is not None and snapshot.bb_upper is not None and snapshot.kc_upper < snapshot.bb_upper
        direction = "BUY" if breakout and (snapshot.atr_14 or 0) > 0 else "HOLD"
        return Signal(snapshot.symbol, snapshot.timeframe, direction, 1.0 if direction == "BUY" else 0.0, {"keltner_breakout": breakout}, self.strategy_id, snapshot.candle_time)
