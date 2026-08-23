from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_engine
from app.schemas.portfolio import EquityPointResponse, PortfolioSummary, PositionResponse, WalletSnapshotResponse
from db.base import get_db
from db.models.equity_curve import EquityCurve
from db.models.wallet_snapshot import WalletSnapshot
from engine.trading_engine import TradingEngine
router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/summary", response_model=PortfolioSummary)
async def portfolio_summary(engine: TradingEngine = Depends(get_engine)) -> PortfolioSummary:
    return PortfolioSummary(**engine.portfolio_manager.summary())


@router.get("/positions")
async def positions(engine: TradingEngine = Depends(get_engine)) -> dict:
    items = [PositionResponse.model_validate(position, from_attributes=True) for position in engine.portfolio_manager.position_tracker.positions()]
    return {"items": items, "total": len(items)}


@router.get("/wallet/history", response_model=list[WalletSnapshotResponse])
async def wallet_history(from_ts: int | None = Query(None), to_ts: int | None = Query(None), db: AsyncSession = Depends(get_db)) -> list[WalletSnapshotResponse]:
    statement = select(WalletSnapshot).order_by(desc(WalletSnapshot.timestamp))
    if from_ts is not None:
        statement = statement.where(WalletSnapshot.timestamp >= from_ts)
    if to_ts is not None:
        statement = statement.where(WalletSnapshot.timestamp <= to_ts)
    result = await db.execute(statement)
    return [WalletSnapshotResponse.model_validate(row) for row in reversed(result.scalars().all())]


@router.get("/equity-curve", response_model=list[EquityPointResponse])
async def equity_curve(from_ts: int | None = Query(None), to_ts: int | None = Query(None), db: AsyncSession = Depends(get_db)) -> list[EquityPointResponse]:
    statement = select(EquityCurve).order_by(desc(EquityCurve.timestamp))
    if from_ts is not None:
        statement = statement.where(EquityCurve.timestamp >= from_ts)
    if to_ts is not None:
        statement = statement.where(EquityCurve.timestamp <= to_ts)
    result = await db.execute(statement)
    return [EquityPointResponse.model_validate(row) for row in reversed(result.scalars().all())]
