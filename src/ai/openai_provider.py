"""
OpenAI Provider — fallback when Claude API is down.
Models: gpt-4o (quality) and gpt-4o-mini (fast/cheap).
"""
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.ai.base import AIProvider, CRYPTO_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class OpenAIProvider(AIProvider):
    """OpenAI — fallback provider."""

    MODEL_QUALITY = "gpt-4o"
    MODEL_FAST = "gpt-4o-mini"

    def __init__(self) -> None:
        from config.settings import settings
        import openai

        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not set in .env")

        self._client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    @property
    def provider_name(self) -> str:
        return "openai"

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
        response = await self._client.chat.completions.create(
            model=self.MODEL_QUALITY,
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
        system_prompt = system or CRYPTO_SYSTEM_PROMPT
        response = await self._client.chat.completions.create(
            model=self.MODEL_FAST,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""
