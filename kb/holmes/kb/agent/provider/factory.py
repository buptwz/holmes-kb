"""Factory for creating LLMProvider instances from HolmesConfig."""

from __future__ import annotations

from holmes.config import HolmesConfig
from holmes.kb.agent.provider.base import LLMProvider


def _infer_provider(cfg: HolmesConfig) -> str:
    """Infer the LLM provider from config fields when cfg.provider is absent.

    Rules (in order):
    1. If cfg has an explicit `provider` attribute that is set, use it.
    2. If model name starts with "claude-", use "anthropic".
    3. Otherwise use "openai" (covers OpenAI, Azure, Ollama, and any
       OpenAI-compatible endpoint configured via api_base_url).
    """
    explicit = getattr(cfg, "provider", None)
    if explicit:
        return str(explicit)
    model = getattr(cfg, "model", "") or ""
    if model.startswith("claude-"):
        return "anthropic"
    return "openai"


def create_provider(cfg: HolmesConfig) -> LLMProvider:
    """Return the appropriate LLMProvider for the configured provider type.

    Args:
        cfg: Holmes runtime configuration containing model, api_key, etc.
            The provider is inferred from model name when not explicitly set.

    Returns:
        Concrete LLMProvider instance.

    Raises:
        ValueError: If the inferred provider is not a known value.
    """
    provider = _infer_provider(cfg)
    if provider == "anthropic":
        from holmes.kb.agent.provider.anthropic_provider import AnthropicProvider
        return AnthropicProvider(cfg)
    if provider == "openai":
        from holmes.kb.agent.provider.openai_provider import OpenAIProvider
        return OpenAIProvider(cfg)
    raise ValueError(
        f"Unknown provider: {provider!r}. Must be 'anthropic' or 'openai'.\n"
        "Set model to a 'claude-*' name for Anthropic, or configure api_base_url "
        "for an OpenAI-compatible endpoint."
    )
