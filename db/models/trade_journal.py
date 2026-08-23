from sqlalchemy import BigInteger, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class TradeJournal(Base):
    __tablename__ = "trade_journal"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_uuid: Mapped[str] = mapped_column(ForeignKey("positions.position_uuid"), nullable=False, unique=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    strategy_id: Mapped[str] = mapped_column(String, nullable=False)
    market_regime: Mapped[str | None] = mapped_column(String)
    entry_time: Mapped[int | None] = mapped_column(BigInteger)
    entry_price: Mapped[float | None] = mapped_column(Float)
    entry_signal_direction: Mapped[str | None] = mapped_column(String)
    entry_confidence: Mapped[float | None] = mapped_column(Float)
    entry_reasoning: Mapped[str | None] = mapped_column(String)
    exit_time: Mapped[int | None] = mapped_column(BigInteger)
    exit_price: Mapped[float | None] = mapped_column(Float)
    exit_reason: Mapped[str | None] = mapped_column(String)
    pnl_usdt: Mapped[float | None] = mapped_column(Float)
    pnl_pct: Mapped[float | None] = mapped_column(Float)
    r_multiple: Mapped[float | None] = mapped_column(Float)
    fees_usdt: Mapped[float | None] = mapped_column(Float)
    slippage_pct: Mapped[float | None] = mapped_column(Float)
    indicator_snapshot: Mapped[str | None] = mapped_column(String)
    onchain_snapshot: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
