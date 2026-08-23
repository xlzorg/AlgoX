from __future__ import annotations

from collections import defaultdict


class VirtualWallet:
    def __init__(self, initial_balance: float = 10_000.0) -> None:
        self.starting_balance = float(initial_balance)
        self.cash = float(initial_balance)
        self.holdings: dict[str, float] = defaultdict(float)

    def apply_fill(self, symbol: str, side: str, quantity: float, price: float, fee: float) -> None:
        notional = quantity * price
        asset = symbol.replace("USDT", "")
        if side.upper() == "BUY":
            self.cash -= notional + fee
            self.holdings[asset] += quantity
        else:
            self.cash += notional - fee
            self.holdings[asset] -= quantity

    def equity(self, prices: dict[str, float] | None = None) -> float:
        total = self.cash
        for asset, quantity in self.holdings.items():
            total += quantity * (prices or {}).get(f"{asset}USDT", 0.0)
        return total

    def reset(self) -> None:
        self.cash = self.starting_balance
        self.holdings.clear()
