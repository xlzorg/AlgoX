from pydantic import BaseModel


class SignalResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    symbol: str
    timeframe: str
    signal_uuid: str
    strategy_id: str
    direction: str
    confidence: float
    timestamp: int
    reasoning: str
    market_regime: str | None = None
    created_at: int


class SignalListResponse(BaseModel):
    items: list[SignalResponse]
    total: int
