import pytest
from indicators.base_indicator import IndicatorSnapshot
from strategy.base_strategy import Signal
from strategy.trend_following_backup import TrendFollowingStrategy
from strategy.mean_reversion import MeanReversionStrategy
from strategy.breakout import BreakoutStrategy
from strategy.composite import CompositeStrategy
from strategy.regime_detector import RegimeDetector


class MockSnapshot(IndicatorSnapshot):
    """Simulates an IndicatorSnapshot for unit testing."""
    def __init__(self, **kwargs):
        self.symbol = "BTCUSDT"
        self.timeframe = "1h"
        self.candle_time = 1600000000

        fields = [
            "close", "vwap", "ema_9", "ema_21", "ema_50", "ema_200",
            "macd_hist", "rsi_14", "atr_14", "adx_14",
            "bb_upper", "bb_lower", "kc_upper", "kc_lower",
            "volume_ratio", "exchange_netflow"
        ]
        for field in fields:
            setattr(self, field, None)

        for k, v in kwargs.items():
            setattr(self, k, v)


class MockPosition:
    def __init__(self, side: str):
        self.side = side


@pytest.fixture
def strategy_engine():
    return CompositeStrategy(
        strategies=[
            TrendFollowingStrategy(),
            MeanReversionStrategy(),
            BreakoutStrategy(),
        ],
        regime_detector=RegimeDetector(),
    )


def test_strong_uptrend_generates_buy(strategy_engine):
    """Test 1: Does a strong uptrend generate a BUY signal?"""
    # 1. Provide an HTF snapshot to trigger the +0.15 HTF Confluence bonus
    snapshot_htf = MockSnapshot(
        close=51000, 
        ema_50=45000, 

        ema_200=40000,
        adx_14=30
    )
    
    # 2. Provide a perfect LTF snapshot
    snapshot_ltf = MockSnapshot(
        close=51000,
        ema_9=50000,
        ema_21=49000,
        ema_50=48000,
        ema_200=40000,
        macd_hist=100,
        rsi_14=55,
        adx_14=30,
        atr_14=500,
        vwap=50500,
        volume_ratio=2.0,
        exchange_netflow=-500,
        kc_upper=50000,
        bb_upper=52000  # Added bb_upper so 'squeeze' condition evaluates to True
    )
    
    # Wrap them in a dictionary mimicking the Pipeline output
    snapshots = {"1h": snapshot_htf, "5m": snapshot_ltf}
    
    signal = strategy_engine.evaluate(snapshots)
    
    assert signal.direction == "BUY", f"Expected BUY, got {signal.direction} (Score: {signal.confidence})"
    assert signal.market_regime == "TRENDING_UP", f"Regime detection failed: {signal.market_regime}"
    assert signal.confidence >= 0.65, f"Confidence too low: {signal.confidence}"


def test_high_volatility_reduces_weights(strategy_engine):
    """Test 2: Does HIGH_VOL regime correctly flag size reduction?"""
    snapshot = MockSnapshot(
        close=50000, 
        vwap=50000, 
        atr_14=5000,  # High ATR triggers HIGH_VOL
        adx_14=15
    )

    signal = strategy_engine.evaluate(snapshot)

    assert signal.market_regime == "HIGH_VOL", "Did not detect HIGH_VOL regime"
    assert signal.reasoning.get("size_reduction_flag") is True, "Weight reduction flag was not set"


def test_exit_signal_on_trend_reversal(strategy_engine):
    """Test 3: Does the engine emit EXIT if holding LONG when market turns bearish?"""
    position = MockPosition(side="LONG")

    snapshot = MockSnapshot(
        close=39000, 
        ema_9=39500, 
        ema_21=40000, 
        ema_50=41000, 
        ema_200=45000,
        macd_hist=-50, 
        rsi_14=40, 
        adx_14=40,
        volume_ratio=2.0,
        exchange_netflow=500  # 6/6 bearish conditions met
    )

    signal = strategy_engine.evaluate(snapshot, position=position)

    assert signal.direction == "EXIT", f"Expected EXIT, got {signal.direction}"


def test_htf_confluence_veto(strategy_engine):
    """Test 4: Does HTF correctly modify score reasoning?"""
    snapshot_htf = MockSnapshot(close=50000, ema_50=45000, ema_200=40000)
    snapshot_ltf = MockSnapshot(close=50000, timeframe="5m")

    snapshots = {"1h": snapshot_htf, "5m": snapshot_ltf}

    signal = strategy_engine.evaluate(snapshots)

    assert signal.reasoning.get("htf_bias") == "BUY", "HTF bias calculation failed"