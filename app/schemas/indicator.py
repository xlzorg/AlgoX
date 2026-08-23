from pydantic import BaseModel


class IndicatorSnapshotResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int = 0
    symbol: str
    timeframe: str
    candle_time: int
    ema_9: float | None = None
    ema_21: float | None = None
    ema_50: float | None = None
    ema_200: float | None = None
    vwap: float | None = None
    bb_upper: float | None = None
    bb_mid: float | None = None
    bb_lower: float | None = None
    rsi_14: float | None = None
    macd_line: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    stoch_k: float | None = None
    stoch_d: float | None = None
    mfi_14: float | None = None
    obv: float | None = None
    taker_buy_ratio: float | None = None
    vwap_dev_pct: float | None = None
    atr_14: float | None = None
    adx_14: float | None = None
    kc_upper: float | None = None
    kc_lower: float | None = None
    hist_vol_20: float | None = None
    nvt_ratio: float | None = None
    exchange_netflow: float | None = None
    market_regime: str | None = None
    created_at: int = 0


class IndicatorHistoryResponse(BaseModel):
    symbol: str
    timeframe: str
    items: list[IndicatorSnapshotResponse]


class IndicatorCompareResponse(BaseModel):
    symbol: str
    snapshots: dict[str, IndicatorSnapshotResponse | None]