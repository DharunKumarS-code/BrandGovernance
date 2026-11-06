"""Gemini as both the LLMProvider and EmbeddingProvider, via Google's
official `google-genai` SDK.

Structured output uses Gemini's native response_schema / response_mime_type
controlled-generation feature (not tool-calling) -- the model is
constrained to emit JSON matching the schema directly. That is itself only
the first of three defence layers; see app/services/analysis/ for the
second (delimiters + anti-injection system-prompt instructions) and third
(Pydantic validation of the returned dict, done by the caller).

Gemini's schema dialect historically rejects JSON Schema's `"type": [X,
"null"]` union-with-null form (it wants `nullable: true` alongside a
single type instead) -- _to_gemini_schema() below translates that one
pattern; everything else in a plain JSON-schema dict (properties, items,
enum, required, nested objects/arrays) passes through unchanged.
"""

from typing import Any

from google import genai
from google.genai import errors, types

from app.services.ai.errors import ProviderNotConfiguredError, ProviderUnavailableError
from app.services.ai.providers import EmbeddingProvider, LLMProvider


def _to_gemini_schema(schema: Any) -> Any:
    if isinstance(schema, dict):
        converted = {k: _to_gemini_schema(v) for k, v in schema.items() if k != "type"}
        type_value = schema.get("type")
        if isinstance(type_value, list):
            non_null = [t for t in type_value if t != "null"]
            converted["type"] = non_null[0] if non_null else "string"
            if "null" in type_value:
                converted["nullable"] = True
        elif type_value is not None:
            converted["type"] = type_value
        return converted
    if isinstance(schema, list):
        return [_to_gemini_schema(item) for item in schema]
    return schema


def _map_api_error(exc: Exception, context: str) -> ProviderUnavailableError:
    code = getattr(exc, "code", None)
    if code in (401, 403):
        return ProviderUnavailableError(f"Gemini API key was rejected (authentication failed) during {context}: {exc}")
    if code == 429:
        return ProviderUnavailableError(f"Gemini API rate limit hit during {context}: {exc}")
    return ProviderUnavailableError(f"Gemini API error during {context}: {exc}")


class GeminiLLMProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ProviderNotConfiguredError("GEMINI_API_KEY is not set.")
        self._model = model
        self._client = genai.Client(api_key=api_key)

    async def verify(self) -> None:
        # A minimal, near-free generation call -- Gemini has no dedicated
        # free "validate key" endpoint, so this is the cheapest real
        # confirmation that the key authenticates.
        try:
            await self._client.aio.models.generate_content(
                model=self._model,
                contents="ping",
                config=types.GenerateContentConfig(max_output_tokens=1),
            )
        except errors.APIError as exc:
            raise _map_api_error(exc, "verification") from exc
        except Exception as exc:
            raise ProviderUnavailableError(f"Gemini API unreachable during verification: {exc}") from exc

    async def generate_structured(
        self, *, system: str, user_content: str, schema: dict[str, Any], max_tokens: int
    ) -> dict[str, Any]:
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=user_content,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=0,
                    max_output_tokens=max_tokens,
                    response_mime_type="application/json",
                    response_schema=_to_gemini_schema(schema),
                ),
            )
        except errors.APIError as exc:
            raise _map_api_error(exc, "content generation") from exc
        except Exception as exc:
            raise ProviderUnavailableError(f"Gemini API unreachable or timed out: {exc}") from exc

        if not response.text:
            raise ProviderUnavailableError("Gemini response had no text content.")
        try:
            import json

            return json.loads(response.text)
        except ValueError as exc:
            raise ProviderUnavailableError(f"Gemini response was not valid JSON: {exc}") from exc


class GeminiEmbeddingProvider(EmbeddingProvider):
    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ProviderNotConfiguredError("GEMINI_API_KEY is not set.")
        self._model = model
        self._client = genai.Client(api_key=api_key)

    async def verify(self) -> None:
        await self.embed(["ping"])

    async def embed(self, texts: list[str], input_type: str | None = None) -> list[list[float]]:
        if not texts:
            return []
        task_type = {"query": "RETRIEVAL_QUERY", "document": "RETRIEVAL_DOCUMENT"}.get(input_type or "")
        try:
            response = await self._client.aio.models.embed_content(
                model=self._model,
                contents=texts,
                config=types.EmbedContentConfig(task_type=task_type) if task_type else None,
            )
        except errors.APIError as exc:
            raise _map_api_error(exc, "embedding") from exc
        except Exception as exc:
            raise ProviderUnavailableError(f"Gemini API unreachable or timed out: {exc}") from exc

        try:
            vectors = [item.values for item in response.embeddings]
        except (AttributeError, TypeError) as exc:
            raise ProviderUnavailableError(f"Gemini API returned an unexpected embedding response shape: {exc}") from exc

        if len(vectors) != len(texts):
            raise ProviderUnavailableError(
                f"Gemini API returned {len(vectors)} embedding(s) for {len(texts)} input text(s)."
            )
        return vectors
