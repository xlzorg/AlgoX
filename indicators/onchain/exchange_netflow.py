def calculate_exchange_netflow(inflow: float, outflow: float) -> float:
    return inflow - outflow


class ExchangeNetflow:
    def calculate(self, inflow: float, outflow: float) -> float:
        return calculate_exchange_netflow(inflow, outflow)
