from sqlalchemy import BigInteger, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class OnchainSnapshot(Base):
    __tablename__ = "onchain_snapshots"
    __table_args__ = (UniqueConstraint("symbol", "timestamp", name="uq_onchain_symbol_timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    chain: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pool_tvl_usd: Mapped[float | None] = mapped_column(Float)
    pool_volume_24h: Mapped[float | None] = mapped_column(Float)
    exchange_netflow_24h: Mapped[float | None] = mapped_column(Float)
    nvt_ratio: Mapped[float | None] = mapped_column(Float)
    active_addresses_24h: Mapped[int | None] = mapped_column(Integer)
    top10_holder_pct: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
