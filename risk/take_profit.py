def target_price(entry_price: float, side: str, distance_pct: float) -> float:
    multiplier = 1 + distance_pct / 100 if side.lower() == "buy" else 1 - distance_pct / 100
    return entry_price * multiplier


def calculate_targets(entry_price: float, stop_price: float, side: str, tp1_r: float = 1.5, tp2_r: float = 2.5) -> tuple[float, float]:
    risk = abs(entry_price - stop_price)
    sign = 1 if side.upper() in {"BUY", "LONG"} else -1
    return entry_price + sign * risk * tp1_r, entry_price + sign * risk * tp2_r
    
def calculate_targets(entry_price: float, stop_price: float, side: str, tp1_r: float = 1.5, tp2_r: float = 2.5) -> tuple[float, float]:
    risk = abs(entry_price - stop_price)
    sign = 1 if side.upper() in {"BUY", "LONG"} else -1
    return entry_price + sign * risk * tp1_r, entry_price + sign * risk * tp2_r
