"""
AI Provider abstract interface.
All providers (Claude, OpenAI, Gemini) implement this — swap via AI_PROVIDER in .env.
"""
from abc import ABC, abstractmethod


class AIProvider(ABC):
    """
    Abstract base for all AI providers.
    Services call this interface — never call Anthropic/OpenAI SDKs directly.
    """

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 1000,
    ) -> str:
        """
        High-quality completion — use for on-demand analysis.
        Maps to: claude-sonnet, gpt-4o, gemini-pro
        """
        ...

    @abstractmethod
    async def complete_fast(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 500,
    ) -> str:
        """
        Fast/cheap completion — use for batch tasks (alerts, morning brief).
        Maps to: claude-haiku, gpt-4o-mini, gemini-flash
        """
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name for logging."""
        ...


# Shared system prompt — injected into every AI call
CRYPTO_SYSTEM_PROMPT = """You are a crypto market analysis assistant. \
You provide factual technical analysis based on data provided to you. \
You NEVER recommend buying or selling specific assets. \
You NEVER predict prices. \
You present analysis as reference information only. \
Always end responses with: "This is for informational purposes only, not financial advice." \
Keep responses concise and in plain English."""
