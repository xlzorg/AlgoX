import logging

from indicators.base_indicator import IndicatorSnapshot
from logs.file_logger import get_file_logger
logger = logging.getLogger(__name__)


class RegimeDetector:
    def __init__(self, adx_threshold: float = 25.0, high_vol_atr_pct: float = 0.05) -> None:
        self.adx_threshold = adx_threshold
        self.high_vol_atr_pct = high_vol_atr_pct

    def detect(self, snapshot: IndicatorSnapshot) -> str:
        """
        Detect market regime for weight adjustments.
        
        Returns:
        - HIGH_VOL: ATR/VWAP > 5% (apply -5% modifier)
        - TRENDING_UP: ADX >= 25 and EMA_50 > EMA_200 (apply +10% modifier)
        - TRENDING_DOWN: ADX >= 25 and EMA_50 < EMA_200 (apply -10% modifier)
        - LOW_VOL_COIL: Tight Bollinger Bands (apply +5% modifier)
        - NEUTRAL: Default, no regime penalty (0% modifier)
        """
        regime = "NEUTRAL"  # Default: no regime-based weight adjustment
        
        # Priority 1: Detect HIGH_VOL (volatility regime)
        if snapshot.atr_14 is not None and snapshot.vwap:
            if snapshot.atr_14 / snapshot.vwap >= self.high_vol_atr_pct:
                regime = "HIGH_VOL"
                logger.debug(
                    "Regime HIGH_VOL | %s | atr_pct=%.4f >= %.4f",
                    snapshot.symbol,
                    snapshot.atr_14 / snapshot.vwap,
                    self.high_vol_atr_pct,
                )
                return regime
        
        # Priority 2: Detect TRENDING (directional regime)
        if snapshot.adx_14 is not None and snapshot.adx_14 >= self.adx_threshold:
            if snapshot.ema_50 is not None and snapshot.ema_200 is not None:
                if snapshot.ema_50 >= snapshot.ema_200:
                    regime = "TRENDING_UP"
                else:
                    regime = "TRENDING_DOWN"
                logger.debug(
                    "Regime %s | %s | adx=%.1f >= %.1f | ema50=%.2f vs ema200=%.2f",
                    regime,
                    snapshot.symbol,
                    snapshot.adx_14,
                    self.adx_threshold,
                    snapshot.ema_50 or 0,
                    snapshot.ema_200 or 0,
                )
                return regime
        
        # Priority 3: Detect LOW_VOL_COIL (compression regime)
        if snapshot.adx_14 is not None and snapshot.adx_14 < 20:
            if snapshot.bb_upper is not None and snapshot.bb_lower is not None and snapshot.vwap is not None:
                bb_width = snapshot.bb_upper - snapshot.bb_lower
                if bb_width / snapshot.vwap < 0.02:
                    regime = "LOW_VOL_COIL"
                    logger.debug(
                        "Regime LOW_VOL_COIL | %s | bb_width_pct=%.4f < 0.02",
                        snapshot.symbol,
                        bb_width / snapshot.vwap,
                    )
                    return regime
        
        # Default: NEUTRAL (no regime penalty applied)
        logger.debug(
            "Regime NEUTRAL | %s | adx=%.1f | atr_pct=%.4f",
            snapshot.symbol,
            snapshot.adx_14 or 0,
            (snapshot.atr_14 or 0) / (snapshot.vwap or 1),
        )
        
        return regime   