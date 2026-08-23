import pandas as pd

from indicators.base_indicator import BaseIndicator


class MACD(BaseIndicator):
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        self.fast, self.slow, self.signal_period = fast, slow, signal
    def calculate(self, frame: pd.DataFrame | list[float]) -> pd.DataFrame:
        close = frame["close"] if isinstance(frame, pd.DataFrame) else pd.Series(frame, dtype=float)
        fast = close.ewm(span=self.fast, adjust=False, min_periods=self.fast).mean()
        slow = close.ewm(span=self.slow, adjust=False, min_periods=self.slow).mean()
        line = fast - slow
        signal = line.ewm(span=self.signal_period, adjust=False, min_periods=self.signal_period).mean()
        return pd.DataFrame({"line": line, "signal": signal, "hist": line - signal})
