"""Factory for creating LLMProvider instances from HolmesConfig."""

from __future__ import annotations

from holmes.config import HolmesConfig
from holmes.kb.agent.provider.base import LLMProvider


def create_provider(cfg: HolmesConfig) -> LLMProvider:
    """Return the appropriate LLMProvider for the configured provider type.

    Args:
        cfg: Holmes runtime configuration containing provider, api_key, etc.

    Returns:
        Concrete LLMProvider instance.

    Raises:
        ValueError: If cfg.provider is not a known value.
    """
    if cfg.provider == "anthropic":
        from holmes.kb.agent.provider.anthropic_provider import AnthropicProvider
        return AnthropicProvider(cfg)
    elif cfg.provider == "openai":
        from holmes.kb.agent.provider.openai_provider import OpenAIProvider
        return OpenAIProvider(cfg)
    raise ValueError(
        f"Unknown provider: {cfg.provider!r}. Must be 'anthropic' or 'openai'.\n"
        "Run 'holmes setup --provider <anthropic|openai>' to reconfigure."
    )
