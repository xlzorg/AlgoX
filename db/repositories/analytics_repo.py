from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class AnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def performance(self, symbol: str | None = None, strategy_id: str | None = None) -> dict:
        filters = ["exit_time IS NOT NULL"]
        params: dict[str, object] = {}
        if symbol:
            filters.append("symbol = :symbol")
            params["symbol"] = symbol.upper()
        if strategy_id:
            filters.append("strategy_id = :strategy_id")
            params["strategy_id"] = strategy_id
        where = " AND ".join(filters)
        query = text(f"""
            SELECT COUNT(*) AS total_trades,
                   COALESCE(AVG(pnl_pct), 0) AS avg_trade_pct,
                   COALESCE(SUM(pnl_usdt), 0) AS total_pnl_usdt,
                   COALESCE(AVG(r_multiple), 0) AS avg_r_multiple,
                   COALESCE(SUM(CASE WHEN pnl_usdt > 0 THEN pnl_usdt ELSE 0 END) / NULLIF(ABS(SUM(CASE WHEN pnl_usdt < 0 THEN pnl_usdt ELSE 0 END)), 0), 0) AS profit_factor,
                   AVG(CASE WHEN pnl_pct > 0 THEN pnl_pct END) AS avg_win_pct,
                   AVG(CASE WHEN pnl_pct < 0 THEN pnl_pct END) AS avg_loss_pct,
                   AVG(exit_time - entry_time) AS avg_hold_ms,
                   COALESCE(SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) * 1.0 / NULLIF(COUNT(*), 0), 0) AS win_rate
            FROM trade_journal WHERE {where}
        """)
        row = (await self.session.execute(query, params)).mappings().one()
        return dict(row)

    async def by_symbol(self) -> list[dict]:
        return await self._group("symbol")

    async def by_strategy(self) -> list[dict]:
        return await self._group("strategy_id")

    async def by_regime(self) -> list[dict]:
        return await self._group("COALESCE(market_regime, 'UNKNOWN')", alias="market_regime")

    async def _group(self, field: str, alias: str | None = None) -> list[dict]:
        name = alias or field
        query = text(f"""
            SELECT {field} AS {name}, COUNT(*) AS trades, COALESCE(AVG(pnl_pct), 0) AS avg_pnl_pct,
                   COALESCE(SUM(pnl_usdt), 0) AS total_pnl_usdt,
                   COALESCE(SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) * 1.0 / NULLIF(COUNT(*), 0), 0) AS win_rate
            FROM trade_journal WHERE exit_time IS NOT NULL GROUP BY {field}
        """)
        return [dict(row) for row in (await self.session.execute(query)).mappings().all()]

    async def return_distribution(self, bucket_size: float = 0.005) -> list[dict]:
        query = text("""
            SELECT ROUND(pnl_pct / :bucket * :bucket, 4) AS bucket, COUNT(*) AS count
            FROM trade_journal WHERE exit_time IS NOT NULL GROUP BY 1 ORDER BY 1
        """)
        return [dict(row) for row in (await self.session.execute(query, {"bucket": bucket_size})).mappings().all()]

    async def drawdown_curve(self) -> list[dict]:
        rows = (await self.session.execute(text("SELECT timestamp, equity, drawdown_pct, peak_equity FROM equity_curve ORDER BY timestamp ASC"))).mappings().all()
        return [dict(row) for row in rows]

    async def signal_quality(self) -> list[dict]:
        query = text("""
            SELECT strategy_id, COUNT(*) AS total_signals,
                   SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) AS profitable,
                   COALESCE(AVG(r_multiple), 0) AS avg_r
            FROM trade_journal WHERE exit_time IS NOT NULL GROUP BY strategy_id
        """)
        return [dict(row) for row in (await self.session.execute(query)).mappings().all()]

    async def journals(self) -> list[dict]:
        rows = (await self.session.execute(text("SELECT * FROM trade_journal WHERE exit_time IS NOT NULL ORDER BY exit_time ASC"))).mappings().all()
        return [dict(row) for row in rows]

    async def slippage(self) -> dict:
        row = (await self.session.execute(text("SELECT COUNT(*) AS trades, COALESCE(AVG(slippage_pct), 0) AS avg_slippage, COALESCE(MIN(slippage_pct), 0) AS min_slippage, COALESCE(MAX(slippage_pct), 0) AS max_slippage FROM fills"))).mappings().one()
        values = [float(item[0]) for item in (await self.session.execute(text("SELECT slippage_pct FROM fills ORDER BY slippage_pct"))).all()]
        if values:
            import numpy as np
            row = dict(row)
            row["p50_slippage"] = float(np.percentile(values, 50))
            row["p95_slippage"] = float(np.percentile(values, 95))
        else:
            row = {**dict(row), "p50_slippage": 0.0, "p95_slippage": 0.0}
        return row

    async def wallet_history(self) -> list[dict]:
        return [dict(row) for row in (await self.session.execute(text("SELECT * FROM wallet_snapshots ORDER BY timestamp ASC"))).mappings().all()]

    async def equity_curve(self) -> list[dict]:
        return [dict(row) for row in (await self.session.execute(text("SELECT * FROM equity_curve ORDER BY timestamp ASC"))).mappings().all()]

    async def rolling_strategy_metrics(self, days: int = 30) -> list[dict]:
        query = text("""
            SELECT strategy_id, pnl_pct
            FROM trade_journal
            WHERE exit_time IS NOT NULL AND exit_time >= :since
        """)
        import time
        from analytics.performance_stats import compute_sharpe
        since = int((time.time() - days * 86400) * 1000)
        grouped: dict[str, list[float]] = {}
        for row in (await self.session.execute(query, {"since": since})).mappings().all():
            grouped.setdefault(str(row["strategy_id"]), []).append(float(row["pnl_pct"] or 0.0))
        return [{"strategy_id": strategy_id, "sharpe": compute_sharpe(values), "win_rate": sum(value > 0 for value in values) / len(values), "trades": len(values)} for strategy_id, values in grouped.items()]
