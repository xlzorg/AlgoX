from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd


def trade_distribution(returns: Sequence[float], bucket_size: float = 0.005) -> dict:
        series = pd.Series(returns, dtype=float)
        buckets = (np.round(series / bucket_size) * bucket_size).value_counts().sort_index()
        return {"count": int(series.size), "wins": int((series > 0).sum()), "skewness": float(series.skew()) if len(series) > 2 else 0.0, "kurtosis": float(series.kurt()) if len(series) > 3 else 0.0, "fat_tail_ratio": float((series.abs() > series.abs().quantile(0.95)).mean()) if len(series) else 0.0, "buckets": [{"bucket": float(key), "count": int(value)} for key, value in buckets.items()]}
