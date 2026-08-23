from sqlalchemy import BigInteger, Float, Index, Integer, desc
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class EquityCurve(Base):
    __tablename__ = "equity_curve"
    __table_args__ = (Index("idx_equity_time", desc("timestamp")),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    equity: Mapped[float] = mapped_column(Float, nullable=False)
    drawdown_pct: Mapped[float] = mapped_column(Float, nullable=False)
    peak_equity: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
