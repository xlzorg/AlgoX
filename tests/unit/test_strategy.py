from strategy.composite import CompositeStrategy
from strategy.breakout import BreakoutStrategy
from strategy.mean_reversion import MeanReversionStrategy
from strategy.trend_following import TrendFollowingStrategy
from indicators.base_indicator import IndicatorSnapshot

def test_composite_buy_signal():
    strategy = CompositeStrategy([
        TrendFollowingStrategy(),
        MeanReversionStrategy(),
        BreakoutStrategy(),
    ])
    
    # 1. ARRANGE: Create a fake indicator snapshot with perfect bullish conditions
    bullish_snapshot = IndicatorSnapshot(
        symbol="BTCUSDT",
        timeframe="1h",
        candle_time=1,
        vwap=51000,
        ema_9=50500,
        ema_21=50000,
        ema_50=50000,
        ema_200=48000,
        macd_hist=150,
        rsi_14=55,
        adx_14=30,
        atr_14=100,
        kc_upper=51050,
        bb_upper=51100,
        exchange_netflow=-50,
    )
    
    # 2. ACT: Feed the snapshot to the strategy engine
    signal = strategy.evaluate(bullish_snapshot)
    
    # 3. ASSERT: The bot MUST output a BUY signal with high confidence
    assert signal.direction == "BUY", f"Expected BUY, got {signal.direction}"
    assert signal.confidence >= 0.65, "Confidence score failed to breach 0.65 threshold"