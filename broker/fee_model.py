class FeeModel:
    def __init__(self, taker_rate: float = 0.001, maker_rate: float = 0.0008) -> None:
        self.taker_rate = taker_rate
        self.maker_rate = maker_rate

    def rate(self, order_type: str) -> float:
        return self.maker_rate if order_type.upper() == "LIMIT" else self.taker_rate

    def calculate(self, notional: float, order_type: str = "MARKET") -> float:
        return notional * self.rate(order_type)
