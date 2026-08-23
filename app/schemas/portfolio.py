from pydantic import BaseModel


class PortfolioSummary(BaseModel):
    balance_usdt: float
    total_equity: float
    open_positions: int
    unrealized_pnl: float
    realized_pnl_today: float
    realized_pnl_total: float


class PositionResponse(BaseModel):
    position_uuid: str
    symbol: str
    side: str
    status: str
    quantity: float
    entry_price: float
    current_price: float | None = None
    exit_price: float | None = None
    unrealized_pnl: float = 0.0
    pnl_pct: float = 0.0
    realized_pnl: float | None = None


class WalletSnapshotResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    timestamp: int
    usdt_balance: float
    total_equity: float
    open_positions: int
    created_at: int


class EquityPointResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    timestamp: int
    equity: float
    drawdown_pct: float
    peak_equity: float
    created_at: int
