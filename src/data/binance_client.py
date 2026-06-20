"""
Binance API Client — fetches market data (no API key needed for public endpoints).
Uses httpx async + tenacity retry + cache-aside pattern.
"""
import logging
from typing import Any
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

BINANCE_BASE_URL = "https://api.binance.com"
BINANCE_TESTNET_URL = "https://testnet.binance.vision"
BINANCE_FUTURES_URL = "https://fapi.binance.com"


def _normalize_symbol(symbol: str) -> str:
    """Convert 'BTC' or 'btc' to 'BTCUSDT', pass through 'BTCUSDT'."""
    symbol = symbol.upper().strip()
    if not symbol.endswith("USDT"):
        symbol = f"{symbol}USDT"
    return symbol


class BinanceClient:
    """
    Async Binance REST API client.
    All public market data endpoints — no API key required.
    """

    def __init__(self, cache=None, testnet: bool = False) -> None:
        # Market data (klines, ticker, funding) always uses mainnet — no API key needed.
        # Testnet only applies to trading order endpoints (Phase 4+).
        self._base_url = BINANCE_BASE_URL
        self._testnet = testnet  # reserved for future order endpoints
        self._cache = cache
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=10.0,
            headers={"User-Agent": "CryptoAI-Tool/1.0"},
        )

    async def close(self) -> None:
        await self._http.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        # Only retry genuine network errors (timeout, DNS, connection reset).
        # Do NOT retry HTTPStatusError — 400/404 are intentional server responses
        # and are used by the Spot→Futures fallback logic in callers.
        retry=retry_if_exception_type(httpx.RequestError),
        reraise=True,
    )
    async def _get(self, path: str, params: dict | None = None, use_futures: bool = False) -> Any:
        url = f"{BINANCE_FUTURES_URL}{path}" if use_futures else path
        resp = await self._http.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    async def _get_market_type(self, symbol: str) -> str:
        """
        Returns cached market type for symbol: 'spot' | 'futures'.
        Avoids unnecessary Spot API call on repeated requests for Futures-only symbols.
        TTL: 24 hours (market listings rarely change intraday).
        """
        if self._cache:
            cached = await self._cache.get(f"mtype:{symbol}")
            if cached:
                return cached
        return "spot"  # default: try Spot first

    async def _cache_market_type(self, symbol: str, market_type: str) -> None:
        """Cache market type discovery result for 24 hours."""
        if self._cache:
            await self._cache.set(f"mtype:{symbol}", market_type, ttl_seconds=86400)

    async def detect_market_type(self, symbol: str) -> str:
        """
        Actively detect whether a symbol is on Spot or Futures.
        Returns: 'spot' | 'futures' | 'unknown'
        Result is cached for 24h.
        """
        symbol = _normalize_symbol(symbol)

        # Check cache first
        if self._cache:
            cached = await self._cache.get(f"mtype:{symbol}")
            if cached in ("spot", "futures"):
                return cached

        # Try Spot first
        try:
            await self._get("/api/v3/ticker/price", {"symbol": symbol})
            await self._cache_market_type(symbol, "spot")
            return "spot"
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 400:
                pass  # not on Spot — try Futures
            else:
                raise

        # Try Futures
        try:
            await self._get("/fapi/v1/ticker/price", {"symbol": symbol}, use_futures=True)
            await self._cache_market_type(symbol, "futures")
            return "futures"
        except Exception:
            pass

        return "unknown"

    async def get_ticker(self, symbol: str) -> dict:
        """
        Get current price and 24h stats for a coin.
        Returns: {symbol, price, change_pct, volume, high_24h, low_24h}
        Cached 30 seconds.
        """
        symbol = _normalize_symbol(symbol)
        cache_key = f"ticker:{symbol}"

        if self._cache:
            cached = await self._cache.get(cache_key)
            if cached:
                logger.debug("Cache hit: %s", cache_key)
                return cached

        logger.debug("Fetching ticker from Binance: %s", symbol)
        # Skip Spot call if we already know this symbol is Futures-only
        use_futures_direct = (await self._get_market_type(symbol)) == "futures"
        try:
            if use_futures_direct:
                raise httpx.HTTPStatusError("skip spot", request=None, response=None)  # type: ignore
            data = await self._get("/api/v3/ticker/24hr", {"symbol": symbol})
        except httpx.HTTPStatusError as e:
            if use_futures_direct or e.response is None or e.response.status_code == 400:
                logger.info("Symbol %s is Futures-only — fetching ticker from fapi", symbol)
                data = await self._get("/fapi/v1/ticker/24hr", {"symbol": symbol}, use_futures=True)
                await self._cache_market_type(symbol, "futures")
            else:
                raise

        result = {
            "symbol": symbol,
            "price": float(data["lastPrice"]),
            "change_pct": float(data["priceChangePercent"]),
            "volume_usdt": float(data["quoteVolume"]),
            "high_24h": float(data["highPrice"]),
            "low_24h": float(data["lowPrice"]),
            "price_change": float(data["priceChange"]),
        }

        if self._cache:
            await self._cache.set(cache_key, result, ttl_seconds=30)

        return result

    async def get_klines(
        self,
        symbol: str,
        interval: str = "4h",
        limit: int = 200,
    ) -> list[list]:
        """
        Get OHLCV candlestick data.
        interval: 1m, 5m, 15m, 1h, 4h, 1d
        Returns list of [open_time, open, high, low, close, volume, ...]
        Cached 5 minutes.
        """
        symbol = _normalize_symbol(symbol)
        cache_key = f"klines:{symbol}:{interval}:{limit}"

        if self._cache:
            cached = await self._cache.get(cache_key)
            if cached:
                return cached

        # Skip Spot call if we already know this symbol is Futures-only
        use_futures_direct = (await self._get_market_type(symbol)) == "futures"
        try:
            if use_futures_direct:
                raise httpx.HTTPStatusError("skip spot", request=None, response=None)  # type: ignore
            data = await self._get(
                "/api/v3/klines",
                {"symbol": symbol, "interval": interval, "limit": limit},
            )
        except httpx.HTTPStatusError as e:
            if use_futures_direct or e.response is None or e.response.status_code == 400:
                logger.info("Symbol %s is Futures-only — fetching klines from fapi (%s, limit=%s)", symbol, interval, limit)
                data = await self._get(
                    "/fapi/v1/klines",
                    {"symbol": symbol, "interval": interval, "limit": limit},
                    use_futures=True
                )
                await self._cache_market_type(symbol, "futures")
            else:
                raise

        if self._cache:
            await self._cache.set(cache_key, data, ttl_seconds=300)

        return data

    async def get_open_interest(self, symbol: str) -> dict | None:
        """
        Get current + historical Open Interest from Futures API for trend confirmation.
        Returns: {"oi": current_oi, "oi_change_pct": %_change_vs_4h_ago}
        Returns None if symbol is spot-only or API fails.
        """
        symbol = _normalize_symbol(symbol)
        cache_key = f"oi:{symbol}"
        if self._cache:
            cached = await self._cache.get(cache_key)
            if cached:
                return cached

        try:
            # Only works for futures symbols. 
            current = await self._get("/fapi/v1/openInterest", {"symbol": symbol}, use_futures=True)
            hist = await self._get(
                "/futures/data/openInterestHist",
                {"symbol": symbol, "period": "4h", "limit": 2},
                use_futures=True
            )
            oi_now = float(current["openInterest"])
            oi_prev = float(hist[0]["sumOpenInterest"]) if hist else oi_now
            
            result = {
                "oi": oi_now,
                "oi_change_pct": ((oi_now - oi_prev) / oi_prev * 100) if oi_prev else 0.0,
            }
            if self._cache:
                await self._cache.set(cache_key, result, ttl_seconds=300)
            return result
        except Exception as e:
            logger.debug("OI unavailable for %s: %s", symbol, e)
            return None

    async def get_funding_rate(self, symbol: str) -> float | None:
        """
        Get current futures funding rate.
        Returns funding rate as float (e.g. 0.0001 = 0.01%).
        Returns None if symbol not available on futures.
        """
        symbol = _normalize_symbol(symbol)
        cache_key = f"funding:{symbol}"

        if self._cache:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        try:
            data = await self._get("/fapi/v1/premiumIndex", {"symbol": symbol}, use_futures=True)
            rate = float(data.get("lastFundingRate", 0))
            if self._cache:
                await self._cache.set(cache_key, rate, ttl_seconds=300)
            return rate
        except Exception as e:
            logger.warning("Funding rate unavailable for %s: %s", symbol, e)
            return None

    async def get_fear_greed_index(self) -> dict:
        """
        Get Fear & Greed Index from Alternative.me (no API key needed).
        Returns: {value: int, label: str}
        Cached 1 hour.
        """
        cache_key = "fear_greed"

        if self._cache:
            cached = await self._cache.get(cache_key)
            if cached:
                return cached

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://api.alternative.me/fng/?limit=1")
            resp.raise_for_status()
            data = resp.json()["data"][0]

        result = {
            "value": int(data["value"]),
            "label": data["value_classification"],
        }

        if self._cache:
            await self._cache.set(cache_key, result, ttl_seconds=3600)

        return result
