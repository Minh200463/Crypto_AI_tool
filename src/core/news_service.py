"""
News Service — aggregates crypto news from CryptoPanic.
"""
import logging
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)


class NewsService:
    """Fetches news from CryptoPanic API."""

    def __init__(self, cache=None) -> None:
        from config.settings import settings
        self._api_key = settings.CRYPTOPANIC_API_KEY
        self._cache = cache

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=5),
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
        reraise=True,
    )
    async def fetch_top_news(self, limit: int = 5) -> list[str]:
        """
        Fetch top 'important' news from CryptoPanic.
        Returns list of headline strings.
        Cached for 30 minutes to avoid rate limits.
        """
        cache_key = "cryptopanic_top_news"

        if self._cache:
            cached = await self._cache.get(cache_key)
            if cached:
                return cached[:limit]

        # Public endpoint can be used without API key sometimes, 
        # but with auth_token it's more reliable.
        url = "https://cryptopanic.com/api/v1/posts/"
        params = {"filter": "important", "public": "true"}
        if self._api_key:
            params["auth_token"] = self._api_key

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()

            results = data.get("results", [])
            headlines = [f"{r['title']} ({r.get('source', {}).get('domain', 'news')})" for r in results]

            if self._cache and headlines:
                await self._cache.set(cache_key, headlines, ttl_seconds=1800)

            return headlines[:limit]

        except Exception as e:
            logger.warning("Failed to fetch CryptoPanic news: %s", e)
            return []
