def stop_price(entry_price: float, side: str, distance_pct: float) -> float:
    multiplier = 1 - distance_pct / 100 if side.lower() == "buy" else 1 + distance_pct / 100
    return entry_price * multiplier


def calculate_stop_loss(entry_price: float, atr: float, side: str, multiplier: float = 1.5) -> float:
    distance = atr * multiplier
    return entry_price - distance if side.upper() in {"BUY", "LONG"} else entry_price + distance
    
def calculate_stop_loss(entry_price: float, atr: float, side: str, multiplier: float = 1.5) -> float:
    distance = atr * multiplier
    return entry_price - distance if side.upper() in {"BUY", "LONG"} else entry_price + distance
