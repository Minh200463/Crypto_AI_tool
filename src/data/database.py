"""
Async database engine and session factory.
SQLite now — swap to PostgreSQL by changing DATABASE_URL in .env.
"""
import logging
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from config.settings import settings

logger = logging.getLogger(__name__)

# Ensure the data/ directory exists for SQLite
if settings.DATABASE_URL.startswith("sqlite"):
    Path("data").mkdir(exist_ok=True)

# SQLite needs special connect_args + StaticPool for async use
_connect_args = {}
_pool_class = None

if "sqlite" in settings.DATABASE_URL:
    _connect_args = {"check_same_thread": False}
    _pool_class = StaticPool

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.is_development,  # log SQL in dev mode
    connect_args=_connect_args,
    **({"poolclass": _pool_class} if _pool_class else {}),
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:  # type: ignore[return]
    """
    Async context manager / FastAPI dependency for DB sessions.
    Usage:
        async with get_db() as db:
            result = await db.execute(...)
    Or as FastAPI dependency:
        db: AsyncSession = Depends(get_db)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all_tables() -> None:
    """
    Create all tables if they don't exist.
    Called at app startup as a safety net (Alembic handles migrations).
    """
    from src.data.models import Base  # noqa: F401 — ensures models are registered
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables verified/created.")
