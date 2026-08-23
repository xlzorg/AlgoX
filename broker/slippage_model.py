from __future__ import annotations

import random


def calculate_slippage(order_type: str, qty: float, avg_volume_24h: float, *, noise_std: float = 0.0002) -> float:
    if avg_volume_24h <= 0 or qty <= 0:
        return abs(random.gauss(0.0, noise_std)) if order_type.upper() == "MARKET" else 0.0
    market_impact = (qty / avg_volume_24h) * 0.1
    noise = random.gauss(0.0, noise_std)
    return market_impact + abs(noise) if order_type.upper() == "MARKET" else noise * 0.5


class SlippageModel:
    def __init__(self, noise_std: float = 0.0002) -> None:
        self.noise_std = noise_std

    def apply(self, price: float, side: str, order_type: str = "MARKET", qty: float = 0.0, avg_volume_24h: float = 1.0) -> tuple[float, float]:
        slippage = calculate_slippage(order_type, qty, avg_volume_24h, noise_std=self.noise_std)
        adjusted = price * (1 + slippage if side.upper() == "BUY" else 1 - slippage)
        return adjusted, slippage
