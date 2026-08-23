from sqlalchemy import BigInteger, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_uuid: Mapped[str] = mapped_column(ForeignKey("signals.signal_uuid"), nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(String)
    position_size: Mapped[float | None] = mapped_column(Float)
    risk_pct: Mapped[float | None] = mapped_column(Float)
    stop_loss_price: Mapped[float | None] = mapped_column(Float)
    tp1_price: Mapped[float | None] = mapped_column(Float)
    tp2_price: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
