"""
Generic async CRUD base repository.
All specific repos inherit from this.
"""
from typing import Any, Generic, TypeVar
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.data.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    def __init__(self, model: type[ModelT], db: AsyncSession) -> None:
        self._model = model
        self._db = db

    async def get(self, id: Any) -> ModelT | None:
        return await self._db.get(self._model, id)

    async def get_all(self) -> list[ModelT]:
        result = await self._db.execute(select(self._model))
        return list(result.scalars().all())

    async def create(self, obj: ModelT) -> ModelT:
        self._db.add(obj)
        await self._db.flush()
        await self._db.refresh(obj)
        return obj

    async def delete(self, obj: ModelT) -> None:
        await self._db.delete(obj)
        await self._db.flush()
