from sqlalchemy import BigInteger, Float, ForeignKey, Index, Integer, String, desc
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        Index("idx_positions_symbol_status", "symbol", "status"),
        Index("idx_positions_entry_time", desc("entry_time")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_uuid: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    entry_signal_uuid: Mapped[str | None] = mapped_column(ForeignKey("signals.signal_uuid"))
    entry_fill_uuid: Mapped[str | None] = mapped_column(ForeignKey("fills.fill_uuid"))
    exit_fill_uuid: Mapped[str | None] = mapped_column(ForeignKey("fills.fill_uuid"))
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss_price: Mapped[float | None] = mapped_column(Float)
    tp1_price: Mapped[float | None] = mapped_column(Float)
    tp2_price: Mapped[float | None] = mapped_column(Float)
    realized_pnl: Mapped[float | None] = mapped_column(Float)
    realized_pnl_pct: Mapped[float | None] = mapped_column(Float)
    total_fees: Mapped[float | None] = mapped_column(Float)
    holding_bars: Mapped[int | None] = mapped_column(Integer)
    entry_time: Mapped[int] = mapped_column(BigInteger, nullable=False)
    exit_time: Mapped[int | None] = mapped_column(BigInteger)
    strategy_id: Mapped[str | None] = mapped_column(String)
    market_regime: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
