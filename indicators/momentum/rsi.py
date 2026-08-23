import pandas as pd
import numpy as np

from indicators.base_indicator import BaseIndicator


class RSI(BaseIndicator):
    def __init__(self, period: int = 14) -> None:
        self.period = period

    def calculate(self, frame: pd.DataFrame | list[float]) -> pd.Series:
        close = frame["close"] if isinstance(frame, pd.DataFrame) else pd.Series(frame, dtype=float)
        delta = close.diff()
        gains = delta.clip(lower=0)
        losses = -delta.clip(upper=0)
        average_gain = gains.ewm(alpha=1 / self.period, adjust=False, min_periods=self.period).mean()
        average_loss = losses.ewm(alpha=1 / self.period, adjust=False, min_periods=self.period).mean()
        relative_strength = average_gain / average_loss.replace(0, np.nan)
        result = 100 - (100 / (1 + relative_strength))
        return result.where(average_loss != 0, 100.0)
