from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from db.base import init_db
from engine.trading_engine import TradingEngine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    engine = TradingEngine()
    app.state.engine = engine
    await engine.start()
    try:
        yield
    finally:
        await engine.stop()
