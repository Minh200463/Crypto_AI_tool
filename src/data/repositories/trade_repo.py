"""
Trade repository — CRUD for trade journal.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.data.models.trade import Trade
from src.data.repositories.base import BaseRepository


class TradeRepository(BaseRepository[Trade]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(Trade, db)

    async def get_open_trades(self, user_id: str) -> list[Trade]:
        result = await self._db.execute(
            select(Trade).where(Trade.user_id == user_id, Trade.status == "open")
        )
        return list(result.scalars().all())

    async def get_recent_trades(self, user_id: str, limit: int = 10) -> list[Trade]:
        result = await self._db.execute(
            select(Trade)
            .where(Trade.user_id == user_id)
            .order_by(Trade.entry_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
