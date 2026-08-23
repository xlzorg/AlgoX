import pandas as pd

from indicators.base_indicator import BaseIndicator


class VWAP(BaseIndicator):
    def calculate(self, frame: pd.DataFrame) -> pd.DataFrame:
        typical = (frame["high"] + frame["low"] + frame["close"]) / 3
        cumulative_volume = frame["volume"].cumsum()
        vwap = (typical * frame["volume"]).cumsum() / cumulative_volume.replace(0, pd.NA)
        variance = ((typical - vwap) ** 2 * frame["volume"]).cumsum() / cumulative_volume.replace(0, pd.NA)
        deviation = variance.clip(lower=0).pow(0.5)
        return pd.DataFrame({"vwap": vwap, "upper": vwap + deviation, "lower": vwap - deviation})
