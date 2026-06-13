"""
Watchlist repository — manage user coin watchlists.
"""
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from src.data.models.watchlist import Watchlist
from src.data.repositories.base import BaseRepository


class WatchlistRepository(BaseRepository[Watchlist]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(Watchlist, db)

    async def get_user_watchlist(self, user_id: str) -> list[Watchlist]:
        result = await self._db.execute(
            select(Watchlist)
            .where(Watchlist.user_id == user_id)
            .order_by(Watchlist.added_at)
        )
        return list(result.scalars().all())

    async def get_symbols(self, user_id: str) -> list[str]:
        """Return just the symbol strings for a user's watchlist."""
        items = await self.get_user_watchlist(user_id)
        return [item.symbol for item in items]

    async def add(self, user_id: str, symbol: str) -> tuple[Watchlist, bool]:
        """Add symbol to watchlist. Returns (item, created)."""
        result = await self._db.execute(
            select(Watchlist).where(
                Watchlist.user_id == user_id,
                Watchlist.symbol == symbol,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing, False

        item = Watchlist(user_id=user_id, symbol=symbol)
        return await self.create(item), True

    async def remove(self, user_id: str, symbol: str) -> bool:
        """Remove symbol from watchlist. Returns True if removed."""
        result = await self._db.execute(
            delete(Watchlist).where(
                Watchlist.user_id == user_id,
                Watchlist.symbol == symbol,
            ).returning(Watchlist.id)
        )
        return result.rowcount > 0

    async def get_all_watched_symbols(self) -> list[str]:
        """Get all unique symbols watched by any user (for background jobs)."""
        result = await self._db.execute(
            select(Watchlist.symbol).distinct()
        )
        return list(result.scalars().all())

    async def get_user_watchlist_by_symbol(self, symbol: str) -> list[Watchlist]:
        """Get all watchlist entries for a given symbol across all users."""
        result = await self._db.execute(
            select(Watchlist).where(Watchlist.symbol == symbol)
        )
        return list(result.scalars().all())
