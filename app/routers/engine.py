from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_engine
from app.schemas.engine import EngineActionResponse, EngineStatusResponse, TimeframeRequest, TimeframeResponse
from engine.trading_engine import TradingEngine

router = APIRouter(prefix="/engine", tags=["engine"])


@router.post("/start", response_model=EngineActionResponse)
async def start_engine(engine: TradingEngine = Depends(get_engine)) -> EngineActionResponse:
    await engine.start()
    return EngineActionResponse(running=engine.running)


@router.post("/stop", response_model=EngineActionResponse)
async def stop_engine(engine: TradingEngine = Depends(get_engine)) -> EngineActionResponse:
    await engine.stop()
    return EngineActionResponse(running=engine.running)


@router.get("/status", response_model=EngineStatusResponse)
async def engine_status(engine: TradingEngine = Depends(get_engine)) -> EngineStatusResponse:
    return EngineStatusResponse(
        running=engine.running,
        uptime_sec=engine.uptime_sec,
        symbols=engine.active_symbols,
        active_tfs=engine.timeframes,
    )


@router.post("/timeframe", response_model=TimeframeResponse)
async def switch_timeframe(
    request: TimeframeRequest,
    engine: TradingEngine = Depends(get_engine),
) -> TimeframeResponse:
    try:
        await engine.switch_timeframe(request.timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TimeframeResponse(timeframe=request.timeframe, running=engine.running)
