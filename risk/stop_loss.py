"""
stop_loss.py

BUG FIXED: The original file defined calculate_stop_loss() TWICE (lines 6-8 and
10-12 were identical). In Python the second definition silently overwrites the
first — harmless here since they were identical, but it indicates the AI agent
ran a patch that appended a duplicate instead of replacing the function.
Cleaned up to a single definition per function.
"""


def stop_price(entry_price: float, side: str, distance_pct: float) -> float:
    """
    Simple percentage-based stop price.
    side='buy'  → stop below entry
    side='sell' → stop above entry
    """
    multiplier = 1 - distance_pct / 100 if side.lower() == "buy" else 1 + distance_pct / 100
    return entry_price * multiplier


def calculate_stop_loss(
    entry_price: float,
    atr: float,
    side: str,
    multiplier: float = 1.5,
) -> float:
    """
    ATR-based stop loss price.
    BUY / LONG  → stop is below entry  (entry - atr × multiplier)
    SELL / SHORT → stop is above entry (entry + atr × multiplier)
    """
    distance = atr * multiplier
    return entry_price - distance if side.upper() in {"BUY", "LONG"} else entry_price + distance