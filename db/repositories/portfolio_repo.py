class PortfolioRepository:
    async def summary(self) -> dict:
        return {"equity": 0.0, "cash": 0.0, "unrealized_pnl": 0.0}
