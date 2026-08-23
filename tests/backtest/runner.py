from __future__ import annotations

import asyncio
import csv
import logging
import sys
import time
from pathlib import Path
from typing import Iterable

# Allow direct execution with `python tests/backtest/runner.py` from the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.normalizer import Candle
from engine.trading_engine import TradingEngine

logger = logging.getLogger(__name__)


class BacktestRunner:
    """Offline event-driven runner sharing the production strategy/risk/broker stack."""

    def __init__(self) -> None:
        self.engine = TradingEngine()
        self.candles_processed = 0

    @staticmethod
    def load_csv(path: str | Path, *, symbol: str, timeframe: str) -> list[Candle]:
        candles = []
        with Path(path).open(newline="") as handle:
            for row in csv.DictReader(handle):
                candles.append(
                    Candle(
                        symbol=symbol.upper(),
                        timeframe=timeframe,
                        open_time=int(row.get("open_time", row.get("timestamp", 0))),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row.get("volume", 0)),
                        quote_volume=float(row.get("quote_volume", float(row["close"]) * float(row.get("volume", 0)))),
                        trades=int(row["trades"]) if row.get("trades") else None,
                        taker_buy_vol=float(row["taker_buy_vol"]) if row.get("taker_buy_vol") else None,
                        is_closed=True,
                    )
                )
        return candles

    async def run(self, candles: Iterable[Candle]) -> dict:
        started = time.perf_counter()
        ordered = sorted(candles, key=lambda candle: (candle.open_time, candle.symbol, candle.timeframe))
        for candle in ordered:
            self.engine.market_store.append(candle)
            await self.engine._on_candle_closed(candle)
            self.candles_processed += 1
        elapsed = time.perf_counter() - started
        summary = self.engine.portfolio_manager.summary()
        summary.update(
            {
                "candles_processed": self.candles_processed,
                "elapsed_sec": elapsed,
                "candles_per_sec": self.candles_processed / elapsed if elapsed else 0.0,
                "fills": len(self.engine.paper_broker.fills),
                "signals": len(self.engine.portfolio_manager.journal.entries),
                "equity_points": len(self.engine.portfolio_manager.performance.points),
            }
        )
        logger.info("Backtest complete: %s", summary)
        return summary

    def run_sync(self, candles: Iterable[Candle]) -> dict:
        return asyncio.run(self.run(candles))


async def run_csv(path: str | Path, *, symbol: str, timeframe: str) -> dict:
    runner = BacktestRunner()
    return await runner.run(runner.load_csv(path, symbol=symbol, timeframe=timeframe))


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Run the offline paper-trading backtest")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--timeframe", default="1h")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run_csv(args.csv_path, symbol=args.symbol, timeframe=args.timeframe)), indent=2))
