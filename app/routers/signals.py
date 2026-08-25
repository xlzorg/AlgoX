from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.signal import (
    DecisionItem,
    DecisionListResponse,
    SignalListResponse,
    SignalResponse,
)
from db.base import get_db
from db.models.signal import Signal          # adjust import path if needed
from db.models.risk_event import RiskEvent   # ← make sure this model exists

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("", response_model=SignalListResponse)
async def list_signals(
    symbol: str | None = Query(None),
    direction: str | None = Query(None),
    strategy_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> SignalListResponse:
    statement = select(Signal)
    if symbol:
        statement = statement.where(Signal.symbol == symbol.upper())
    if direction:
        statement = statement.where(Signal.direction == direction.upper())
    if strategy_id:
        statement = statement.where(Signal.strategy_id == strategy_id)
    statement = statement.order_by(desc(Signal.timestamp)).limit(limit)

    result = await db.execute(statement)
    items = list(result.scalars().all())
    return SignalListResponse(
        items=[SignalResponse.model_validate(item) for item in items],
        total=len(items),
    )


@router.get("/live", response_model=SignalListResponse)
async def live_signals(
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> SignalListResponse:
    result = await db.execute(
        select(Signal).order_by(desc(Signal.timestamp)).limit(limit)
    )
    items = list(result.scalars().all())
    return SignalListResponse(
        items=[SignalResponse.model_validate(item) for item in items],
        total=len(items),
    )


@router.get("/decisions", response_model=DecisionListResponse)
async def get_candle_decisions(
    symbol: str = Query("BTCUSDT"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> DecisionListResponse:
    """
    Full decision trace for recently closed candles.
    Joins Signal + RiskEvent so the frontend can show
    regime, components, risk decision, SL/TP, etc.
    """
    query = (
        select(Signal, RiskEvent)
        .outerjoin(RiskEvent, Signal.signal_uuid == RiskEvent.signal_uuid)
        .where(Signal.symbol == symbol.upper())
        .order_by(desc(Signal.timestamp))
        .limit(limit)
    )
    result = await db.execute(query)
    rows = result.all()

    decisions: list[DecisionItem] = []
    for sig, risk in rows:
        reasoning: dict[str, Any] = {}
        if sig.reasoning:
            try:
                reasoning = json.loads(sig.reasoning)
            except Exception:
                reasoning = {}

        decisions.append(
            DecisionItem(
                signal_uuid=sig.signal_uuid,
                symbol=sig.symbol,
                timeframe=sig.timeframe,
                timestamp=sig.timestamp,
                direction=sig.direction,
                confidence=sig.confidence,
                market_regime=sig.market_regime,
                score=reasoning.get("score", sig.confidence),
                components=reasoning.get("components", {}),
                htf_bias=reasoning.get("htf_bias", "HOLD"),
                risk_decision=risk.decision if risk else "SKIPPED_OR_HOLD",
                rejection_reason=risk.rejection_reason if risk else None,
                position_size=risk.position_size if risk else 0.0,
                stop_loss=risk.stop_loss_price if risk else None,
                tp1=risk.tp1_price if risk else None,
                tp2=getattr(risk, "tp2_price", None) if risk else None,
            )
        )

    return DecisionListResponse(
        symbol=symbol.upper(),
        count=len(decisions),
        items=decisions,
    )


@router.get("/{signal_id}", response_model=SignalResponse)
async def get_signal(
    signal_id: int,
    db: AsyncSession = Depends(get_db),
) -> SignalResponse:
    result = await db.execute(select(Signal).where(Signal.id == signal_id))
    return SignalResponse.model_validate(result.scalar_one())

