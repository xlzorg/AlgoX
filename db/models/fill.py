from sqlalchemy import BigInteger, Float, ForeignKey, Index, Integer, String, desc
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class Fill(Base):
    __tablename__ = "fills"
    __table_args__ = (Index("idx_fills_symbol_time", "symbol", desc("timestamp")),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fill_uuid: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    order_uuid: Mapped[str] = mapped_column(ForeignKey("orders.order_uuid"), nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)
    filled_qty: Mapped[float] = mapped_column(Float, nullable=False)
    avg_price: Mapped[float] = mapped_column(Float, nullable=False)
    fee: Mapped[float] = mapped_column(Float, nullable=False)
    fee_asset: Mapped[str] = mapped_column(String, nullable=False)
    slippage_pct: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
