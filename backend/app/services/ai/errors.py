class ProviderNotConfiguredError(Exception):
    """The provider's API key is missing/empty. Known at construction time,
    before any network call -- callers should treat this identically to a
    transient ProviderUnavailableError (fall back to degraded mode), but it
    is worth distinguishing in logs: this one means "never configured", not
    "configured but currently failing"."""


class ProviderUnavailableError(Exception):
    """A configured provider failed at call time -- auth failure, timeout,
    rate limit, or an invalid/unparseable response. Always caught by the
    analysis orchestrator and treated as "fall back to degraded mode for
    this request", never as fatal."""
