"""Unit tests for VerifierAgent full-doc access (T026).

Verifies that verify_content uses the full source_text from ctx (not truncated)
when the ctx source is longer than the tool_input source.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from holmes.kb.agent.tools import verify_content


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(source_text: str) -> dict[str, Any]:
    """Build a minimal ctx dict with a mock provider."""
    provider = MagicMock()
    provider.simple_complete.return_value = '{"verified_fields": ["title", "root_cause", "resolution_commands"], "unsupported_fields": [], "confidence": 0.95}'
    return {
        "source_text": source_text,
        "provider": provider,
    }


DRAFT_CONTENT = """\
---
type: pitfall
title: Redis replication lag
category: database
---

## Root Cause

Redis replication buffer overflow caused by large key writes.

## Resolution

```bash
redis-cli CONFIG SET repl-backlog-size 67108864
```
"""


# ---------------------------------------------------------------------------
# Tests: verify_content uses full source from ctx
# ---------------------------------------------------------------------------


class TestVerifyContentFullDocAccess:
    def test_uses_ctx_source_when_longer(self):
        """When ctx["source_text"] is longer than tool_input source, ctx source is used."""
        # Build a 12K source where key content is in chars 5000-9000
        prefix = "Background information. " * 200  # ~4800 chars
        key_content = (
            "\n\n## Root Cause\n\nRedis replication buffer overflow caused by large key writes.\n\n"
            "## Resolution\n\nSet repl-backlog-size to 64MB.\n\n"
        )
        suffix = "Additional context. " * 150  # ~3000 chars
        full_source = prefix + key_content + suffix
        assert len(full_source) > 6000

        ctx = _make_ctx(full_source)
        short_source = full_source[:3000]  # truncated, missing key content

        # Call with truncated source in tool_input
        result = verify_content(ctx, {
            "source_text": short_source,
            "draft_content": DRAFT_CONTENT,
        })

        # Check that simple_complete was called with the FULL source (via ctx fallback)
        call_args = ctx["provider"].simple_complete.call_args
        messages = call_args[0][0]  # first positional arg is list of messages
        prompt = messages[0]["content"]

        # The full_source should be in the prompt, not the short_source
        assert len(prompt) > len(short_source), (
            "verify_content should use full ctx source, not the truncated tool_input source"
        )

    def test_uses_tool_input_source_when_ctx_source_shorter(self):
        """When tool_input source is longer or equal to ctx source, tool_input source is used."""
        short_ctx_source = "Short context source."
        long_tool_source = "A" * 5000  # tool_input source is longer

        ctx = _make_ctx(short_ctx_source)
        result = verify_content(ctx, {
            "source_text": long_tool_source,
            "draft_content": DRAFT_CONTENT,
        })

        call_args = ctx["provider"].simple_complete.call_args
        messages = call_args[0][0]
        prompt = messages[0]["content"]
        # long_tool_source should be in prompt (not the short ctx source)
        # The prompt truncates to [:6000], so check at least 4000 chars are from long_tool_source
        assert "A" * 1000 in prompt

    def test_no_false_clear_for_content_in_chars_5000_to_9000(self):
        """Content at chars 5000-9000 should not be falsely CLEARED.

        When verify_content uses the full source (not truncated), fields
        supported by content in chars 5000-9000 should NOT be in unsupported_fields.
        """
        # Build 12K source with key content in chars 5000-9000
        prefix = "x" * 5000
        key_content = (
            "## Root Cause\nRedis replication buffer overflow.\n\n"
            "## Resolution\nredis-cli CONFIG SET repl-backlog-size 67108864\n"
        )
        padding = "y" * (9000 - 5000 - len(key_content))
        suffix = "z" * 3000
        full_source = prefix + key_content + padding + suffix
        assert len(full_source) > 9000

        # Provider confirms all fields are verified
        provider = MagicMock()
        provider.simple_complete.return_value = (
            '{"verified_fields": ["title", "root_cause", "resolution_commands"], '
            '"unsupported_fields": [], "confidence": 0.95}'
        )
        ctx = {"source_text": full_source, "provider": provider}

        result = verify_content(ctx, {
            "source_text": full_source[:3000],  # truncated in tool_input
            "draft_content": DRAFT_CONTENT,
        })

        # No fields should be cleared when full source is used
        assert result["unsupported_fields"] == []
        assert result["confidence"] == 0.95

    def test_returns_error_gracefully_on_provider_failure(self):
        """Returns confidence=1.0 and empty lists if provider call fails."""
        provider = MagicMock()
        provider.simple_complete.side_effect = Exception("API timeout")
        ctx = {"source_text": "test source", "provider": provider}

        result = verify_content(ctx, {
            "source_text": "test source",
            "draft_content": DRAFT_CONTENT,
        })

        assert result["verified_fields"] == []
        assert result["unsupported_fields"] == []
        assert result["confidence"] == 1.0
        assert "error" in result

    def test_no_provider_returns_passthrough(self):
        """With no provider in ctx, returns pass-through result (no CLEARED)."""
        ctx: dict[str, Any] = {}
        result = verify_content(ctx, {
            "source_text": "test",
            "draft_content": DRAFT_CONTENT,
        })
        assert result["confidence"] == 1.0
        assert result["unsupported_fields"] == []
