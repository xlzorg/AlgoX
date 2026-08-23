from __future__ import annotations

import pandas as pd


def regime_analysis(records: list[dict]) -> dict[str, dict[str, float | int]]:
        if not records:
            return {}
        frame = pd.DataFrame(records)
        grouped = frame.groupby(frame["market_regime"].fillna("UNKNOWN"))
        return {str(regime): {"trades": int(group["pnl_pct"].count()), "avg_pnl_pct": float(group["pnl_pct"].mean()), "total_pnl_usdt": float(group.get("pnl_usdt", pd.Series(dtype=float)).sum()), "win_rate": float((group["pnl_pct"] > 0).mean())} for regime, group in grouped}
