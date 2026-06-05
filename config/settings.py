"""
Application settings — loaded from .env via Pydantic Settings.
Swap DATABASE_URL to PostgreSQL anytime — zero code changes needed.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ────────────────────────────────────────────────────────────────
    APP_ENV: str = Field(default="development")
    LOG_LEVEL: str = Field(default="INFO")
    SECRET_KEY: str = Field(default="change-me-in-production")

    # ── Database ───────────────────────────────────────────────────────────
    # SQLite (default, local dev) → swap to PostgreSQL by changing this URL only
    # SQLite:     sqlite+aiosqlite:///./data/cryptoai.db
    # PostgreSQL: postgresql+asyncpg://user:pass@localhost:5432/cryptoai
    DATABASE_URL: str = Field(default="sqlite+aiosqlite:///./data/cryptoai.db")

    # ── Cache ──────────────────────────────────────────────────────────────
    # "memory" → in-process TTL dict (personal use)
    # "redis"  → Redis (production / multi-user)
    CACHE_BACKEND: str = Field(default="memory")
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # ── Telegram ───────────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = Field(default="")
    # Personal use: only this user ID can interact with the bot
    TELEGRAM_ALLOWED_USER_ID: int = Field(default=0)

    # ── AI Providers (Hybrid) ──────────────────────────────────────────────
    PRIMARY_AI_PROVIDER: str = Field(default="claude")  # claude | openai
    FAST_AI_PROVIDER: str = Field(default="deepseek")   # deepseek | openai
    ANTHROPIC_API_KEY: str = Field(default="")
    OPENAI_API_KEY: str = Field(default="")
    DEEPSEEK_API_KEY: str = Field(default="")

    # ── Binance ────────────────────────────────────────────────────────────
    BINANCE_API_KEY: str = Field(default="")
    BINANCE_SECRET_KEY: str = Field(default="")
    BINANCE_TESTNET: bool = Field(default=True)  # Always testnet until ready

    # ── External APIs ──────────────────────────────────────────────────────
    CRYPTOPANIC_API_KEY: str = Field(default="")
    # Alternative.me Fear & Greed: no key needed

    # ── Trading Defaults (personal profile) ───────────────────────────────
    DEFAULT_CAPITAL_USD: float = Field(default=1000.0)
    DEFAULT_RISK_PER_TRADE: float = Field(default=0.02)   # 2%
    DEFAULT_TIMEZONE: str = Field(default="Asia/Ho_Chi_Minh")
    MORNING_BRIEF_TIME: str = Field(default="07:00")

    # ── Rate limits ────────────────────────────────────────────────────────
    MAX_AI_CALLS_PER_MINUTE: int = Field(default=5)
    MAX_ALERTS_PER_COIN_PER_HOUR: int = Field(default=3)
    MAX_SIGNAL_CALLS_PER_HOUR: int = Field(default=10)

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"

    @property
    def binance_base_url(self) -> str:
        if self.BINANCE_TESTNET:
            return "https://testnet.binance.vision"
        return "https://api.binance.com"


# Singleton — import this everywhere
settings = Settings()
