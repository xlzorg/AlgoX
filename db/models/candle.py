from sqlalchemy import BigInteger, Float, Index, Integer, String, UniqueConstraint, desc
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "open_time", name="uq_candles_symbol_tf_time"),
        Index("idx_candles_symbol_tf_time", "symbol", "timeframe", desc("open_time")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)
    open_time: Mapped[int] = mapped_column(BigInteger, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    quote_volume: Mapped[float] = mapped_column(Float, nullable=False)
    trades: Mapped[int | None] = mapped_column(Integer)
    taker_buy_vol: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
