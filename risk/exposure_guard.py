class ExposureGuard:
    def __init__(self, max_positions: int = 5, max_single_asset_fraction: float = 0.20) -> None:
        self.max_positions = max_positions
        self.max_single_asset_fraction = max_single_asset_fraction

    def check(self, open_positions: int, asset_exposure_fraction: float) -> str | None:
        if open_positions >= self.max_positions:
            return "MAX_OPEN_POSITIONS"
        if asset_exposure_fraction >= self.max_single_asset_fraction:
            return "MAX_SINGLE_ASSET_EXPOSURE"
        return None

    def allows(self, current_pct: float, new_pct: float, maximum_pct: float) -> bool:
        return current_pct + new_pct <= maximum_pct
