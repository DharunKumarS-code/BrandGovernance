"""Phase 5 provider abstraction.

Two tiny interfaces -- an LLM that can be forced to emit JSON matching a
given schema, and an embedding provider -- so no single vendor's API shape
is hard-wired into the analysis code. Swapping providers later means
implementing these two ABCs and changing get_llm_provider()/
get_embedding_provider(); nothing in app/services/analysis/ needs to know
which vendor is behind them, or how that vendor's SDK expresses "respond
with this JSON shape" (Gemini: response_schema; a hypothetical future
provider might use tool-calling, as the previous Anthropic-based
implementation did) -- that detail stays inside each provider class.
"""

from abc import ABC, abstractmethod
from typing import Any

from app.core.config import settings
from app.services.ai.errors import ProviderNotConfiguredError


class LLMProvider(ABC):
    @abstractmethod
    async def verify(self) -> None:
        """Raises ProviderNotConfiguredError (no key) or
        ProviderUnavailableError (key present but rejected/unreachable) if
        this provider cannot currently be used. Returns normally if it can."""

    @abstractmethod
    async def generate_structured(
        self, *, system: str, user_content: str, schema: dict[str, Any], max_tokens: int
    ) -> dict[str, Any]:
        """Forces the model to respond with JSON matching `schema` (a
        plain JSON-schema-shaped dict) and returns the parsed dict.
        Callers are responsible for validating the result against their
        own Pydantic model -- this layer only guarantees "the provider was
        made to emit structured output", not "the output is semantically
        correct". Raises ProviderUnavailableError on any transport/auth/
        rate-limit/malformed-response failure."""


class EmbeddingProvider(ABC):
    @abstractmethod
    async def verify(self) -> None: ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Returns one embedding vector per input text, same order.
        Raises ProviderUnavailableError on any failure."""


def get_llm_provider() -> LLMProvider | None:
    """None means "not configured" -- callers must treat that as a signal
    to run in degraded (rule-only) mode, never as something to retry."""
    from app.services.ai.gemini_provider import GeminiLLMProvider

    if not settings.gemini_api_key:
        return None
    try:
        return GeminiLLMProvider(api_key=settings.gemini_api_key, model=settings.gemini_model)
    except ProviderNotConfiguredError:
        return None


def get_embedding_provider() -> EmbeddingProvider | None:
    from app.services.ai.gemini_provider import GeminiEmbeddingProvider

    if not settings.gemini_api_key:
        return None
    try:
        return GeminiEmbeddingProvider(api_key=settings.gemini_api_key, model=settings.gemini_embedding_model)
    except ProviderNotConfiguredError:
        return None
