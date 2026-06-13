"""
User model — multi-user ready.
For personal use: only 1 row, but schema is ready to scale.
"""
import uuid
from datetime import datetime, time
from sqlalchemy import BigInteger, Boolean, String, Numeric, Time, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from src.data.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Settings
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Ho_Chi_Minh")
    capital: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    risk_per_trade: Mapped[float] = mapped_column(Numeric(5, 4), default=0.02)  # 2%

    # Morning brief
    morning_brief_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    morning_brief_time: Mapped[time] = mapped_column(Time, default=time(7, 0))

    # Plan (for future multi-user)
    plan: Mapped[str] = mapped_column(String(20), default="free")  # free | pro | pro_plus

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<User telegram_id={self.telegram_id} username={self.username}>"
