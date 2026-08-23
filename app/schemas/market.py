from pydantic import BaseModel


class CandleResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    symbol: str
    timeframe: str
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    trades: int | None = None
    taker_buy_vol: float | None = None
    created_at: int


class OnChainResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    symbol: str
    chain: str
    timestamp: int
    pool_tvl_usd: float | None = None
    pool_volume_24h: float | None = None
    exchange_netflow_24h: float | None = None
    nvt_ratio: float | None = None
    active_addresses_24h: int | None = None
    top10_holder_pct: float | None = None
    created_at: int
