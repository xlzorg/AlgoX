from pydantic import BaseModel


class PerformanceStats(BaseModel):
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    expectancy: float = 0.0
    profit_factor: float = 0.0
    avg_r_multiple: float = 0.0
    total_trades: int = 0
    total_pnl_usdt: float = 0.0
    avg_trade_pct: float = 0.0
    avg_hold_ms: float | None = None


class BreakdownRow(BaseModel):
    symbol: str | None = None
    strategy_id: str | None = None
    market_regime: str | None = None
    trades: int
    avg_pnl_pct: float
    total_pnl_usdt: float
    win_rate: float


class DistributionBucket(BaseModel):
    bucket: float
    count: int


class DrawdownPeriod(BaseModel):
    start: int | None = None
    end: int | None = None
    peak_equity: float
    trough_equity: float
    depth_pct: float
    duration_bars: int | None = None


class CorrelationResponse(BaseModel):
    target: str
    correlations: dict[str, float]


class SignalQualityResponse(BaseModel):
    strategy_id: str
    total_signals: int
    profitable: int
    precision: float
    recall: float
    f1: float
    avg_r: float = 0.0


class SlippageReport(BaseModel):
    trades: int = 0
    avg_slippage: float = 0.0
    min_slippage: float = 0.0
    max_slippage: float = 0.0
    p50_slippage: float = 0.0
    p95_slippage: float = 0.0


class CalendarPoint(BaseModel):
    date: str
    pnl_pct: float
    trades: int
    regime: str | None = None


class RollingPoint(BaseModel):
    timestamp: int
    value: float | None
