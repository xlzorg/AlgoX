"""
backtest_report.py — Terminal reporter untuk hasil backtest.

Menampilkan:
1. Header ringkasan (equity, return, drawdown, Sharpe)
2. Equity curve ASCII di terminal
3. Drawdown chart ASCII
4. Per-strategy breakdown (win rate, Sharpe, avg confidence)
5. Trade list (mode full)

Tidak ada dependency external selain stdlib + numpy.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


# ── ANSI colors (fallback graceful jika terminal tidak support) ────────────────
class _C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    GREEN  = "\033[92m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    WHITE  = "\033[97m"
    DIM    = "\033[2m"
    BLUE   = "\033[94m"


def _color(text: str, *codes: str) -> str:
    return "".join(codes) + str(text) + _C.RESET


def _pct(v: float, decimals: int = 2) -> str:
    sign = "+" if v >= 0 else ""
    col = _C.GREEN if v >= 0 else _C.RED
    return _color(f"{sign}{v:.{decimals}f}%", col)


def _money(v: float) -> str:
    return f"${v:,.2f}"


# ── ASCII chart helpers ────────────────────────────────────────────────────────
_CHART_WIDTH  = 80
_CHART_HEIGHT = 12
_SPARK_CHARS  = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"]


def _sparkline(values: list[float], width: int = _CHART_WIDTH) -> str:
    """Single-line sparkline dari list of values."""
    if not values:
        return ""
    lo, hi = min(values), max(values)
    span = hi - lo or 1.0
    # Downsample jika lebih lebar dari width
    if len(values) > width:
        step = len(values) / width
        values = [values[int(i * step)] for i in range(width)]
    chars = []
    for v in values:
        idx = int((v - lo) / span * (len(_SPARK_CHARS) - 1))
        chars.append(_SPARK_CHARS[idx])
    return "".join(chars)


def _block_chart(
    values: list[float],
    *,
    width: int = _CHART_WIDTH,
    height: int = _CHART_HEIGHT,
    label: str = "",
    color_positive: bool = True,
) -> str:
    """
    Multi-baris block chart (vertical bars).
    Negatif values → merah, positif → hijau.
    """
    if not values:
        return "(tidak ada data)"

    lo, hi = min(values), max(values)
    # Pastikan 0 selalu ada di range
    lo = min(lo, 0.0)
    hi = max(hi, 0.0)
    span = hi - lo or 1.0

    # Downsample
    if len(values) > width:
        step = len(values) / width
        values = [values[int(i * step)] for i in range(width)]

    n = len(values)
    rows: list[list[str]] = [[" "] * n for _ in range(height)]

    zero_row = int((hi / span) * (height - 1))

    for col_i, v in enumerate(values):
        bar_top = int(((v - lo) / span) * (height - 1))
        bar_zero = zero_row
        top    = height - 1 - max(bar_top, bar_zero)
        bottom = height - 1 - min(bar_top, bar_zero)
        char   = "█"
        col    = _C.GREEN if v >= 0 else _C.RED
        for r in range(top, bottom + 1):
            rows[r][col_i] = _color(char, col) if color_positive else char

    lines = []
    if label:
        lines.append(_color(f" {label}", _C.CYAN, _C.BOLD))

    # Y-axis labels
    y_labels = [
        f"{hi:>8.1f}",
        *["        "] * (height // 2 - 1),
        f"{(hi+lo)/2:>8.1f}",
        *["        "] * (height // 2 - 1),
        f"{lo:>8.1f}",
    ]
    for i, row in enumerate(rows):
        y_lbl = y_labels[i] if i < len(y_labels) else "        "
        lines.append(_color(y_lbl, _C.DIM) + " │" + "".join(row))

    lines.append("        " + " └" + "─" * n)
    lines.append("        " + "  " + _color(f"0", _C.DIM) + " " * (n // 2 - 2) + _color(f"{n}", _C.DIM))
    return "\n".join(lines)


# ── Kalkulasi metrics ──────────────────────────────────────────────────────────

def _compute_equity_metrics(equity_curve: list[tuple[int, float]]) -> dict:
    if len(equity_curve) < 2:
        return {}

    equities = [e for _, e in equity_curve]
    initial  = equities[0]
    final    = equities[-1]

    # Returns per candle
    returns = [
        (equities[i] - equities[i - 1]) / equities[i - 1]
        for i in range(1, len(equities))
        if equities[i - 1] != 0
    ]

    # Sharpe ratio (annualized, assume 1h candles → 8760 candles/year)
    if returns:
        avg_r = sum(returns) / len(returns)
        std_r = math.sqrt(sum((r - avg_r) ** 2 for r in returns) / len(returns)) or 1e-9
        sharpe = (avg_r / std_r) * math.sqrt(8760)
    else:
        avg_r = std_r = sharpe = 0.0

    # Max drawdown
    peak = initial
    max_dd = 0.0
    dd_series = []
    for eq in equities:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
        dd_series.append(-dd * 100)   # negatif untuk chart

    total_return_pct = (final - initial) / initial * 100 if initial else 0.0

    return {
        "initial_equity": initial,
        "final_equity": final,
        "total_return_pct": total_return_pct,
        "sharpe": sharpe,
        "max_drawdown_pct": max_dd * 100,
        "equities": equities,
        "drawdown_series": dd_series,
        "avg_return_per_candle": avg_r * 100,
        "volatility_pct": std_r * 100,
    }


def _compute_strategy_metrics(journal_entries: list[dict]) -> dict[str, dict]:
    """
    Per-strategy metrics dari journal entries.

    Win/loss ditentukan dengan mencocokkan entry-exit berdasarkan urutan
    (FIFO matching sederhana per symbol per strategy).
    """
    # Group entries by strategy
    by_strat: dict[str, list[dict]] = defaultdict(list)
    for e in journal_entries:
        by_strat[e.get("strategy_id", "unknown")].append(e)

    result: dict[str, dict] = {}
    for strat_id, entries in by_strat.items():
        buy_prices: list[float]  = []
        sell_prices: list[float] = []
        confidences: list[float] = []
        pnls: list[float]        = []
        regimes: dict[str, int]  = defaultdict(int)

        for e in entries:
            side = (e.get("fill_side") or "").upper()
            px   = e.get("fill_price") or 0.0
            conf = e.get("confidence") or 0.0
            reg  = e.get("market_regime") or "UNKNOWN"

            confidences.append(conf)
            regimes[reg] += 1

            if side in ("BUY", "LONG"):
                buy_prices.append(px)
            elif side in ("SELL", "SHORT") and buy_prices:
                entry_px = buy_prices.pop(0)
                if entry_px > 0:
                    pnl_pct = (px - entry_px) / entry_px * 100
                    pnls.append(pnl_pct)
                    sell_prices.append(px)

        total_trades = len(pnls)
        wins  = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        win_rate = len(wins) / total_trades * 100 if total_trades else 0.0
        avg_win  = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        profit_factor = (
            abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")
        )

        # Sharpe per trade
        if pnls:
            avg_pnl = sum(pnls) / len(pnls)
            std_pnl = math.sqrt(sum((p - avg_pnl) ** 2 for p in pnls) / len(pnls)) or 1e-9
            sharpe_trade = avg_pnl / std_pnl
        else:
            sharpe_trade = 0.0

        result[strat_id] = {
            "total_signals": len(entries),
            "total_trades": total_trades,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": win_rate,
            "avg_win_pct": avg_win,
            "avg_loss_pct": avg_loss,
            "profit_factor": profit_factor,
            "sharpe_per_trade": sharpe_trade,
            "avg_confidence": sum(confidences) / len(confidences) if confidences else 0.0,
            "top_regime": max(regimes, key=regimes.get) if regimes else "N/A",
            "total_pnl_pct": sum(pnls),
        }

    return result


# ── BacktestReport ─────────────────────────────────────────────────────────────

class BacktestReport:
    """Render backtest result ke terminal."""

    def __init__(self, result: dict[str, Any], *, symbol: str, timeframe: str) -> None:
        self.result    = result
        self.symbol    = symbol
        self.timeframe = timeframe
        self._eq       = _compute_equity_metrics(result.get("equity_curve", []))
        self._strat    = _compute_strategy_metrics(result.get("journal_entries", []))

    # ── public ────────────────────────────────────────────────────────────────

    def print(self, mode: str = "full") -> None:
        print()
        self._print_header()
        self._print_equity_summary()
        self._print_equity_chart()
        self._print_drawdown_chart()
        self._print_strategy_table()
        if mode == "full":
            self._print_trade_list()
        self._print_footer()

    # ── sections ──────────────────────────────────────────────────────────────

    def _print_header(self) -> None:
        w = 82
        title = f"  BACKTEST REPORT — {self.symbol} {self.timeframe}  "
        pad   = (w - len(title)) // 2
        print(_color("═" * w, _C.CYAN))
        print(_color(" " * pad + title + " " * pad, _C.WHITE, _C.BOLD))
        print(_color("═" * w, _C.CYAN))

    def _print_equity_summary(self) -> None:
        eq = self._eq
        r  = self.result

        n_candles = r.get("candles_processed", 0)
        n_fills   = r.get("fills_total", 0)
        n_signals = r.get("signals_total", 0)
        elapsed   = r.get("elapsed_sec", 0.0)
        cps       = r.get("candles_per_sec", 0.0)

        balance   = r.get("balance_usdt", 0.0)
        positions = r.get("open_positions", 0)

        ret_pct   = eq.get("total_return_pct", 0.0)
        sharpe    = eq.get("sharpe", 0.0)
        max_dd    = eq.get("max_drawdown_pct", 0.0)
        init_eq   = eq.get("initial_equity", 0.0)
        final_eq  = eq.get("final_equity", 0.0)
        vol       = eq.get("volatility_pct", 0.0)

        print()
        print(_color("  ▶ RINGKASAN EKSEKUSI", _C.BOLD, _C.YELLOW))
        print(f"    Candles diproses : {n_candles:,}  ({cps:.0f} candle/detik, total {elapsed:.1f}s)")
        print(f"    Signals generated: {n_signals:,}")
        print(f"    Fills (orders)   : {n_fills:,}")
        print(f"    Posisi masih open: {positions}")
        print(f"    Saldo akhir USDT : {_money(balance)}")
        print()
        print(_color("  ▶ PERFORMA EQUITY", _C.BOLD, _C.YELLOW))
        print(f"    Equity awal      : {_money(init_eq)}")
        print(f"    Equity akhir     : {_money(final_eq)}")
        print(f"    Total return     : {_pct(ret_pct)}")
        print(f"    Sharpe ratio     : {_color(f'{sharpe:+.3f}', _C.GREEN if sharpe >= 0 else _C.RED)}")
        print(f"    Max drawdown     : {_color(f'-{max_dd:.2f}%', _C.RED)}")
        print(f"    Volatilitas      : {vol:.4f}% per candle")

    def _print_equity_chart(self) -> None:
        equities = self._eq.get("equities", [])
        if not equities:
            return
        print()
        print(_color("  ▶ EQUITY CURVE", _C.BOLD, _C.YELLOW))
        print(_block_chart(equities, label="Equity (USDT)", color_positive=True))
        print()
        print("    Sparkline: " + _sparkline(equities, width=70))

    def _print_drawdown_chart(self) -> None:
        dd = self._eq.get("drawdown_series", [])
        if not dd:
            return
        print()
        print(_color("  ▶ DRAWDOWN", _C.BOLD, _C.YELLOW))
        print(_block_chart(dd, label="Drawdown (%)", color_positive=False))

    def _print_strategy_table(self) -> None:
        if not self._strat:
            print()
            print(_color("  ⚠  Tidak ada journal entries — periksa apakah ada trades.", _C.YELLOW))
            return

        print()
        print(_color("  ▶ PER-STRATEGY BREAKDOWN", _C.BOLD, _C.YELLOW))
        print()

        # Header
        col_w = [22, 8, 8, 10, 10, 10, 10, 10, 12, 12]
        headers = [
            "Strategy", "Signals", "Trades", "Win%", "AvgWin",
            "AvgLoss", "PF", "Sharpe", "Confidence", "Regime",
        ]
        header_line = "  "
        for h, w in zip(headers, col_w):
            header_line += _color(h.ljust(w), _C.CYAN, _C.BOLD)
        print(header_line)
        print("  " + _color("─" * sum(col_w), _C.DIM))

        for strat_id, m in sorted(self._strat.items()):
            win_rate = m["win_rate_pct"]
            sharpe   = m["sharpe_per_trade"]
            pf       = m["profit_factor"]
            pf_str   = f"{pf:.2f}" if pf != float("inf") else "∞"

            win_col  = _C.GREEN if win_rate >= 50 else _C.RED
            shr_col  = _C.GREEN if sharpe >= 0 else _C.RED
            pf_col   = _C.GREEN if pf >= 1.0 else _C.RED

            row = "  "
            row += strat_id[:21].ljust(col_w[0])
            row += str(m["total_signals"]).ljust(col_w[1])
            row += str(m["total_trades"]).ljust(col_w[2])
            row += _color(f"{win_rate:.1f}%".ljust(col_w[3]), win_col)
            row += _color(f"+{m['avg_win_pct']:.2f}%".ljust(col_w[4]), _C.GREEN)
            row += _color(f"{m['avg_loss_pct']:.2f}%".ljust(col_w[5]), _C.RED)
            row += _color(pf_str.ljust(col_w[6]), pf_col)
            row += _color(f"{sharpe:+.3f}".ljust(col_w[7]), shr_col)
            row += f"{m['avg_confidence']:.3f}".ljust(col_w[8])
            row += m["top_regime"][:11].ljust(col_w[9])
            print(row)

        print("  " + _color("─" * sum(col_w), _C.DIM))

        # Total row
        all_trades = sum(m["total_trades"] for m in self._strat.values())
        all_wins   = sum(m["wins"] for m in self._strat.values())
        total_wr   = all_wins / all_trades * 100 if all_trades else 0.0
        total_pnl  = sum(m["total_pnl_pct"] for m in self._strat.values())

        print(
            "  " +
            _color("TOTAL".ljust(col_w[0]), _C.BOLD) +
            _color(str(sum(m["total_signals"] for m in self._strat.values())).ljust(col_w[1]), _C.BOLD) +
            _color(str(all_trades).ljust(col_w[2]), _C.BOLD) +
            _color(f"{total_wr:.1f}%".ljust(col_w[3]), _C.GREEN if total_wr >= 50 else _C.RED, _C.BOLD) +
            "".ljust(sum(col_w[4:])) +
            _color(f"  Σ PnL: {_pct(total_pnl)}", _C.BOLD)
        )

        # Insight otomatis
        print()
        print(_color("  ▶ INSIGHT OTOMATIS", _C.BOLD, _C.YELLOW))
        self._print_insights()

    def _print_insights(self) -> None:
        eq     = self._eq
        strats = self._strat

        sharpe = eq.get("sharpe", 0.0)
        dd     = eq.get("max_drawdown_pct", 0.0)
        ret    = eq.get("total_return_pct", 0.0)

        insights: list[str] = []

        # Equity-level insights
        if sharpe < 0:
            insights.append(f"❌  Sharpe negatif ({sharpe:.3f}) — strategi merugi secara risk-adjusted. "
                            f"Return tidak cukup mengkompensasi volatilitas.")
        elif sharpe < 0.5:
            insights.append(f"⚠   Sharpe rendah ({sharpe:.3f}) — return ada tapi tidak efisien. "
                            f"Coba perketat threshold confidence atau filter market regime.")
        elif sharpe >= 1.5:
            insights.append(f"✅  Sharpe tinggi ({sharpe:.3f}) — performa risk-adjusted sangat baik.")
        else:
            insights.append(f"✅  Sharpe wajar ({sharpe:.3f}) — model bekerja dengan cukup efisien.")

        if dd > 30:
            insights.append(f"❌  Max drawdown sangat dalam ({dd:.1f}%) — risiko ruin tinggi. "
                            f"Pertimbangkan perketat RiskGuard (reduce position size atau tighten SL).")
        elif dd > 15:
            insights.append(f"⚠   Max drawdown {dd:.1f}% — dalam batas toleransi tapi perlu dimonitor. "
                            f"Pastikan SL aktif pada setiap posisi.")
        else:
            insights.append(f"✅  Max drawdown terkontrol ({dd:.1f}%).")

        if ret < 0:
            insights.append(f"❌  Total return negatif ({ret:.2f}%) — model secara keseluruhan merugi.")
        else:
            insights.append(f"✅  Total return positif ({ret:.2f}%).")

        # Per-strategy insights
        for sid, m in strats.items():
            wr = m["win_rate_pct"]
            pf = m["profit_factor"]
            if m["total_trades"] < 5:
                insights.append(f"⚠   [{sid}] Hanya {m['total_trades']} trade — "
                                f"sample terlalu kecil untuk kesimpulan statistik.")
            elif wr < 40:
                insights.append(f"❌  [{sid}] Win rate rendah ({wr:.1f}%) — "
                                f"strategi ini sering salah. Coba naikkan minimum confidence threshold.")
            elif wr >= 60:
                insights.append(f"✅  [{sid}] Win rate tinggi ({wr:.1f}%).")

            if pf != float("inf") and pf < 1.0 and m["total_trades"] >= 5:
                insights.append(f"❌  [{sid}] Profit factor < 1 ({pf:.2f}) — "
                                f"loss total lebih besar dari profit total.")

        for ins in insights:
            print(f"    {ins}")

    def _print_trade_list(self) -> None:
        entries_raw = self.result.get("fills_ledger", {}).get("entries", [])
        exits_raw   = self.result.get("fills_ledger", {}).get("exits", [])

        if not entries_raw and not exits_raw:
            return

        print()
        print(_color("  ▶ TRADE LIST (max 30 trades terbaru)", _C.BOLD, _C.YELLOW))
        print()

        # Match entry-exit FIFO sederhana
        entry_q: list[dict] = list(entries_raw)
        trades: list[dict]  = []

        for ex in exits_raw:
            if entry_q:
                en = entry_q.pop(0)
                pnl_pct = (ex["price"] - en["price"]) / en["price"] * 100 if en["price"] else 0.0
                trades.append({
                    "symbol": ex["symbol"],
                    "entry_price": en["price"],
                    "exit_price": ex["price"],
                    "qty": en["qty"],
                    "pnl_pct": pnl_pct,
                    "fee": en["fee"] + ex["fee"],
                    "slippage": ex.get("slippage_pct", 0.0),
                    "open_time": en["candle_open_time"],
                    "close_time": ex["candle_open_time"],
                })

        # Print header tabel
        hdr = (
            f"  {'#':>3}  {'Symbol':<10} {'Entry':>10} {'Exit':>10} "
            f"{'Qty':>10} {'PnL':>8} {'Fee':>8} {'Slip':>7}"
        )
        print(_color(hdr, _C.DIM))
        print("  " + _color("─" * 75, _C.DIM))

        recent = trades[-30:]
        for i, t in enumerate(recent, 1):
            pnl_pct = t["pnl_pct"]
            col = _C.GREEN if pnl_pct >= 0 else _C.RED
            sign = "+" if pnl_pct >= 0 else ""
            print(
                f"  {i:>3}  {t['symbol']:<10} "
                f"${t['entry_price']:>9,.2f} "
                f"${t['exit_price']:>9,.2f} "
                f"{t['qty']:>10.4f} "
                + _color(f"{sign}{pnl_pct:>7.2f}%", col) +
                f" {t['fee']:>8.4f} "
                f"{t['slippage']:>6.4f}%"
            )

        print("  " + _color("─" * 75, _C.DIM))

        # Summary row
        if trades:
            total_pnl = sum(t["pnl_pct"] for t in trades)
            total_fee = sum(t["fee"] for t in trades)
            avg_slip  = sum(t["slippage"] for t in trades) / len(trades)
            print(
                f"  {'':>3}  {'TOTAL':<10} {'':>10} {'':>10} {'':>10} " +
                _color(f"{'+' if total_pnl >= 0 else ''}{total_pnl:>7.2f}%", _C.GREEN if total_pnl >= 0 else _C.RED, _C.BOLD) +
                f" {total_fee:>8.4f} "
                f"{avg_slip:>6.4f}%"
            )

    def _print_footer(self) -> None:
        print()
        print(_color("═" * 82, _C.CYAN))
        print(_color("  Gunakan insight di atas untuk tune parameter di RiskGuard, strategy threshold,", _C.DIM))
        print(_color("  dan confidence minimum sebelum deploy ke live trading.", _C.DIM))
        print(_color("═" * 82, _C.CYAN))
        print()