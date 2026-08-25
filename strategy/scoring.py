# strategy/scoring.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Mapping

@dataclass(frozen=True, slots=True)
class IndicatorScore:
    name: str
    score: float          # [-1.0, +1.0]
    weight: float         # relative importance

def clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))

def linear_score(value: float | None, *, center: float, scale: float, invert: bool = False) -> float:
    """Map a raw indicator value to [-1, +1] around a center point."""
    if value is None:
        return 0.0
    raw = (value - center) / scale
    if invert:
        raw = -raw
    return clamp(raw)

def threshold_score(
    value: float | None,
    *,
    bull_threshold: float,
    bear_threshold: float,
    max_score: float = 1.0,
) -> float:
    """Simple three-zone scorer (useful for RSI-style indicators)."""
    if value is None:
        return 0.0
    if value >= bull_threshold:
        return max_score
    if value <= bear_threshold:
        return -max_score
    # linear interpolation between the two thresholds
    mid = (bull_threshold + bear_threshold) / 2
    span = (bull_threshold - bear_threshold) / 2
    return clamp((value - mid) / span)