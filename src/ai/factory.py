"""
AI Provider Factory — returns correct provider from AI_PROVIDER env var.
Also provides fallback wrapper: try Claude → fallback OpenAI on failure.
"""
import logging
from src.ai.base import AIProvider

logger = logging.getLogger(__name__)


def _instantiate_provider(provider_name: str) -> AIProvider:
    if provider_name == "claude":
        from src.ai.claude_provider import ClaudeProvider
        return ClaudeProvider()
    if provider_name == "openai":
        from src.ai.openai_provider import OpenAIProvider
        return OpenAIProvider()
    if provider_name == "deepseek":
        from src.ai.deepseek_provider import DeepSeekProvider
        return DeepSeekProvider()
    raise ValueError(f"Unknown AI provider: {provider_name}")


def get_primary_provider() -> AIProvider:
    """Return primary AI provider for deep analysis (e.g. Claude)."""
    from config.settings import settings
    return _instantiate_provider(settings.PRIMARY_AI_PROVIDER.lower())


def get_fast_provider() -> AIProvider:
    """Return fast AI provider for summaries and alerts (e.g. DeepSeek)."""
    from config.settings import settings
    return _instantiate_provider(settings.FAST_AI_PROVIDER.lower())


async def complete_with_fallback(
    prompt: str,
    system: str = "",
    max_tokens: int = 1000,
    fast: bool = False,
) -> str:
    """
    Execute AI completion. If fast=True, uses the fast provider (DeepSeek).
    Otherwise, uses the primary provider (Claude).
    Falls back to OpenAI if primary fails.
    """
    from src.ai.openai_provider import OpenAIProvider

    provider = get_fast_provider() if fast else get_primary_provider()
    fallback = OpenAIProvider if not isinstance(provider, OpenAIProvider) else None

    try:
        if fast:
            return await provider.complete_fast(prompt, system, max_tokens)
        return await provider.complete(prompt, system, max_tokens)

    except Exception as e:
        logger.warning(
            "Provider '%s' failed: %s. Trying fallback...",
            provider.provider_name,
            e,
        )
        if fallback is None:
            raise

        try:
            backup = fallback()
            if fast:
                return await backup.complete_fast(prompt, system, max_tokens)
            return await backup.complete(prompt, system, max_tokens)
        except Exception as fallback_err:
            logger.error("Fallback also failed: %s", fallback_err)
            raise
