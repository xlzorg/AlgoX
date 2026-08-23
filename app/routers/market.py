from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_engine
from app.schemas.market import CandleResponse
from config.symbols import DEFAULT_SYMBOL, DEFAULT_TIMEFRAME
from data.market_store import MarketStore
from db.base import get_db
from db.models.candle import Candle as CandleRow
from engine.trading_engine import TradingEngine

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/candles", response_model=list[CandleResponse])
async def candles(
    symbol: str = Query(DEFAULT_SYMBOL),
    timeframe: str = Query(DEFAULT_TIMEFRAME),
    limit: int = Query(200, ge=1, le=500),
    from_ts: int | None = Query(None),
    to_ts: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[CandleRow]:
    statement = (
        select(CandleRow)
        .where(CandleRow.symbol == symbol.upper(), CandleRow.timeframe == timeframe)
    )
    if from_ts is not None:
        statement = statement.where(CandleRow.open_time >= from_ts)
    if to_ts is not None:
        statement = statement.where(CandleRow.open_time <= to_ts)
    statement = statement.order_by(desc(CandleRow.open_time)).limit(limit)
    result = await db.execute(statement)
    return list(reversed(result.scalars().all()))


@router.get("/candles/latest/{symbol}/{timeframe}", response_model=CandleResponse)
async def latest_candle(
    symbol: str,
    timeframe: str,
    engine: TradingEngine = Depends(get_engine),
) -> CandleResponse:
    candle = engine.market_store.latest_candle(symbol, timeframe)
    if candle is None:
        raise HTTPException(status_code=404, detail="No closed candle available")
    return CandleResponse(
        id=0,
        symbol=candle.symbol,
        timeframe=candle.timeframe,
        open_time=candle.open_time,
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
        volume=candle.volume,
        quote_volume=candle.quote_volume,
        trades=candle.trades,
        taker_buy_vol=candle.taker_buy_vol,
        created_at=candle.open_time,
    )


@router.get("/onchain")
async def onchain(symbol: str = Query(DEFAULT_SYMBOL)) -> dict:
    return {"symbol": symbol, "snapshots": []}
