"""
Claude AI Provider — implements AIProvider using Anthropic SDK.
Models: claude-haiku-4-5 (fast) and claude-sonnet-4-6 (quality).
"""
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.ai.base import AIProvider, CRYPTO_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class ClaudeProvider(AIProvider):
    """Anthropic Claude — primary AI provider."""

    # Model IDs from master prompt spec
    MODEL_QUALITY = "claude-sonnet-4-6"   # On-demand analysis, trade journal
    MODEL_FAST = "claude-haiku-4-5"       # Morning brief, alert messages

    def __init__(self) -> None:
        from config.settings import settings
        import anthropic

        if not settings.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not set in .env")

        self._client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    @property
    def provider_name(self) -> str:
        return "claude"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 1000,
    ) -> str:
        system_prompt = system or CRYPTO_SYSTEM_PROMPT
        logger.debug("Claude Sonnet request: %d chars", len(prompt))

        message = await self._client.messages.create(
            model=self.MODEL_QUALITY,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text  # type: ignore[index]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def complete_fast(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 500,
    ) -> str:
        system_prompt = system or CRYPTO_SYSTEM_PROMPT
        logger.debug("Claude Haiku request: %d chars", len(prompt))

        message = await self._client.messages.create(
            model=self.MODEL_FAST,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text  # type: ignore[index]
