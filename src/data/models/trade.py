"""
Trade model — trade journal entries with P&L tracking.
"""
import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Numeric, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from src.data.models.base import Base


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # buy | sell

    entry_price: Mapped[float] = mapped_column(Numeric(30, 10), nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Numeric(30, 10), nullable=True)
    quantity: Mapped[float] = mapped_column(Numeric(30, 10), nullable=False)
    leverage: Mapped[int] = mapped_column(Integer, default=1)

    stop_loss: Mapped[float | None] = mapped_column(Numeric(30, 10), nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Numeric(30, 10), nullable=True)

    # open | closed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="open")

    pnl: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    pnl_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    entry_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<Trade symbol={self.symbol} side={self.side} status={self.status}>"
