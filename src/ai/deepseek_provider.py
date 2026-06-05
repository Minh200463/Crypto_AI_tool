"""
DeepSeek Provider — used as the FAST AI provider for summaries and simple tasks.
Model: deepseek-chat (DeepSeek-V3)
Uses the official OpenAI Python SDK pointing to DeepSeek's API endpoint.
"""
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.ai.base import AIProvider, CRYPTO_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class DeepSeekProvider(AIProvider):
    """DeepSeek — Fast & Cost-Effective AI provider."""

    MODEL = "deepseek-chat"

    def __init__(self) -> None:
        from config.settings import settings
        import openai

        if not settings.DEEPSEEK_API_KEY:
            raise ValueError("DEEPSEEK_API_KEY is not set in .env")

        self._client = openai.AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com",
        )

    @property
    def provider_name(self) -> str:
        return "deepseek"

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
        logger.debug("DeepSeek request: %d chars", len(prompt))
        
        response = await self._client.chat.completions.create(
            model=self.MODEL,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""

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
        # For DeepSeek, we just use the same model for both, it's fast and cheap enough.
        return await self.complete(prompt, system, max_tokens)
