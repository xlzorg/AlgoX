from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from analytics.indicator_correlation import indicator_correlation
from analytics.performance_stats import compute_expectancy, compute_max_drawdown, compute_rolling_sharpe, compute_sharpe, compute_sortino
from analytics.regime_analysis import regime_analysis
from analytics.signal_quality import signal_quality
from analytics.trade_distribution import trade_distribution
from app.schemas.analytics import BreakdownRow, CalendarPoint, CorrelationResponse, DistributionBucket, DrawdownPeriod, PerformanceStats, RollingPoint, SignalQualityResponse, SlippageReport
from db.base import get_db
from db.repositories.analytics_repo import AnalyticsRepository

router = APIRouter(prefix="/analytics", tags=["analytics"])


async def _repo(db: AsyncSession = Depends(get_db)) -> AnalyticsRepository:
    return AnalyticsRepository(db)


@router.get("/performance", response_model=PerformanceStats)
async def performance(repo: AnalyticsRepository = Depends(_repo)) -> PerformanceStats:
    summary = await repo.performance()
    journals = await repo.journals()
    returns = [float(row["pnl_pct"] or 0) for row in journals]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    equity = [100.0]
    for value in returns:
        equity.append(equity[-1] * (1 + value))
    drawdown = compute_max_drawdown(equity)
    return PerformanceStats(sharpe=compute_sharpe(returns), sortino=compute_sortino(returns), max_drawdown=float(drawdown["max_drawdown_pct"]), win_rate=float(summary["win_rate"] or 0), expectancy=compute_expectancy(wins, losses), **{key: summary.get(key) or 0 for key in ["profit_factor", "avg_r_multiple", "total_trades", "total_pnl_usdt", "avg_trade_pct", "avg_hold_ms"]})


@router.get("/performance/by-symbol", response_model=list[BreakdownRow])
async def performance_by_symbol(repo: AnalyticsRepository = Depends(_repo)) -> list[BreakdownRow]:
    return [BreakdownRow(**row) for row in await repo.by_symbol()]


@router.get("/performance/by-strategy", response_model=list[BreakdownRow])
async def performance_by_strategy(repo: AnalyticsRepository = Depends(_repo)) -> list[BreakdownRow]:
    return [BreakdownRow(**row) for row in await repo.by_strategy()]


@router.get("/performance/by-regime", response_model=list[BreakdownRow])
async def performance_by_regime(repo: AnalyticsRepository = Depends(_repo)) -> list[BreakdownRow]:
    return [BreakdownRow(**row) for row in await repo.by_regime()]


@router.get("/drawdown/periods", response_model=list[DrawdownPeriod])
async def drawdown_periods(repo: AnalyticsRepository = Depends(_repo)) -> list[DrawdownPeriod]:
    curve = await repo.drawdown_curve()
    periods = []
    start = None
    for index, point in enumerate(curve):
        if point["drawdown_pct"] < 0 and start is None:
            start = index
        if start is not None and (point["drawdown_pct"] >= 0 or index == len(curve) - 1):
            end = index if point["drawdown_pct"] >= 0 else index
            segment = curve[start:end + 1]
            trough = min(segment, key=lambda item: item["equity"])
            periods.append(DrawdownPeriod(start=segment[0]["timestamp"], end=segment[-1]["timestamp"], peak_equity=segment[0]["peak_equity"], trough_equity=trough["equity"], depth_pct=trough["drawdown_pct"], duration_bars=end - start))
            start = None
    return periods


@router.get("/returns/distribution")
async def returns_distribution(bucket_size: float = Query(0.005, gt=0), repo: AnalyticsRepository = Depends(_repo)) -> dict:
    returns = [float(row["pnl_pct"] or 0) for row in await repo.journals()]
    return trade_distribution(returns, bucket_size)


@router.get("/indicators/correlation", response_model=CorrelationResponse)
async def indicators_correlation(target: str = "pnl_pct", repo: AnalyticsRepository = Depends(_repo)) -> CorrelationResponse:
    return CorrelationResponse(target=target, correlations=indicator_correlation(await repo.journals(), target))


@router.get("/signals/quality", response_model=list[SignalQualityResponse])
async def signals_quality(repo: AnalyticsRepository = Depends(_repo)) -> list[SignalQualityResponse]:
    records = await repo.journals()
    metrics = signal_quality(records)
    return [SignalQualityResponse(strategy_id=key, **value) for key, value in metrics.items()]


@router.get("/regime/summary")
async def regime_summary(repo: AnalyticsRepository = Depends(_repo)) -> dict:
    return regime_analysis(await repo.journals())


@router.get("/slippage/report", response_model=SlippageReport)
async def slippage_report(repo: AnalyticsRepository = Depends(_repo)) -> SlippageReport:
    return SlippageReport(**await repo.slippage())


@router.get("/calendar/heatmap", response_model=list[CalendarPoint])
async def calendar_heatmap(repo: AnalyticsRepository = Depends(_repo)) -> list[CalendarPoint]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in await repo.journals():
        date = datetime.fromtimestamp((row["exit_time"] or row["entry_time"]) / 1000, tz=timezone.utc).date().isoformat()
        grouped[date].append(row)
    return [CalendarPoint(date=date, pnl_pct=sum(float(item["pnl_pct"] or 0) for item in items), trades=len(items), regime=items[-1].get("market_regime")) for date, items in sorted(grouped.items())]


@router.get("/rolling", response_model=list[RollingPoint])
async def rolling(window: int = Query(30, ge=2), metric: str = Query("sharpe"), repo: AnalyticsRepository = Depends(_repo)) -> list[RollingPoint]:
    rows = await repo.journals()
    values = pd.Series([float(row["pnl_pct"] or 0) for row in rows], dtype=float)
    if metric == "sharpe":
        series = compute_rolling_sharpe(values, window)
    elif metric == "winrate":
        series = values.gt(0).rolling(window).mean()
    else:
        series = values.rolling(window).sum()
    return [RollingPoint(timestamp=int(row["exit_time"] or row["entry_time"]), value=None if pd.isna(value) else float(value)) for row, value in zip(rows, series)]
