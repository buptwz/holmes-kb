"""Langfuse observability integration (optional plugin).

Langfuse is a **disabled-by-default** plugin. It is activated only when
``langfuse_enabled`` is ``true`` in ``~/.holmes/config.json``.

Activation flow:
  1. CLI loads config, calls ``init_langfuse_from_config(cfg)`` **before**
     importing pipeline modules.
  2. If ``cfg.langfuse_enabled`` is falsy, nothing happens — all decorators
     remain no-ops, zero overhead on the main flow.
  3. If enabled, config fields (or env vars as fallback) are used to
     initialise langfuse.

Configuration (``~/.holmes/config.json``)::

    {
      "langfuse_enabled": true,
      "langfuse_public_key": "pk-lf-...",
      "langfuse_secret_key": "sk-lf-...",
      "langfuse_host": "http://localhost:3000"
    }

Enable/disable via CLI::

    holmes config set langfuse_enabled true
    holmes config set langfuse_enabled false
"""

from __future__ import annotations

import os
from typing import Any

LANGFUSE_AVAILABLE = False


def init_langfuse_from_config(cfg: Any) -> None:
    """Initialise langfuse from HolmesConfig if enabled.

    Must be called **before** importing pipeline modules (so that
    ``@observe`` decorators bind to the real implementation).
    """
    enabled = getattr(cfg, "langfuse_enabled", False)
    if not enabled:
        return

    public_key = getattr(cfg, "langfuse_public_key", "") or ""
    secret_key = getattr(cfg, "langfuse_secret_key", "") or ""
    host = getattr(cfg, "langfuse_host", "") or ""

    if public_key:
        os.environ.setdefault("LANGFUSE_PUBLIC_KEY", public_key)
    if secret_key:
        os.environ.setdefault("LANGFUSE_SECRET_KEY", secret_key)
    if host:
        os.environ.setdefault("LANGFUSE_HOST", host)

    _try_enable()


def _try_enable() -> None:
    """Attempt to import and enable langfuse if credentials are available."""
    global LANGFUSE_AVAILABLE, observe, get_langfuse  # noqa: PLW0603

    has_key = bool(os.environ.get("LANGFUSE_PUBLIC_KEY"))
    if not has_key:
        return

    try:
        from langfuse import get_client  # type: ignore[import-untyped]
        from langfuse import observe as _observe  # type: ignore[import-untyped]

        LANGFUSE_AVAILABLE = True
        observe = _observe  # type: ignore[misc]
        get_langfuse = get_client  # type: ignore[misc]
    except ImportError:
        pass


# -- Default no-op implementations (overwritten by _try_enable on success) -----

def observe(  # type: ignore[misc]
    *args: Any, **kwargs: Any,
) -> Any:
    """No-op decorator when langfuse is not active."""
    if args and callable(args[0]):
        return args[0]
    return lambda fn: fn


class _StubClient:
    """Stub that silently ignores all method calls."""

    def __getattr__(self, _name: str) -> Any:
        return lambda *a, **kw: None


def get_langfuse() -> Any:  # type: ignore[misc]
    """Return a stub client when langfuse is not active."""
    return _StubClient()
