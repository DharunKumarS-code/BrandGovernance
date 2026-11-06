"""Fake LLMProvider/EmbeddingProvider implementations for Phase 5 tests --
deterministic, free, and network-free, so analysis-pipeline tests
(caching, degraded-mode fallback, schema-validation rejection) don't
depend on real credentials or real API calls.
"""

import hashlib
from typing import Any

from app.services.ai.errors import ProviderNotConfiguredError, ProviderUnavailableError
from app.services.ai.providers import EmbeddingProvider, LLMProvider


class FakeLLMProvider(LLMProvider):
    """`responses` is keyed by the schema's top-level JSON property name --
    "claims" for claim extraction, "findings" for tone analysis -- which is
    how a caller-agnostic fake can tell the two apart without depending on
    provider-specific concepts like Anthropic's tool names."""

    def __init__(
        self,
        responses: dict[str, Any] | None = None,
        fail: bool = False,
        not_configured: bool = False,
    ):
        self.responses = responses or {}
        self.fail = fail
        self.not_configured = not_configured
        self.calls: list[dict[str, Any]] = []

    async def verify(self) -> None:
        if self.not_configured:
            raise ProviderNotConfiguredError("fake: not configured")
        if self.fail:
            raise ProviderUnavailableError("fake: verify failure")

    async def generate_structured(
        self, *, system: str, user_content: str, schema: dict[str, Any], max_tokens: int
    ) -> dict[str, Any]:
        schema_key = next(iter(schema.get("properties", {})), None)
        self.calls.append({"schema_key": schema_key, "system": system, "user_content": user_content})
        if self.fail:
            raise ProviderUnavailableError("fake: generate_structured failure")
        if schema_key in self.responses:
            return self.responses[schema_key]
        if schema_key == "claims":
            return {"claims": []}
        if schema_key == "findings":
            return {"findings": []}
        return {}


class FakeEmbeddingProvider(EmbeddingProvider):
    def __init__(self, dim: int = 8, fail: bool = False, not_configured: bool = False):
        self.dim = dim
        self.fail = fail
        self.not_configured = not_configured
        self.calls: list[int] = []  # number of texts per call

    async def verify(self) -> None:
        if self.not_configured:
            raise ProviderNotConfiguredError("fake: not configured")
        if self.fail:
            raise ProviderUnavailableError("fake: verify failure")

    async def embed(self, texts: list[str], input_type: str | None = None) -> list[list[float]]:
        self.calls.append(len(texts))
        if self.fail:
            raise ProviderUnavailableError("fake: embed failure")
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vectors.append([b / 255.0 for b in digest[: self.dim]])
        return vectors
