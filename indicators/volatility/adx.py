import pandas as pd

from indicators.base_indicator import BaseIndicator


class ADX(BaseIndicator):
    def __init__(self, period: int = 14) -> None:
        self.period = period

    def calculate(self, frame: pd.DataFrame) -> pd.Series:
        up_move = frame["high"].diff()
        down_move = -frame["low"].diff()
        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
        previous_close = frame["close"].shift(1)
        true_range = pd.concat(
            [frame["high"] - frame["low"], (frame["high"] - previous_close).abs(), (frame["low"] - previous_close).abs()],
            axis=1,
        ).max(axis=1)
        atr = true_range.ewm(alpha=1 / self.period, adjust=False, min_periods=self.period).mean()
        plus_di = 100 * plus_dm.ewm(alpha=1 / self.period, adjust=False, min_periods=self.period).mean() / atr
        minus_di = 100 * minus_dm.ewm(alpha=1 / self.period, adjust=False, min_periods=self.period).mean() / atr
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, pd.NA)
        return dx.ewm(alpha=1 / self.period, adjust=False, min_periods=self.period).mean()
