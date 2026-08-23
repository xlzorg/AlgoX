import pandas as pd

from indicators.base_indicator import BaseIndicator


class OBV(BaseIndicator):
    def calculate(self, frame: pd.DataFrame) -> pd.Series:
        direction = frame["close"].diff().gt(0).astype(int) - frame["close"].diff().lt(0).astype(int)
        return (direction * frame["volume"]).cumsum()
