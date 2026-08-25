"""
runner.py — Backtest runner yang diperbaiki untuk production TradingEngine.

Fix dari versi lama:
1. _bootstrap_complete di-set sebelum loop → candle tidak di-skip lagi
2. Intra-candle high/low tick simulation → SL/TP bisa kena di dalam candle
3. CSV loader mendukung format Binance lengkap (close_time, count, dll.)
4. Semua trades direkam ke BacktestLedger untuk analisis per-strategy

Cara pakai:
    python runner.py data/BTCUSDT-1h.csv --symbol BTCUSDT --timeframe 1h
    python runner.py data/ --symbol BTCUSDT --timeframe 1h --report full
"""

from __future__ import annotations

import asyncio
import csv
import logging
import sys
import time
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[0]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.normalizer import Candle
from engine.trading_engine import TradingEngine
from backtest_report import BacktestReport

logger = logging.getLogger(__name__)

# ── Kolom Binance OHLCV (urutan export standar) ───────────────────────────────
_BINANCE_COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "count",
    "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]


class BacktestLedger:
    """Merekam setiap fill selama backtest untuk kalkulasi metrics."""

    def __init__(self) -> None:
        self.entries: list[dict] = []   # BUY fills
        self.exits: list[dict] = []     # SELL fills
        self.equity_curve: list[tuple[int, float]] = []  # (open_time, equity)

    def record_fill(self, fill, candle_time: int) -> None:
        record = {
            "fill_uuid": str(fill.fill_uuid),
            "symbol": fill.symbol,
            "side": fill.side,
            "qty": fill.filled_qty,
            "price": fill.avg_price,
            "fee": fill.fee,
            "slippage_pct": fill.slippage_pct,
            "timestamp": fill.timestamp,
            "candle_open_time": candle_time,
        }
        if fill.side in ("BUY", "LONG"):
            self.entries.append(record)
        else:
            self.exits.append(record)

    def record_equity(self, ts: int, equity: float) -> None:
        self.equity_curve.append((ts, equity))


class BacktestRunner:
    """
    Event-driven backtest runner yang menggunakan production TradingEngine stack.

    Perbedaan dari live:
    - _bootstrap_complete di-set manual (tidak perlu REST bootstrap)
    - Untuk setiap candle, kita simulate tick dengan high & low
      agar SL/TP intra-candle bisa kena (tidak hanya di close)
    - DB writer tidak dijalankan (tidak ingin polusi DB production)
    - Walk-forward evaluator tidak dijalankan (bobot strategy statis)
    """

    def __init__(self) -> None:
        self.engine = TradingEngine()
        self.ledger = BacktestLedger()
        self.candles_processed = 0
        self._patch_broker()

    def _patch_broker(self) -> None:
        """Intercept setiap fill dari paper broker ke ledger kita."""
        original_submit = self.engine.paper_broker.submit

        async def patched_submit(intent, price, order_type="MARKET"):
            fill = await original_submit(intent, price=price, order_type=order_type)
            if fill is not None:
                self.ledger.record_fill(fill, candle_time=self._current_candle_time)
            return fill

        self.engine.paper_broker.submit = patched_submit
        self._current_candle_time: int = 0

    @staticmethod
    def load_csv(path: str | Path, *, symbol: str, timeframe: str) -> list[Candle]:
        """
        Load CSV dalam format Binance.

        Mendukung dua format:
        A) Dengan header row  → gunakan nama kolom
        B) Tanpa header row   → assume urutan kolom Binance standar
        """
        candles: list[Candle] = []
        path = Path(path)

        with path.open(newline="") as fh:
            raw_sample = fh.read(512)
            fh.seek(0)

            # Deteksi apakah ada header
            first_token = raw_sample.split(",")[0].strip().lower()
            has_header = not first_token.lstrip("-").isdigit()

            if has_header:
                reader = csv.DictReader(fh)
            else:
                reader = csv.DictReader(fh, fieldnames=_BINANCE_COLS)

            for row in reader:
                try:
                    # Normalisasi nama kolom (Binance kadang pakai taker_buy_vol)
                    taker_buy = (
                        float(row.get("taker_buy_volume") or row.get("taker_buy_vol") or 0)
                    )
                    quote_vol = (
                        float(row.get("quote_volume") or 0)
                        or float(row.get("close", 0)) * float(row.get("volume", 0))
                    )
                    open_time = int(
                        float(row.get("open_time") or row.get("timestamp") or 0)
                    )

                    candles.append(
                        Candle(
                            symbol=symbol.upper(),
                            timeframe=timeframe,
                            open_time=open_time,
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            volume=float(row.get("volume") or 0),
                            quote_volume=quote_vol,
                            trades=int(row["count"]) if row.get("count") else None,
                            taker_buy_vol=taker_buy if taker_buy else None,
                            is_closed=True,
                        )
                    )
                except (ValueError, KeyError) as exc:
                    logger.warning("Skip baris tidak valid: %s | error: %s", dict(row), exc)

        logger.info("Loaded %d candles dari %s", len(candles), path.name)
        return candles

    async def run(self, candles: Iterable[Candle]) -> dict:
        started = time.perf_counter()

        # ── FIX #1: set bootstrap sebelum loop ────────────────────────────────
        # Tanpa ini semua candle di-skip di gate bootstrap di _on_candle_closed
        self.engine._bootstrap_complete.set()

        ordered = sorted(
            candles,
            key=lambda c: (c.open_time, c.symbol, c.timeframe),
        )

        for candle in ordered:
            self._current_candle_time = candle.open_time

            # Append ke market store agar indicator pipeline punya history
            self.engine.market_store.append(candle)

            # ── FIX #2: simulasi intra-candle wick ────────────────────────────
            # Di live, _on_tick dipanggil setiap forming candle.
            # Di backtest kita tidak punya tick stream, jadi kita simulate dengan
            # high dan low candle. Urutan: high dulu lalu low (atau sebaliknya)
            # tergantung apakah kamu curiga candle adalah up/down candle.
            # Konvensi umum backtest: cek low dulu untuk LONG (worst case),
            # high dulu untuk SHORT (worst case) — lebih konservatif.
            #
            # Kita pakai pendekatan sederhana: always high → low
            # untuk tick interval (tidak memodelkan urutan sebenarnya)
            if self.engine.auto_manage_positions:
                await self.engine._on_tick(candle.symbol, candle.high, candle.timeframe)
                await self.engine._on_tick(candle.symbol, candle.low, candle.timeframe)

            # Proses candle closed (indicator + strategy + risk + order)
            await self.engine._on_candle_closed(candle)

            # Rekam equity setelah setiap candle
            summary = self.engine.portfolio_manager.summary()
            self.ledger.record_equity(candle.open_time, summary["total_equity"])

            self.candles_processed += 1

        elapsed = time.perf_counter() - started

        # Build summary dari portfolio manager + ledger
        pm_summary = self.engine.portfolio_manager.summary()
        result = {
            **pm_summary,
            "candles_processed": self.candles_processed,
            "elapsed_sec": round(elapsed, 3),
            "candles_per_sec": round(self.candles_processed / elapsed if elapsed else 0.0, 1),
            "fills_total": len(self.engine.paper_broker.fills),
            "signals_total": len(self.engine.portfolio_manager.journal.entries),
            "equity_curve": self.ledger.equity_curve,
            "fills_ledger": {
                "entries": self.ledger.entries,
                "exits": self.ledger.exits,
            },
            # Untuk per-strategy metrics dari journal
            "journal_entries": [
                {
                    "strategy_id": e.signal.strategy_id if hasattr(e, "signal") else "unknown",
                    "symbol": e.signal.symbol if hasattr(e, "signal") else "",
                    "direction": e.signal.direction if hasattr(e, "signal") else "",
                    "confidence": e.signal.confidence if hasattr(e, "signal") else 0.0,
                    "market_regime": e.signal.market_regime if hasattr(e, "signal") else "",
                    "fill_price": e.fill.avg_price if hasattr(e, "fill") and e.fill else None,
                    "fill_side": e.fill.side if hasattr(e, "fill") and e.fill else None,
                    "fee": e.fill.fee if hasattr(e, "fill") and e.fill else 0.0,
                }
                for e in self.engine.portfolio_manager.journal.entries
                if e is not None
            ],
        }

            # ========== ADD THESE 4 LINES HERE ==========
        print("Total fills:", len(self.engine.paper_broker.fills))
        print("Still open:", len(self.engine.portfolio_manager.position_tracker.open_positions()))
        print("Realized PnL:", self.engine.portfolio_manager.realized_pnl_total)
        print("Open positions:", len(self.engine.portfolio_manager.position_tracker.open_positions()))
        print("Closed positions:", len(self.engine.portfolio_manager.position_tracker.closed))
        for p in self.engine.portfolio_manager.position_tracker.closed:
            print(p.symbol, p.side, p.entry_price, "→", p.exit_price, "pnl=", p.realized_pnl)
        # ============================================

        logger.info("Backtest selesai: %d candles, %.1fs", self.candles_processed, elapsed)
        return result

    def run_sync(self, candles: Iterable[Candle]) -> dict:
        return asyncio.run(self.run(candles))


async def run_csv(
    path: str | Path,
    *,
    symbol: str,
    timeframe: str,
) -> dict:
    runner = BacktestRunner()
    candles = runner.load_csv(path, symbol=symbol, timeframe=timeframe)
    return await runner.run(candles)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.WARNING,   # suppress noise dari engine saat backtest
        format="%(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Backtest offline dari CSV")
    parser.add_argument("csv_path", type=Path, help="Path ke file CSV atau folder")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument(
        "--report",
        choices=["summary", "full"],
        default="full",
        help="'summary' = ringkasan saja, 'full' = termasuk trade list",
    )
    args = parser.parse_args()

    result = asyncio.run(
        run_csv(args.csv_path, symbol=args.symbol, timeframe=args.timeframe)
    )

    report = BacktestReport(result, symbol=args.symbol, timeframe=args.timeframe)
    report.print(mode=args.report)

