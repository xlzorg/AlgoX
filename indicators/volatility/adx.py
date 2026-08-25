import numpy as np
import pandas as pd

from indicators.base_indicator import BaseIndicator


class ADX(BaseIndicator):
    def __init__(self, period: int = 14) -> None:
        self.period = period

    def calculate(self, frame: pd.DataFrame) -> pd.Series:
        up_move = frame["high"].diff()
        down_move = -frame["low"].diff()
        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
        previous_close = frame["close"].shift(1)
        true_range = pd.concat(
            [frame["high"] - frame["low"], (frame["high"] - previous_close).abs(), (frame["low"] - previous_close).abs()],
            axis=1,
        ).max(axis=1)
        atr = true_range.ewm(alpha=1 / self.period, adjust=False, min_periods=self.period).mean()
        plus_di = 100 * plus_dm.ewm(alpha=1 / self.period, adjust=False, min_periods=self.period).mean() / atr
        minus_di = 100 * minus_dm.ewm(alpha=1 / self.period, adjust=False, min_periods=self.period).mean() / atr

        # FIX: .replace(0, pd.NA) menyuntikkan pd.NA ke Series sehingga dtype
        # berubah menjadi object dan .ewm() crash dengan DataError.
        # Ini terjadi saat plus_di + minus_di == 0, yang umum di candle 1m
        # dengan volume rendah atau candle doji berturut-turut.
        # Solusi: pakai np.where agar hasilnya tetap float64 murni.
        denom = plus_di + minus_di
        dx = pd.Series(
            np.where(denom == 0, np.nan, 100 * (plus_di - minus_di).abs() / denom),
            index=frame.index,
            dtype=float,
        )
        return dx.ewm(alpha=1 / self.period, adjust=False, min_periods=self.period).mean()