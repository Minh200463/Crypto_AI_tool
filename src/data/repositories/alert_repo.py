"""
Alert repository — CRUD for user alerts.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.data.models.alert import Alert
from src.data.repositories.base import BaseRepository


class AlertRepository(BaseRepository[Alert]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(Alert, db)

    async def get_active_alerts(self, symbol: str) -> list[Alert]:
        result = await self._db.execute(
            select(Alert).where(Alert.symbol == symbol, Alert.is_active == True)  # noqa: E712
        )
        return list(result.scalars().all())

    async def get_user_alerts(self, user_id: str) -> list[Alert]:
        result = await self._db.execute(
            select(Alert).where(Alert.user_id == user_id, Alert.is_active == True)  # noqa: E712
        )
        return list(result.scalars().all())

    async def deactivate(self, alert: Alert) -> None:
        alert.is_active = False
        await self._db.flush()
