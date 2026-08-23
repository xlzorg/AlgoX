from pydantic import BaseModel


class TradeResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    fill_uuid: str
    order_uuid: str
    signal_uuid: str | None = None
    symbol: str
    side: str
    filled_qty: float
    avg_price: float
    fee: float
    fee_asset: str
    slippage_pct: float
    timestamp: int
    created_at: int


class TradeListResponse(BaseModel):
    items: list[TradeResponse]
    total: int
