from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.lifespan import lifespan
from app.middleware import register_middleware
from app.routers import analytics, engine, indicators, market, portfolio, signals, trades, ws
from config.settings import get_settings
import logging

logger = logging.getLogger(__name__)


logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# 2. Tell the noisy third-party libraries to only log WARNINGs or errors
logging.getLogger("websockets").setLevel(logging.WARNING)

settings = get_settings()
app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
register_middleware(app)
frontend_dir = Path(__file__).resolve().parent / "frontend"
app.mount("/frontend", StaticFiles(directory=frontend_dir), name="frontend")
app.include_router(engine.router)
app.include_router(market.router)
app.include_router(indicators.router)
app.include_router(signals.router)
app.include_router(trades.router)
app.include_router(portfolio.router)
app.include_router(analytics.router)
app.include_router(ws.router)


@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(frontend_dir / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}
