import numpy as np
import pandas as pd

from data.market_store import MarketStore
from data.normalizer import Candle
from indicators.momentum.macd import MACD
from indicators.momentum.rsi import RSI
from indicators.pipeline import IndicatorPipeline
from indicators.price.bollinger import BollingerBands
from indicators.price.ema import EMA
from indicators.volatility.atr import ATR
from indicators.volume.obv import OBV


def sample_frame(size: int = 250) -> pd.DataFrame:
    close = pd.Series(np.linspace(100, 150, size), dtype=float)
    return pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.linspace(100, 200, size),
            "taker_buy_vol": np.linspace(55, 110, size),
        }
    )


def test_ema_matches_pandas_reference() -> None:
    frame = sample_frame()
    expected = frame["close"].ewm(span=9, adjust=False, min_periods=9).mean().iloc[-1]
    actual = EMA(9).calculate(frame).iloc[-1]
    assert actual == expected


def test_bollinger_uses_population_standard_deviation() -> None:
    frame = sample_frame(20)
    expected_mid = frame["close"].mean()
    expected_std = frame["close"].std(ddof=0)
    result = BollingerBands(20, 2).calculate(frame).iloc[-1]
    assert np.isclose(result["middle"], expected_mid)
    assert np.isclose(result["upper"], expected_mid + 2 * expected_std)
    assert np.isclose(result["lower"], expected_mid - 2 * expected_std)


def test_rsi_is_100_for_uninterrupted_gains() -> None:
    frame = sample_frame()
    assert RSI(14).calculate(frame).iloc[-1] == 100.0


def test_macd_has_line_signal_and_histogram() -> None:
    frame = sample_frame()
    result = MACD().calculate(frame).iloc[-1]
    assert result["line"] == result["signal"] + result["hist"]


def test_obv_and_atr_standard_values() -> None:
    frame = pd.DataFrame(
        {
            "high": [10.0, 12.0, 13.0],
            "low": [8.0, 9.0, 11.0],
            "close": [9.0, 11.0, 12.0],
            "volume": [10.0, 20.0, 30.0],
        }
    )
    assert OBV().calculate(frame).tolist() == [0.0, 20.0, 50.0]
    assert np.isclose(ATR(2).calculate(frame).iloc[-1], 2.25)


def test_pipeline_returns_database_snapshot_shape() -> None:
    store = MarketStore(max_window=500)
    frame = sample_frame()
    for index, row in frame.iterrows():
        store.append(
            Candle(
                symbol="BTCUSDT",
                timeframe="1h",
                open_time=index,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
                quote_volume=row.close * row.volume,
                taker_buy_vol=row.taker_buy_vol,
            )
        )
    snapshot = IndicatorPipeline(store).compute("BTCUSDT", "1h")
    assert snapshot is not None
    assert snapshot.symbol == "BTCUSDT"
    assert snapshot.ema_200 is not None
    assert snapshot.candle_time == 249
