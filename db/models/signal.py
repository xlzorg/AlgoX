from sqlalchemy import BigInteger, Float, Index, Integer, String, desc
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        Index("idx_signals_symbol_time", "symbol", desc("timestamp")),
        Index("idx_signals_direction", "direction"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_uuid: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    strategy_id: Mapped[str] = mapped_column(String, nullable=False)
    reasoning: Mapped[str] = mapped_column(String, nullable=False)
    market_regime: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
