def calculate_nvt_signal(market_cap: float, transaction_volume: float) -> float | None:
    return market_cap / transaction_volume if transaction_volume else None


class NVTSignal:
    def calculate(self, market_cap: float, transaction_volume: float) -> float | None:
        return calculate_nvt_signal(market_cap, transaction_volume)
