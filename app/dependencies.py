from fastapi import Request

from db.base import get_db
from engine.trading_engine import TradingEngine


async def get_engine(request: Request) -> TradingEngine:
    return request.app.state.engine
