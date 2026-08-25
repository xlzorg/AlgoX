"""
take_profit.py

BUG FIXED: Same as stop_loss.py — calculate_targets() was defined twice.
The second definition overwrote the first. Cleaned up to single definitions.
"""


def target_price(entry_price: float, side: str, distance_pct: float) -> float:
    """
    Simple percentage-based target price.
    side='buy'  → target above entry
    side='sell' → target below entry
    """
    multiplier = 1 + distance_pct / 100 if side.lower() == "buy" else 1 - distance_pct / 100
    return entry_price * multiplier


def calculate_targets(
    entry_price: float,
    stop_price: float,
    side: str,
    tp1_r: float = 1.5,
    tp2_r: float = 2.5,
) -> tuple[float, float]:
    """
    R-multiple take profit levels.
    risk = |entry - stop|
    BUY:  TP above entry  (+risk × R)
    SELL: TP below entry  (-risk × R)
    Returns (tp1_price, tp2_price).
    """
    risk = abs(entry_price - stop_price)
    sign = 1 if side.upper() in {"BUY", "LONG"} else -1
    return (
        entry_price + sign * risk * tp1_r,
        entry_price + sign * risk * tp2_r,
    )