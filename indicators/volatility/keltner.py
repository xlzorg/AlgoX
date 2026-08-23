import pandas as pd

from indicators.base_indicator import BaseIndicator
from indicators.volatility.atr import ATR


class KeltnerChannel(BaseIndicator):
    def __init__(self, period: int = 20, atr_multiplier: float = 1.5) -> None:
        self.period = period
        self.atr_multiplier = atr_multiplier

    def calculate(self, frame: pd.DataFrame) -> pd.DataFrame:
        middle = frame["close"].ewm(span=self.period, adjust=False, min_periods=self.period).mean()
        atr = ATR(14).calculate(frame)
        return pd.DataFrame({"middle": middle, "upper": middle + self.atr_multiplier * atr, "lower": middle - self.atr_multiplier * atr})
