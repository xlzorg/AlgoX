from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_engine
from app.schemas.trade import TradeListResponse, TradeResponse
from db.base import get_db
from db.models.fill import Fill
from db.models.trade_journal import TradeJournal
from engine.trading_engine import TradingEngine
router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("", response_model=TradeListResponse)
async def list_trades(
    symbol: str | None = Query(None),
    status: str | None = Query(None),
    from_ts: int | None = Query(None),
    to_ts: int | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> TradeListResponse:
    statement = select(Fill)
    if symbol:
        statement = statement.where(Fill.symbol == symbol.upper())
    if from_ts is not None:
        statement = statement.where(Fill.timestamp >= from_ts)
    if to_ts is not None:
        statement = statement.where(Fill.timestamp <= to_ts)
    statement = statement.order_by(desc(Fill.timestamp)).limit(limit)
    result = await db.execute(statement)
    items = list(result.scalars().all())
    return TradeListResponse(items=[TradeResponse.model_validate(item) for item in items], total=len(items))


@router.get("/open")
async def open_trades(engine: TradingEngine = Depends(get_engine)) -> dict:
    positions = engine.portfolio_manager.position_tracker.open_positions()
    return {"items": [position.__dict__ if hasattr(position, "__dict__") else {field: getattr(position, field) for field in position.__dataclass_fields__} for position in positions], "total": len(positions)}


@router.get("/journal")
async def trade_journal(engine: TradingEngine = Depends(get_engine)) -> dict:
    return {"items": [entry.__dict__ if hasattr(entry, "__dict__") else {field: getattr(entry, field) for field in entry.__dataclass_fields__} for entry in engine.portfolio_manager.journal.entries], "total": len(engine.portfolio_manager.journal.entries)}

@router.post("/force-flat")
async def force_flat(
    engine: TradingEngine = Depends(get_engine),
    db: AsyncSession = Depends(get_db),
):
    """Emergency: close all open positions and clear in-memory state."""
    from db.models.position import Position as PositionRow
    from sqlalchemy import update
    import time

    # 1. Close in database
    await db.execute(
        update(PositionRow)
        .where(PositionRow.status == "OPEN")
        .values(
            status="CLOSED",
            exit_price=PositionRow.entry_price,   # zero PnL close
            realized_pnl=0.0,
            exit_time=int(time.time() * 1000),
        )
    )
    await db.commit()

    # 2. Clear in-memory tracker
    tracker = engine.portfolio_manager.position_tracker
    for pos in list(tracker.open_positions()):
        pos.status = "CLOSED"
        pos.exit_price = pos.entry_price
        pos.realized_pnl = 0.0
        tracker.closed.append(pos)
        tracker._positions.pop(pos.position_uuid, None)

    # 3. Reset realized PnL counter if you want a true clean slate
    engine.portfolio_manager.realized_pnl_total = 0.0

    return {
        "status": "ok",
        "message": "All open positions force-closed. System is flat.",
        "open_positions_left": len(tracker.open_positions()),
    }

@router.get("/{trade_id}", response_model=TradeResponse)
async def get_trade(trade_id: int, db: AsyncSession = Depends(get_db)) -> TradeResponse:
    result = await db.execute(select(Fill).where(Fill.id == trade_id))
    fill = result.scalar_one_or_none()
    if fill is None:
        raise HTTPException(status_code=404, detail="Trade not found")
    return TradeResponse.model_validate(fill)
