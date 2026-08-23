import numpy as np
import pandas as pd

from analytics.indicator_correlation import indicator_correlation
from analytics.performance_stats import compute_expectancy, compute_max_drawdown, compute_sharpe, compute_sortino
from analytics.trade_distribution import trade_distribution


def test_sharpe_matches_vectorized_reference() -> None:
    returns = [0.01, 0.02, 0.015, 0.025]
    expected = np.mean(returns) / np.std(returns, ddof=1) * np.sqrt(252)
    assert np.isclose(compute_sharpe(returns), expected)


def test_sortino_uses_downside_standard_deviation() -> None:
    returns = [-0.02, -0.01, 0.01, 0.02]
    downside = np.std([-0.02, -0.01], ddof=1)
    expected = np.mean(returns) / downside * np.sqrt(252)
    assert np.isclose(compute_sortino(returns), expected)


def test_max_drawdown_tracks_peak_trough_and_recovery() -> None:
    result = compute_max_drawdown([100, 120, 90, 100, 120])
    assert result == {"max_drawdown_pct": -0.25, "peak_idx": 1, "trough_idx": 2, "recovery_bars": 2}


def test_expectancy_and_distribution() -> None:
    assert np.isclose(compute_expectancy([0.10, 0.20], [-0.05, -0.10]), 0.0375)
    result = trade_distribution([-0.01, 0.01, 0.02], bucket_size=0.01)
    assert result["count"] == 3
    assert result["wins"] == 2
    assert result["skewness"] < 0


def test_indicator_correlation_from_json_snapshots() -> None:
    records = [
        {"indicator_snapshot": '{"rsi_14": 1, "atr_14": 3}', "pnl_pct": 1},
        {"indicator_snapshot": '{"rsi_14": 2, "atr_14": 2}', "pnl_pct": 2},
        {"indicator_snapshot": '{"rsi_14": 3, "atr_14": 1}', "pnl_pct": 3},
    ]
    result = indicator_correlation(records)
    assert np.isclose(result["rsi_14"], 1.0)
    assert np.isclose(result["atr_14"], -1.0)
