from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "clarivue_ai"

    jwt_secret_key: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 120
    # Phase 9 Stage 2: when True, every request MUST carry a valid JWT
    # (Authorization: Bearer ...) -- the legacy X-Organisation-Id/
    # X-User-Id demo headers are rejected outright. Default False
    # preserves all existing local-dev/test behaviour; set true in
    # production. See app/core/demo_context.py.
    require_jwt_auth: bool = False
    # Phase 9 Stage 2: GET /api/demo/organisations and .../users let
    # anyone enumerate every org/user with no credentials -- fine for a
    # local demo selector, a real vulnerability in production. Default
    # True preserves current behaviour; set false in production.
    enable_demo_endpoints: bool = True

    frontend_origin: str = "http://localhost:5173"

    # Phase 3: file storage (see app/core/storage.py)
    storage_root: str = "storage"
    max_guideline_upload_mb: int = 20
    max_asset_upload_mb: int = 5

    # Phase 5: AI provider configuration. Gemini covers both analysis/
    # claim-extraction and embeddings under one API key. Optional at the
    # settings level: a missing key means degraded (rule-only) mode, never
    # a startup crash -- see app/services/ai/.
    gemini_api_key: str | None = None
    # gemini-2.5-flash was Google's default here through Phase 5 development
    # but has since been sunset for this API key's account tier (confirmed
    # live: Gemini now returns 404 "no longer available to new users" for
    # it). gemini-3.5-flash-lite is the confirmed-working replacement as of
    # this verification pass -- override via the GEMINI_MODEL env var (or
    # backend/.env) without touching this default if Google moves the
    # goalposts again.
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_embedding_model: str = "gemini-embedding-001"

    # Phase 5 cost/performance controls (section H of the implementation spec).
    analysis_max_content_chars: int = 20_000
    analysis_retrieval_chunk_limit: int = 5
    analysis_max_output_tokens: int = 2048
    # Bumping this invalidates every cached analysis result (see
    # app/models/revision.py: Revision.analysis_cache) without needing to
    # touch model/version strings individually -- e.g. after a prompt
    # rewrite that isn't a model/version change.
    analysis_prompt_version: str = "v1"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
