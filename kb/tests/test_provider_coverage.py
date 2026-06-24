"""Coverage tests for LLM provider methods not covered by test_provider_retry.py.

Covers:
- AnthropicProvider.simple_complete() retry on rate limit (US3)
- AnthropicProvider.simple_complete() auth error fast-fail (US3)
- OpenAIProvider.simple_complete() retry on rate limit (US3)
- OpenAIProvider.complete() tool call response parsing (OpenAI tool call path)
- _to_openai_tools() format conversion
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from holmes.config import HolmesConfig
from holmes.kb.agent.provider.base import ToolCall


# ---------------------------------------------------------------------------
# T4: AnthropicProvider.simple_complete() retries on RateLimitError
# ---------------------------------------------------------------------------

def test_anthropic_simple_complete_retries_rate_limit() -> None:
    """T4: simple_complete() must retry on RateLimitError, return text on success."""
    import anthropic
    from holmes.kb.agent.provider.anthropic_provider import AnthropicProvider

    cfg = HolmesConfig(api_key="test", retry_max_attempts=3, retry_base_delay=0.0)
    provider = AnthropicProvider(cfg)

    call_count = 0

    def _fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise anthropic.RateLimitError(
                message="rate limited",
                response=MagicMock(status_code=429, headers={}),
                body={},
            )
        resp = MagicMock()
        resp.content = [MagicMock(text="resolved")]
        return resp

    with patch.object(provider._client.messages, "create", side_effect=_fake_create), \
         patch("time.sleep"):
        result = provider.simple_complete(
            messages=[{"role": "user", "content": "summarize"}]
        )

    assert call_count == 3, f"Expected 3 attempts, got {call_count}"
    assert result == "resolved"


# ---------------------------------------------------------------------------
# T5: AnthropicProvider.simple_complete() auth error is not retried
# ---------------------------------------------------------------------------

def test_anthropic_simple_complete_auth_error_not_retried() -> None:
    """T5: simple_complete() must raise RuntimeError immediately on AuthenticationError."""
    import anthropic
    from holmes.kb.agent.provider.anthropic_provider import AnthropicProvider

    cfg = HolmesConfig(api_key="bad-key", retry_max_attempts=5, retry_base_delay=0.0)
    provider = AnthropicProvider(cfg)

    call_count = 0

    def _fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        raise anthropic.AuthenticationError(
            message="invalid key",
            response=MagicMock(status_code=401, headers={}),
            body={},
        )

    with patch.object(provider._client.messages, "create", side_effect=_fake_create):
        with pytest.raises(RuntimeError, match="Authentication failed"):
            provider.simple_complete(
                messages=[{"role": "user", "content": "hi"}]
            )

    assert call_count == 1, "Auth error must not be retried in simple_complete()"


# ---------------------------------------------------------------------------
# T6: OpenAIProvider.simple_complete() retries on RateLimitError
# ---------------------------------------------------------------------------

def test_openai_simple_complete_retries_rate_limit() -> None:
    """T6: OpenAI simple_complete() must retry on RateLimitError."""
    import openai
    from holmes.kb.agent.provider.openai_provider import OpenAIProvider

    cfg = HolmesConfig(api_key="test", retry_max_attempts=3, retry_base_delay=0.0)
    provider = OpenAIProvider(cfg)

    call_count = 0

    def _fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise openai.RateLimitError(
                message="rate limited",
                response=MagicMock(status_code=429, headers={}),
                body={},
            )
        msg = MagicMock()
        msg.content = "answer text"
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        return resp

    with patch.object(provider._client.chat.completions, "create",
                      side_effect=_fake_create), \
         patch("time.sleep"):
        result = provider.simple_complete(
            messages=[{"role": "user", "content": "what is this?"}],
            system="You are helpful.",
        )

    assert call_count == 3, f"Expected 3 attempts, got {call_count}"
    assert result == "answer text"


# ---------------------------------------------------------------------------
# T7: OpenAIProvider.complete() correctly parses tool_calls from response
# ---------------------------------------------------------------------------

def test_openai_complete_parses_tool_calls_correctly() -> None:
    """T7: complete() must parse tool_calls from model response into ToolCall objects."""
    import openai
    from holmes.kb.agent.provider.openai_provider import OpenAIProvider

    cfg = HolmesConfig(api_key="test", retry_max_attempts=1)
    provider = OpenAIProvider(cfg)

    # Build a mock response with two tool calls.
    tc1 = MagicMock()
    tc1.id = "call-001"
    tc1.function.name = "search_kb"
    tc1.function.arguments = '{"query": "memory leak"}'

    tc2 = MagicMock()
    tc2.id = "call-002"
    tc2.function.name = "write_entry"
    tc2.function.arguments = '{"content": "some content"}'

    msg = MagicMock()
    msg.content = None
    msg.tool_calls = [tc1, tc2]

    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "tool_calls"

    resp = MagicMock()
    resp.choices = [choice]

    with patch.object(provider._client.chat.completions, "create", return_value=resp):
        stop, tool_calls, updated_messages = provider.complete(
            messages=[{"role": "user", "content": "find stuff"}],
            system="",
            model="gpt-4o",
            max_tokens=512,
            tools=[],
        )

    assert stop is False, "stop must be False when tool calls are present"
    assert len(tool_calls) == 2, f"Expected 2 ToolCall objects, got {len(tool_calls)}"

    assert tool_calls[0].id == "call-001"
    assert tool_calls[0].name == "search_kb"
    assert tool_calls[0].input == {"query": "memory leak"}

    assert tool_calls[1].id == "call-002"
    assert tool_calls[1].name == "write_entry"
    assert tool_calls[1].input == {"content": "some content"}

    # Assistant message must be appended with tool_calls field.
    assistant_msg = updated_messages[-1]
    assert assistant_msg["role"] == "assistant"
    assert "tool_calls" in assistant_msg


# ---------------------------------------------------------------------------
# T8: _to_openai_tools() converts Anthropic tool defs to OpenAI format
# ---------------------------------------------------------------------------

def test_openai_to_openai_tools_conversion() -> None:
    """T8: _to_openai_tools() must produce valid OpenAI function-call format."""
    from holmes.kb.agent.provider.openai_provider import _to_openai_tools

    anthropic_tools = [
        {
            "name": "search_kb",
            "description": "Search the knowledge base",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "write_entry",
            "description": "Write a KB entry",
            "input_schema": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                },
            },
        },
    ]

    result = _to_openai_tools(anthropic_tools)

    assert len(result) == 2

    tool0 = result[0]
    assert tool0["type"] == "function"
    assert tool0["function"]["name"] == "search_kb"
    assert tool0["function"]["description"] == "Search the knowledge base"
    assert "query" in tool0["function"]["parameters"]["properties"]

    tool1 = result[1]
    assert tool1["type"] == "function"
    assert tool1["function"]["name"] == "write_entry"
    assert "content" in tool1["function"]["parameters"]["properties"]
