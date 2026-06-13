"""
Signal model — stores every generated trade signal for future backtesting.
"""
import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Numeric, DateTime, ForeignKey, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column
from src.data.models.base import Base


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)  # 4h | 1h | 1d

    # long | short | none
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    confluence_score: Mapped[int] = mapped_column(Integer, nullable=False)

    entry_price: Mapped[float | None] = mapped_column(Numeric(30, 10), nullable=True)
    sl_price: Mapped[float | None] = mapped_column(Numeric(30, 10), nullable=True)
    tp1_price: Mapped[float | None] = mapped_column(Numeric(30, 10), nullable=True)
    tp2_price: Mapped[float | None] = mapped_column(Numeric(30, 10), nullable=True)
    tp3_price: Mapped[float | None] = mapped_column(Numeric(30, 10), nullable=True)
    rr_tp1: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    rr_tp2: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)

    # Full indicator snapshot for backtesting
    indicator_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ai_interpretation: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    def __repr__(self) -> str:
        return f"<Signal symbol={self.symbol} side={self.side} score={self.confluence_score}>"
