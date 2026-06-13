"""
User repository — find, create, upsert users by Telegram ID.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.data.models.user import User
from src.data.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(User, db)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self._db.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def upsert_user(
        self,
        telegram_id: int,
        username: str | None = None,
        first_name: str | None = None,
    ) -> tuple[User, bool]:
        """
        Create user if not exists, update name if changed.
        Returns (user, created) — created=True if newly registered.
        """
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            # Update name fields if changed
            if username and user.username != username:
                user.username = username
            if first_name and user.first_name != first_name:
                user.first_name = first_name
            await self._db.flush()
            return user, False

        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
        )
        return await self.create(user), True
