import pandas as pd

from indicators.base_indicator import BaseIndicator


class BollingerBands(BaseIndicator):
    def __init__(self, period: int = 20, stddev: float = 2.0) -> None:
        self.period = period
        self.stddev = stddev
    def calculate(self, frame: pd.DataFrame | list[float]) -> pd.DataFrame:
        values = frame["close"] if isinstance(frame, pd.DataFrame) else pd.Series(frame, dtype=float)
        middle = values.rolling(self.period, min_periods=self.period).mean()
        deviation = values.rolling(self.period, min_periods=self.period).std(ddof=0)
        return pd.DataFrame({"upper": middle + self.stddev * deviation, "middle": middle, "lower": middle - self.stddev * deviation})
