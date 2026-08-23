from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd


def compute_sharpe(returns: Sequence[float], risk_free: float = 0.0, periods_per_year: int = 252) -> float:
        series = pd.Series(returns, dtype=float)
        excess = series - risk_free / periods_per_year
        deviation = excess.std()
        return float(excess.mean() / deviation * np.sqrt(periods_per_year)) if deviation > 0 else 0.0


def compute_sortino(returns: Sequence[float], risk_free: float = 0.0, periods_per_year: int = 252) -> float:
        series = pd.Series(returns, dtype=float)
        excess = series - risk_free / periods_per_year
        downside = excess[excess < 0].std()
        return float(excess.mean() / downside * np.sqrt(periods_per_year)) if downside is not None and downside > 0 else 0.0


def compute_max_drawdown(equity_series: Sequence[float]) -> dict[str, float | int | None]:
        equity = pd.Series(equity_series, dtype=float)
        if equity.empty:
            return {"max_drawdown_pct": 0.0, "peak_idx": None, "trough_idx": None, "recovery_bars": None}
        peak = equity.cummax()
        drawdown = (equity - peak) / peak.replace(0, np.nan)
        trough_idx = int(drawdown.idxmin())
        peak_idx = int(equity.iloc[: trough_idx + 1].idxmax())
        recovery = equity.iloc[trough_idx:]
        recovered = recovery[recovery >= peak.iloc[trough_idx]]
        recovery_bars = int(recovered.index[0] - trough_idx) if not recovered.empty else None
        return {"max_drawdown_pct": float(drawdown.min()), "peak_idx": peak_idx, "trough_idx": trough_idx, "recovery_bars": recovery_bars}


def compute_expectancy(wins: Sequence[float], losses: Sequence[float]) -> float:
        total = len(wins) + len(losses)
        if total == 0:
            return 0.0
        return float(len(wins) / total * (np.mean(wins) if wins else 0.0) + len(losses) / total * (np.mean(losses) if losses else 0.0))


def compute_rolling_sharpe(daily_returns: pd.Series, window: int = 30) -> pd.Series:
        return daily_returns.rolling(window).mean() / daily_returns.rolling(window).std() * np.sqrt(252)


def compute_indicator_correlation(df: pd.DataFrame, target_col: str = "pnl_pct") -> pd.Series:
        if target_col not in df:
            return pd.Series(dtype=float)
        numeric = df.select_dtypes(include=[float, int]).drop(columns=[target_col], errors="ignore")
        return numeric.corrwith(df[target_col]).sort_values(ascending=False)


def performance_stats(returns: Sequence[float]) -> dict[str, float]:
    return {"sharpe": compute_sharpe(returns), "sortino": compute_sortino(returns), "calmar": 0.0, "max_drawdown": 0.0}
