"""
Cache abstraction — swap in-memory ↔ Redis by changing CACHE_BACKEND in .env.
All services use CacheService interface, never call Redis/dict directly.
"""
import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, Optional


class CacheService(ABC):
    """Abstract cache interface — backend-agnostic."""

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        """Return cached value or None if missing/expired."""
        ...

    @abstractmethod
    async def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        """Store value with TTL (seconds). Default 5 minutes."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove a key."""
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if key exists and not expired."""
        ...

    @abstractmethod
    async def flush(self) -> None:
        """Clear all cache (use with caution)."""
        ...


# ── In-Memory Implementation (personal use / local dev) ───────────────────────

class InMemoryCache(CacheService):
    """
    Simple in-process TTL cache — no external dependencies.
    Thread-safe enough for single-process asyncio app.
    Upgrade path: replace with RedisCache when scaling to multi-user.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float]] = {}  # key → (value, expires_at)
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    async def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        async with self._lock:
            self._store[key] = (value, time.monotonic() + ttl_seconds)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def exists(self, key: str) -> bool:
        return await self.get(key) is not None

    async def flush(self) -> None:
        async with self._lock:
            self._store.clear()

    def size(self) -> int:
        """Debug helper — number of cached keys (including expired)."""
        return len(self._store)


# ── Redis Implementation (multi-user / production) ────────────────────────────

class RedisCache(CacheService):
    """
    Redis-backed cache — activate by setting CACHE_BACKEND=redis in .env.
    Requires: uv add redis
    """

    def __init__(self, redis_url: str) -> None:
        # Lazy import — only needed when CACHE_BACKEND=redis
        try:
            import redis.asyncio as aioredis  # type: ignore
            self._redis = aioredis.from_url(redis_url, decode_responses=False)
        except ImportError:
            raise RuntimeError(
                "Redis backend requires 'redis' package. Run: uv add redis"
            )

    async def get(self, key: str) -> Optional[Any]:
        import pickle
        raw = await self._redis.get(key)
        return pickle.loads(raw) if raw else None  # noqa: S301

    async def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        import pickle
        await self._redis.setex(key, ttl_seconds, pickle.dumps(value))

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    async def exists(self, key: str) -> bool:
        return bool(await self._redis.exists(key))

    async def flush(self) -> None:
        await self._redis.flushdb()


# ── Factory ────────────────────────────────────────────────────────────────────

def get_cache() -> CacheService:
    """
    Return the correct cache backend based on CACHE_BACKEND env var.
    Import and call this once at startup, pass instance around via DI.
    """
    # pyrefly: ignore [missing-import]
    from config.settings import settings

    if settings.CACHE_BACKEND == "redis":
        return RedisCache(settings.REDIS_URL)
    return InMemoryCache()
