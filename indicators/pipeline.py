from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from config.settings import get_settings
from data.market_store import MarketStore
from indicators.base_indicator import IndicatorSnapshot
from indicators.momentum.macd import MACD
from indicators.momentum.rsi import RSI
from indicators.momentum.stochastic import Stochastic
from indicators.price.bollinger import BollingerBands
from indicators.price.ema import EMA
from indicators.price.vwap import VWAP
from indicators.volatility.adx import ADX
from indicators.volatility.atr import ATR
from indicators.volatility.keltner import KeltnerChannel
from indicators.volume.obv import OBV
from indicators.volume.volume_profile import VolumeProfile


class IndicatorPipeline:
    def __init__(self, market_store: MarketStore) -> None:
        self.market_store = market_store
        settings = get_settings()
        self.ema_periods = settings.ema_periods
        self.rsi = RSI(settings.rsi_period)
        self.macd = MACD(settings.macd_fast, settings.macd_slow, settings.macd_signal_period)
        self.stochastic = Stochastic(14, 3, 3)
        self.bollinger = BollingerBands(settings.bb_period, settings.bb_std)
        self.vwap = VWAP()
        self.atr = ATR(settings.atr_period)
        self.adx = ADX(settings.adx_period)
        self.keltner = KeltnerChannel(20, 1.5)
        self.obv = OBV()
        self.volume_profile = VolumeProfile()

    def compute(self, symbol: str, timeframe: str) -> IndicatorSnapshot | None:
        candles = self.market_store.get_candles(symbol, timeframe)
        if not candles:
            return None
        frame = pd.DataFrame([c.model_dump() for c in candles])

        # Paksa kolom OHLCV ke float64 secara eksplisit.
        # Candle 1m dari Binance bisa menghasilkan kolom object jika ada nilai
        # None / NaN yang masuk melalui field Optional di model Candle.
        # Ini mencegah downstream crash di ADX, ATR, dan indikator lain yang
        # memanggil .ewm() atau .rolling() dan mengharapkan dtype numerik.
        _numeric_cols = ["open", "high", "low", "close", "volume", "quote_volume"]
        for col in _numeric_cols:
            if col in frame.columns:
                frame[col] = pd.to_numeric(frame[col], errors="coerce")
        latest = frame.iloc[-1]
        ema = {period: EMA(period).calculate(frame).iloc[-1] for period in self.ema_periods}
        vwap = self.vwap.calculate(frame).iloc[-1]
        bands = self.bollinger.calculate(frame).iloc[-1]
        rsi = self.rsi.calculate(frame).iloc[-1]
        macd = self.macd.calculate(frame).iloc[-1]
        stochastic = self.stochastic.calculate(frame).iloc[-1]
        atr = self.atr.calculate(frame).iloc[-1]
        adx = self.adx.calculate(frame).iloc[-1]
        keltner = self.keltner.calculate(frame).iloc[-1]
        volume = self.volume_profile.calculate(frame).iloc[-1]
        hist_vol = frame["close"].pct_change().rolling(20, min_periods=20).std(ddof=0).iloc[-1] * np.sqrt(365)
        vwap_value = self._number(vwap.get("vwap"))
        close = float(latest["close"])
        onchain = self.market_store.get_onchain(symbol)
        latest_onchain = onchain[-1] if onchain else None
        return IndicatorSnapshot(
            symbol=symbol.upper(), timeframe=timeframe, candle_time=int(latest["open_time"]), close=close,                 
            ema_9=self._number(ema.get(9)), ema_21=self._number(ema.get(21)),
            ema_50=self._number(ema.get(50)), ema_200=self._number(ema.get(200)),
            vwap=vwap_value, bb_upper=self._number(bands.get("upper")),
            bb_mid=self._number(bands.get("middle")), bb_lower=self._number(bands.get("lower")),
            rsi_14=self._number(rsi), macd_line=self._number(macd.get("line")),
            macd_signal=self._number(macd.get("signal")), macd_hist=self._number(macd.get("hist")),
            stoch_k=self._number(stochastic.get("k")), stoch_d=self._number(stochastic.get("d")),
            mfi_14=self._mfi(frame), obv=self._number(self.obv.calculate(frame)),
            taker_buy_ratio=self._number(volume.get("taker_buy_ratio")),
            vwap_dev_pct=((close - vwap_value) / vwap_value * 100) if vwap_value else None,
            atr_14=self._number(atr), adx_14=self._number(adx),
            kc_upper=self._number(keltner.get("upper")), kc_lower=self._number(keltner.get("lower")),
            hist_vol_20=self._number(hist_vol),
            nvt_ratio=latest_onchain.nvt_ratio if latest_onchain else None,
            exchange_netflow=latest_onchain.exchange_netflow_24h if latest_onchain else None,
            market_regime=self._regime(close, self._number(ema.get(50)), self._number(ema.get(200)), self._number(adx), self._number(hist_vol)),
            created_at=int(datetime.now(timezone.utc).timestamp() * 1000),
            
        )

    def compute_history(self, symbol: str, timeframe: str) -> list[IndicatorSnapshot]:
        candles = self.market_store.get_candles(symbol, timeframe)
        snapshots: list[IndicatorSnapshot] = []
        for end in range(1, len(candles) + 1):
            window = MarketStore(max_window=len(candles))
            for candle in candles[:end]:
                window.append(candle)
            snapshot = IndicatorPipeline(window).compute(symbol, timeframe)
            if snapshot is not None:
                snapshots.append(snapshot)
        return snapshots

    @staticmethod
    def _number(value: object) -> float | None:
        if isinstance(value, pd.DataFrame):
            value = value.iloc[-1, 0]
        elif isinstance(value, pd.Series):
            value = value.iloc[-1]
        return None if value is None or pd.isna(value) else float(value)

    @staticmethod
    def _mfi(frame: pd.DataFrame, period: int = 14) -> float | None:
        typical = (frame["high"] + frame["low"] + frame["close"]) / 3
        money_flow = typical * frame["volume"]
        direction = typical.diff()
        positive = money_flow.where(direction > 0, 0.0).rolling(period, min_periods=period).sum()
        negative = money_flow.where(direction < 0, 0.0).abs().rolling(period, min_periods=period).sum()
        if negative.iloc[-1] == 0:
            return 100.0 if positive.iloc[-1] > 0 else None
        return float(100 - 100 / (1 + positive.iloc[-1] / negative.iloc[-1]))

    @staticmethod
    def _regime(close: float, ema_50: float | None, ema_200: float | None, adx: float | None, hist_vol: float | None) -> str | None:
        if ema_50 is None or ema_200 is None:
            return None
        if hist_vol is not None and hist_vol > 1.0:
            return "HIGH_VOL"
        if adx is not None and adx >= 25:
            return "TRENDING_UP" if close > ema_50 > ema_200 else "TRENDING_DOWN"
        return "RANGING"