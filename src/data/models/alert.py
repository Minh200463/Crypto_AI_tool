"""
Alert model — price/volume/RSI/funding alerts per user.
"""
import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, Numeric, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from src.data.models.base import Base


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # Alert type: price_above | price_below | pct_change | volume_spike | rsi_extreme | funding_extreme
    alert_type: Mapped[str] = mapped_column(String(30), nullable=False)
    threshold: Mapped[float | None] = mapped_column(Numeric(30, 10), nullable=True)
    direction: Mapped[str | None] = mapped_column(String(10), nullable=True)  # above | below

    # State
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<Alert symbol={self.symbol} type={self.alert_type} threshold={self.threshold}>"
