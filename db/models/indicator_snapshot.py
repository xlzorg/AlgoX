from sqlalchemy import BigInteger, Float, Index, Integer, String, UniqueConstraint, desc
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class IndicatorSnapshot(Base):
    __tablename__ = "indicator_snapshots"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "candle_time", name="uq_indicators_symbol_tf_time"),
        Index("idx_ind_symbol_tf_time", "symbol", "timeframe", desc("candle_time")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)
    candle_time: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ema_9: Mapped[float | None] = mapped_column(Float)
    ema_21: Mapped[float | None] = mapped_column(Float)
    ema_50: Mapped[float | None] = mapped_column(Float)
    ema_200: Mapped[float | None] = mapped_column(Float)
    vwap: Mapped[float | None] = mapped_column(Float)
    bb_upper: Mapped[float | None] = mapped_column(Float)
    bb_mid: Mapped[float | None] = mapped_column(Float)
    bb_lower: Mapped[float | None] = mapped_column(Float)
    rsi_14: Mapped[float | None] = mapped_column(Float)
    macd_line: Mapped[float | None] = mapped_column(Float)
    macd_signal: Mapped[float | None] = mapped_column(Float)
    macd_hist: Mapped[float | None] = mapped_column(Float)
    stoch_k: Mapped[float | None] = mapped_column(Float)
    stoch_d: Mapped[float | None] = mapped_column(Float)
    mfi_14: Mapped[float | None] = mapped_column(Float)
    obv: Mapped[float | None] = mapped_column(Float)
    taker_buy_ratio: Mapped[float | None] = mapped_column(Float)
    vwap_dev_pct: Mapped[float | None] = mapped_column(Float)
    atr_14: Mapped[float | None] = mapped_column(Float)
    adx_14: Mapped[float | None] = mapped_column(Float)
    kc_upper: Mapped[float | None] = mapped_column(Float)
    kc_lower: Mapped[float | None] = mapped_column(Float)
    hist_vol_20: Mapped[float | None] = mapped_column(Float)
    nvt_ratio: Mapped[float | None] = mapped_column(Float)
    exchange_netflow: Mapped[float | None] = mapped_column(Float)
    market_regime: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
