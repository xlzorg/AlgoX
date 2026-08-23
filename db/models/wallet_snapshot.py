from sqlalchemy import BigInteger, Float, Index, Integer, desc
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class WalletSnapshot(Base):
    __tablename__ = "wallet_snapshots"
    __table_args__ = (Index("idx_wallet_time", desc("timestamp")),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    usdt_balance: Mapped[float] = mapped_column(Float, nullable=False)
    total_equity: Mapped[float] = mapped_column(Float, nullable=False)
    open_positions: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
