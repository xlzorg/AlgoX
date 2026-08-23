import pandas as pd

from indicators.base_indicator import BaseIndicator


class EMA(BaseIndicator):
    def __init__(self, period: int = 20) -> None:
        self.period = period

    def calculate(self, frame: pd.DataFrame | list[float]) -> pd.Series:
        values = frame["close"] if isinstance(frame, pd.DataFrame) else pd.Series(frame, dtype=float)
        return values.ewm(span=self.period, adjust=False, min_periods=self.period).mean()
