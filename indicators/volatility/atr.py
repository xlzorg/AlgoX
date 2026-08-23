import pandas as pd

from indicators.base_indicator import BaseIndicator


class ATR(BaseIndicator):
    def __init__(self, period: int = 14) -> None:
        self.period = period

    def calculate(self, frame: pd.DataFrame) -> pd.Series:
        previous_close = frame["close"].shift(1)
        true_range = pd.concat(
            [frame["high"] - frame["low"], (frame["high"] - previous_close).abs(), (frame["low"] - previous_close).abs()],
            axis=1,
        ).max(axis=1)
        return true_range.ewm(alpha=1 / self.period, adjust=False, min_periods=self.period).mean()
