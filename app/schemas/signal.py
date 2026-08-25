from pydantic import BaseModel, Field
from typing import Any


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


# ── New schemas for /signals/decisions ──────────────────────────────────────

class DecisionComponent(BaseModel):
    """Optional nested structure if you want typed components later."""
    pass  # keep flexible for now


class DecisionItem(BaseModel):
    signal_uuid: str
    symbol: str
    timeframe: str
    timestamp: int
    direction: str
    confidence: float
    market_regime: str | None = None
    score: float
    components: dict[str, Any] = Field(default_factory=dict)
    htf_bias: str = "HOLD"
    risk_decision: str = "SKIPPED_OR_HOLD"
    rejection_reason: str | None = None
    position_size: float = 0.0
    stop_loss: float | None = None
    tp1: float | None = None
    tp2: float | None = None


class DecisionListResponse(BaseModel):
    symbol: str
    count: int
    items: list[DecisionItem]