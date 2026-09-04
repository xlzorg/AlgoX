from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_engine
from app.schemas.indicator import (
    IndicatorCompareResponse,
    IndicatorHistoryResponse,
    IndicatorSnapshotResponse,
)
from db.base import get_db
from db.models.indicator_snapshot import IndicatorSnapshot as IndicatorSnapshotRow
from engine.trading_engine import TradingEngine
router = APIRouter(prefix="/indicators", tags=["indicators"])


@router.get("/{symbol}/{timeframe}/latest", response_model=IndicatorSnapshotResponse)
async def latest_indicators(
    symbol: str,
    timeframe: str,
    engine: TradingEngine = Depends(get_engine),
    db: AsyncSession = Depends(get_db),
) -> IndicatorSnapshotResponse:
    snapshot = engine.indicator_pipeline.compute(symbol, timeframe)
    if snapshot is not None:
        return IndicatorSnapshotResponse(**snapshot.as_dict())
    result = await db.execute(
        select(IndicatorSnapshotRow)
        .where(IndicatorSnapshotRow.symbol == symbol.upper(), IndicatorSnapshotRow.timeframe == timeframe)
        .order_by(desc(IndicatorSnapshotRow.candle_time))
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="No indicator snapshot available")
    return IndicatorSnapshotResponse.model_validate(row)


@router.get("/{symbol}/{timeframe}/history", response_model=IndicatorHistoryResponse)
async def indicator_history(
    symbol: str,
    timeframe: str,
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> IndicatorHistoryResponse:
    result = await db.execute(
        select(IndicatorSnapshotRow)
        .where(IndicatorSnapshotRow.symbol == symbol.upper(), IndicatorSnapshotRow.timeframe == timeframe)
        .order_by(desc(IndicatorSnapshotRow.candle_time))
        .limit(limit)
    )
    rows = list(reversed(result.scalars().all()))
    return IndicatorHistoryResponse(
        symbol=symbol.upper(), timeframe=timeframe,
        items=[IndicatorSnapshotResponse.model_validate(row) for row in rows],
    )


@router.get("/{symbol}/compare", response_model=IndicatorCompareResponse)
async def compare_indicators(
    symbol: str,
    timeframes: list[str] = Query(default=["1m", "5m"]),
    db: AsyncSession = Depends(get_db),
) -> IndicatorCompareResponse:
    snapshots: dict[str, IndicatorSnapshotResponse | None] = {}
    for timeframe in timeframes:
        result = await db.execute(
            select(IndicatorSnapshotRow)
            .where(IndicatorSnapshotRow.symbol == symbol.upper(), IndicatorSnapshotRow.timeframe == timeframe)
            .order_by(desc(IndicatorSnapshotRow.candle_time))
            .limit(1)
        )
        row = result.scalar_one_or_none()
        snapshots[timeframe] = IndicatorSnapshotResponse.model_validate(row) if row else None
    return IndicatorCompareResponse(symbol=symbol.upper(), snapshots=snapshots)
