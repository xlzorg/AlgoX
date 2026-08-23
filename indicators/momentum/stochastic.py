import pandas as pd

from indicators.base_indicator import BaseIndicator


class Stochastic(BaseIndicator):
    def __init__(self, period: int = 14, smooth_k: int = 3, smooth_d: int = 3) -> None:
        self.period, self.smooth_k, self.smooth_d = period, smooth_k, smooth_d
    def calculate(self, frame: pd.DataFrame) -> pd.DataFrame:
        lowest = frame["low"].rolling(self.period, min_periods=self.period).min()
        highest = frame["high"].rolling(self.period, min_periods=self.period).max()
        raw_k = 100 * (frame["close"] - lowest) / (highest - lowest).replace(0, pd.NA)
        k = raw_k.rolling(self.smooth_k, min_periods=self.smooth_k).mean()
        d = k.rolling(self.smooth_d, min_periods=self.smooth_d).mean()
        return pd.DataFrame({"k": k, "d": d})
