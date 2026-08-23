import pandas as pd

from indicators.base_indicator import BaseIndicator


class VolumeProfile(BaseIndicator):
    def calculate(self, frame: pd.DataFrame) -> pd.DataFrame:
        total_volume = frame["volume"].sum()
        taker_volume = frame["taker_buy_vol"].fillna(0).sum() if "taker_buy_vol" in frame else 0.0
        typical = (frame["high"] + frame["low"] + frame["close"]) / 3
        return pd.DataFrame(
            {
                "taker_buy_ratio": [taker_volume / total_volume if total_volume else None] * len(frame),
                "volume_mean": [frame["volume"].mean()] * len(frame),
                "volume_std": [frame["volume"].std(ddof=0)] * len(frame),
                "point_of_control": [float(typical.loc[frame["volume"].idxmax()])] * len(frame) if len(frame) else [],
            },
            index=frame.index,
        )
