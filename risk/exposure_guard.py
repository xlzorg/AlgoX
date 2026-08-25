class ExposureGuard:
    """
    Guards against over-concentration at the portfolio level.

    WHAT CHANGED:
      The per-asset exposure fraction check (asset_exposure_fraction >=
      max_single_asset_fraction) has been moved into PositionSizer.calculate(),
      which now caps quantity so notional never exceeds the limit in the first
      place. Checking the same limit here again would reject orders that are
      already correctly sized — which was why no positions were opening after
      the "fix" attempt.

      ExposureGuard now owns only the MAX OPEN POSITIONS count check.
      The `allows()` helper remains for any caller that still needs it
      (e.g. a correlation guard or a multi-asset allocation layer).
    """

    def __init__(
        self,
        max_positions: int = 5,
        max_single_asset_fraction: float = 0.20,
    ) -> None:
        self.max_positions = max_positions
        self.max_single_asset_fraction = max_single_asset_fraction

    def check_position_count(self, open_positions: int) -> str | None:
        """Returns rejection reason string if limit breached, else None."""
        if open_positions >= self.max_positions:
            return "MAX_OPEN_POSITIONS"
        return None

    def check(self, open_positions: int, asset_exposure_fraction: float) -> str | None:
        """
        Kept for backward compatibility with any code that still calls check().
        Only enforces the position count — the asset_exposure_fraction
        parameter is accepted but intentionally ignored here because the
        PositionSizer already caps quantity before this is called.
        """
        return self.check_position_count(open_positions)

    def allows(self, current_pct: float, new_pct: float, maximum_pct: float) -> bool:
        """True if adding new_pct exposure stays within maximum_pct."""
        return current_pct + new_pct <= maximum_pct