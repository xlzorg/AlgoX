from indicators.base_indicator import IndicatorSnapshot


class RegimeDetector:
    def __init__(self, adx_threshold: float = 25.0, high_vol_atr_pct: float = 0.05) -> None:
        self.adx_threshold = adx_threshold
        self.high_vol_atr_pct = high_vol_atr_pct

    def detect(self, snapshot: IndicatorSnapshot) -> str:
        if snapshot.atr_14 is not None and snapshot.vwap:
            if snapshot.atr_14 / snapshot.vwap >= self.high_vol_atr_pct:
                return "HIGH_VOL"
        if snapshot.adx_14 is not None and snapshot.adx_14 >= self.adx_threshold:
            if snapshot.ema_50 is not None and snapshot.ema_200 is not None:
                return "TRENDING_UP" if snapshot.ema_50 >= snapshot.ema_200 else "TRENDING_DOWN"
        return "RANGING"
