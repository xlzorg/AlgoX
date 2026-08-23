from __future__ import annotations

import json
from typing import Iterable

import pandas as pd

from analytics.performance_stats import compute_indicator_correlation


def indicator_correlation(records: Iterable[dict], target_col: str = "pnl_pct") -> dict[str, float]:
        rows = []
        for record in records:
            snapshot = record.get("indicator_snapshot", {})
            if isinstance(snapshot, str):
                try:
                    snapshot = json.loads(snapshot)
                except json.JSONDecodeError:
                    snapshot = {}
            rows.append({**snapshot, target_col: record.get(target_col)})
        if not rows:
            return {}
        return {key: float(value) for key, value in compute_indicator_correlation(pd.DataFrame(rows), target_col).dropna().items()}
