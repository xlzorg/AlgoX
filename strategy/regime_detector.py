import logging

from indicators.base_indicator import IndicatorSnapshot
from logs.file_logger import get_file_logger
logger = logging.getLogger(__name__)


class RegimeDetector:
    def __init__(self, adx_threshold: float = 25.0, high_vol_atr_pct: float = 0.05) -> None:
        self.adx_threshold = adx_threshold
        self.high_vol_atr_pct = high_vol_atr_pct

    def detect(self, snapshot: IndicatorSnapshot) -> str:
        regime = "RANGING"  # Default fallback
        
        if snapshot.atr_14 is not None and snapshot.vwap:
            if snapshot.atr_14 / snapshot.vwap >= self.high_vol_atr_pct:
                regime = "HIGH_VOL"
        elif snapshot.adx_14 is not None and snapshot.adx_14 >= self.adx_threshold:
            if snapshot.ema_50 is not None and snapshot.ema_200 is not None:
                regime = "TRENDING_UP" if snapshot.ema_50 >= snapshot.ema_200 else "TRENDING_DOWN"
        elif snapshot.adx_14 is not None and snapshot.adx_14 < 20:
            if snapshot.bb_upper is not None and snapshot.bb_lower is not None and snapshot.vwap is not None:
                if (snapshot.bb_upper - snapshot.bb_lower) / snapshot.vwap < 0.02:
                    regime = "LOW_VOL_COIL"
                    
        # --- CHECKPOINT 7 ---
        logger.debug(
            "Regime %s | adx=%.1f atr_pct=%.4f ema50=%.2f ema200=%.2f → %s",
            snapshot.symbol,
            snapshot.adx_14 or 0,
            (snapshot.atr_14 or 0) / (snapshot.vwap or 1),
            snapshot.ema_50 or 0,
            snapshot.ema_200 or 0,
            regime
        )
        
        return regime   