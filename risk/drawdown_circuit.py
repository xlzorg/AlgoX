class DrawdownCircuit:
    def __init__(self, max_daily_loss_fraction: float = 0.03, max_drawdown_fraction: float = 0.10) -> None:
        self.max_daily_loss_fraction = max_daily_loss_fraction
        self.max_drawdown_fraction = max_drawdown_fraction

    def check(self, daily_loss_fraction: float, drawdown_fraction: float) -> str | None:
        if daily_loss_fraction >= self.max_daily_loss_fraction:
            return "MAX_DAILY_LOSS"
        if drawdown_fraction >= self.max_drawdown_fraction:
            return "MAX_DRAWDOWN"
        return None

    def tripped(self, drawdown_pct: float) -> bool:
        return drawdown_pct >= self.max_drawdown_fraction * 100
