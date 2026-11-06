"""Tests for the Phase 5 provider abstraction -- factory functions
returning None when unconfigured, and GeminiLLMProvider/
GeminiEmbeddingProvider's error mapping and schema translation, all
without a real network call (the genai client's own methods are
monkeypatched directly -- google-genai has no public MockTransport-style
hook, so this is the equivalent for it)."""

import pytest
from google.genai import errors

from app.core.config import settings
from app.services.ai import get_embedding_provider, get_llm_provider
from app.services.ai.errors import ProviderNotConfiguredError, ProviderUnavailableError
from app.services.ai.gemini_provider import GeminiEmbeddingProvider, GeminiLLMProvider, _to_gemini_schema


# --- Factory functions: missing key -> None, never a crash/mock substitute ---


def test_get_llm_provider_returns_none_when_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", None)
    assert get_llm_provider() is None

    monkeypatch.setattr(settings, "gemini_api_key", "")
    assert get_llm_provider() is None


def test_get_embedding_provider_returns_none_when_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", None)
    assert get_embedding_provider() is None


def test_both_factories_return_gemini_providers_when_key_present(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "fake-key-for-construction-only")
    assert isinstance(get_llm_provider(), GeminiLLMProvider)
    assert isinstance(get_embedding_provider(), GeminiEmbeddingProvider)


# --- Constructing directly with an empty key --------------------------------


async def test_gemini_llm_provider_rejects_empty_key_at_construction():
    with pytest.raises(ProviderNotConfiguredError):
        GeminiLLMProvider(api_key="", model="gemini-2.5-flash")


async def test_gemini_embedding_provider_rejects_empty_key_at_construction():
    with pytest.raises(ProviderNotConfiguredError):
        GeminiEmbeddingProvider(api_key="", model="gemini-embedding-001")


# --- Schema translation (JSON-schema nullable-union -> Gemini's dialect) ---


def test_to_gemini_schema_converts_nullable_type_union():
    schema = {
        "type": "object",
        "properties": {
            "suggestion": {"type": ["string", "null"]},
            "count": {"type": ["integer", "null"]},
            "name": {"type": "string"},
        },
    }
    converted = _to_gemini_schema(schema)
    assert converted["properties"]["suggestion"] == {"type": "string", "nullable": True}
    assert converted["properties"]["count"] == {"type": "integer", "nullable": True}
    assert converted["properties"]["name"] == {"type": "string"}


def test_to_gemini_schema_recurses_into_arrays_and_nested_objects():
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"value": {"type": ["string", "null"]}},
                    "required": ["value"],
                },
            }
        },
    }
    converted = _to_gemini_schema(schema)
    inner = converted["properties"]["items"]["items"]
    assert inner["properties"]["value"] == {"type": "string", "nullable": True}
    assert inner["required"] == ["value"]  # non-schema-type fields pass through unchanged


# --- generate_structured: error mapping and success path --------------------


async def test_generate_structured_maps_authentication_error():
    provider = GeminiLLMProvider(api_key="fake", model="gemini-2.5-flash")

    async def fake_generate_content(**kwargs):
        raise errors.ClientError(401, {"error": {"message": "invalid API key"}})

    provider._client.aio.models.generate_content = fake_generate_content
    with pytest.raises(ProviderUnavailableError):
        await provider.generate_structured(system="s", user_content="u", schema={"type": "object"}, max_tokens=10)


async def test_generate_structured_maps_rate_limit_error():
    provider = GeminiLLMProvider(api_key="fake", model="gemini-2.5-flash")

    async def fake_generate_content(**kwargs):
        raise errors.ClientError(429, {"error": {"message": "rate limited"}})

    provider._client.aio.models.generate_content = fake_generate_content
    with pytest.raises(ProviderUnavailableError):
        await provider.generate_structured(system="s", user_content="u", schema={"type": "object"}, max_tokens=10)


async def test_generate_structured_rejects_non_json_response():
    provider = GeminiLLMProvider(api_key="fake", model="gemini-2.5-flash")

    class _FakeResponse:
        text = "not valid json {{{"

    async def fake_generate_content(**kwargs):
        return _FakeResponse()

    provider._client.aio.models.generate_content = fake_generate_content
    with pytest.raises(ProviderUnavailableError):
        await provider.generate_structured(system="s", user_content="u", schema={"type": "object"}, max_tokens=10)


async def test_generate_structured_returns_parsed_json_on_success():
    provider = GeminiLLMProvider(api_key="fake", model="gemini-2.5-flash")

    class _FakeResponse:
        text = '{"claims": []}'

    async def fake_generate_content(**kwargs):
        return _FakeResponse()

    provider._client.aio.models.generate_content = fake_generate_content
    result = await provider.generate_structured(system="s", user_content="u", schema={"type": "object"}, max_tokens=10)
    assert result == {"claims": []}


async def test_llm_verify_maps_authentication_error():
    provider = GeminiLLMProvider(api_key="fake", model="gemini-2.5-flash")

    async def fake_generate_content(**kwargs):
        raise errors.ClientError(401, {"error": {"message": "invalid API key"}})

    provider._client.aio.models.generate_content = fake_generate_content
    with pytest.raises(ProviderUnavailableError):
        await provider.verify()


# --- embed: error mapping, shape validation, success path -------------------


async def test_embed_maps_authentication_error():
    provider = GeminiEmbeddingProvider(api_key="fake", model="gemini-embedding-001")

    async def fake_embed_content(**kwargs):
        raise errors.ClientError(401, {"error": {"message": "invalid API key"}})

    provider._client.aio.models.embed_content = fake_embed_content
    with pytest.raises(ProviderUnavailableError):
        await provider.embed(["a"])


async def test_embed_rejects_malformed_response_shape():
    provider = GeminiEmbeddingProvider(api_key="fake", model="gemini-embedding-001")

    class _FakeResponse:
        embeddings = None  # missing .values entirely

    async def fake_embed_content(**kwargs):
        return _FakeResponse()

    provider._client.aio.models.embed_content = fake_embed_content
    with pytest.raises(ProviderUnavailableError):
        await provider.embed(["a"])


async def test_embed_rejects_mismatched_result_count():
    provider = GeminiEmbeddingProvider(api_key="fake", model="gemini-embedding-001")

    class _FakeEmbedding:
        values = [0.1, 0.2]

    class _FakeResponse:
        embeddings = [_FakeEmbedding()]  # one result for two inputs below

    async def fake_embed_content(**kwargs):
        return _FakeResponse()

    provider._client.aio.models.embed_content = fake_embed_content
    with pytest.raises(ProviderUnavailableError):
        await provider.embed(["a", "b"])


async def test_embed_returns_vectors_on_success():
    provider = GeminiEmbeddingProvider(api_key="fake", model="gemini-embedding-001")

    class _FakeEmbedding:
        def __init__(self, v):
            self.values = v

    class _FakeResponse:
        embeddings = [_FakeEmbedding([0.0, 0.0]), _FakeEmbedding([1.0, 1.0])]

    async def fake_embed_content(**kwargs):
        return _FakeResponse()

    provider._client.aio.models.embed_content = fake_embed_content
    vectors = await provider.embed(["a", "b"])
    assert vectors == [[0.0, 0.0], [1.0, 1.0]]


async def test_embed_empty_input_returns_empty_without_a_call():
    provider = GeminiEmbeddingProvider(api_key="fake", model="gemini-embedding-001")

    calls = []

    async def fake_embed_content(**kwargs):
        calls.append(kwargs)
        raise AssertionError("should never be called for empty input")

    provider._client.aio.models.embed_content = fake_embed_content
    result = await provider.embed([])
    assert result == []
    assert calls == []
