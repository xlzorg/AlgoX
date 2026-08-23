from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.signal import SignalListResponse, SignalResponse
from db.base import get_db
from db.models.signal import Signal

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
    return SignalListResponse(items=[SignalResponse.model_validate(item) for item in items], total=len(items))


@router.get("/live", response_model=SignalListResponse)
async def live_signals(limit: int = Query(10, ge=1, le=100), db: AsyncSession = Depends(get_db)) -> SignalListResponse:
    result = await db.execute(select(Signal).order_by(desc(Signal.timestamp)).limit(limit))
    items = list(result.scalars().all())
    return SignalListResponse(items=[SignalResponse.model_validate(item) for item in items], total=len(items))


@router.get("/{signal_id}", response_model=SignalResponse)
async def get_signal(signal_id: int, db: AsyncSession = Depends(get_db)) -> SignalResponse:
    result = await db.execute(select(Signal).where(Signal.id == signal_id))
    return SignalResponse.model_validate(result.scalar_one())
