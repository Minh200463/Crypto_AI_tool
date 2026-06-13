"""
Watchlist model — coins a user is tracking.
"""
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.data.models.base import Base


class Watchlist(Base):
    __tablename__ = "watchlist"
    __table_args__ = (
        UniqueConstraint("user_id", "symbol", name="uq_watchlist_user_symbol"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. "BTCUSDT"
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<Watchlist user_id={self.user_id} symbol={self.symbol}>"
