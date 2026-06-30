"""Tests for OpenAIProvider timeout and retry logic."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import openai

from holmes.config import HolmesConfig
from holmes.kb.agent.provider.openai_provider import (
    OpenAIProvider,
    _MAX_RETRIES,
    _REQUEST_TIMEOUT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_provider() -> OpenAIProvider:
    cfg = HolmesConfig(api_key="test-key")
    return OpenAIProvider(cfg)


def _make_success_response(content: str = "ok") -> MagicMock:
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    return resp


# ---------------------------------------------------------------------------
# Timeout configuration
# ---------------------------------------------------------------------------

def test_client_has_timeout() -> None:
    """OpenAI client must be initialised with a timeout."""
    provider = _make_provider()
    assert provider._client.timeout is not None


# ---------------------------------------------------------------------------
# Retry on transient errors
# ---------------------------------------------------------------------------

def test_retry_on_timeout() -> None:
    """APITimeoutError should be retried up to _MAX_RETRIES times."""
    provider = _make_provider()
    call_count = 0

    def _fake_create(**kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count <= _MAX_RETRIES:
            raise openai.APITimeoutError(request=MagicMock())
        return _make_success_response()

    with patch.object(provider._client.chat.completions, "create", side_effect=_fake_create):
        with patch("holmes.kb.agent.provider.openai_provider.time.sleep"):
            result = provider.simple_complete([{"role": "user", "content": "hi"}])

    assert result == "ok"
    assert call_count == _MAX_RETRIES + 1


def test_retry_on_connection_error() -> None:
    """APIConnectionError should be retried."""
    provider = _make_provider()
    call_count = 0

    def _fake_create(**kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise openai.APIConnectionError(request=MagicMock())
        return _make_success_response()

    with patch.object(provider._client.chat.completions, "create", side_effect=_fake_create):
        with patch("holmes.kb.agent.provider.openai_provider.time.sleep"):
            result = provider.simple_complete([{"role": "user", "content": "hi"}])

    assert result == "ok"
    assert call_count == 2


def test_retry_on_server_500() -> None:
    """Server errors (5xx) should be retried."""
    provider = _make_provider()
    call_count = 0

    def _fake_create(**kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise openai.APIStatusError(
                message="server error",
                response=MagicMock(status_code=502, headers={}),
                body={},
            )
        return _make_success_response()

    with patch.object(provider._client.chat.completions, "create", side_effect=_fake_create):
        with patch("holmes.kb.agent.provider.openai_provider.time.sleep"):
            result = provider.simple_complete([{"role": "user", "content": "hi"}])

    assert result == "ok"
    assert call_count == 2


def test_retry_exhausted_raises_runtime_error() -> None:
    """When all retries fail, RuntimeError must be raised."""
    provider = _make_provider()

    def _fake_create(**kwargs: Any) -> Any:
        raise openai.APITimeoutError(request=MagicMock())

    with patch.object(provider._client.chat.completions, "create", side_effect=_fake_create):
        with patch("holmes.kb.agent.provider.openai_provider.time.sleep"):
            with pytest.raises(RuntimeError, match="failed after"):
                provider.simple_complete([{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# Non-retryable errors propagate immediately
# ---------------------------------------------------------------------------

def test_auth_error_not_retried() -> None:
    """AuthenticationError must raise RuntimeError immediately."""
    provider = _make_provider()
    call_count = 0

    def _fake_create(**kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        raise openai.AuthenticationError(
            message="bad key",
            response=MagicMock(status_code=401, headers={}),
            body={},
        )

    with patch.object(provider._client.chat.completions, "create", side_effect=_fake_create):
        with pytest.raises(RuntimeError, match="Authentication failed"):
            provider.simple_complete([{"role": "user", "content": "hi"}])

    assert call_count == 1


def test_rate_limit_not_retried() -> None:
    """RateLimitError must raise RuntimeError immediately (not silently retried)."""
    provider = _make_provider()
    call_count = 0

    def _fake_create(**kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        raise openai.RateLimitError(
            message="rate limit",
            response=MagicMock(status_code=429, headers={}),
            body={},
        )

    with patch.object(provider._client.chat.completions, "create", side_effect=_fake_create):
        with pytest.raises(RuntimeError, match="Rate limit"):
            provider.simple_complete([{"role": "user", "content": "hi"}])

    assert call_count == 1


def test_client_error_4xx_not_retried() -> None:
    """4xx errors (not auth/rate-limit) must raise immediately."""
    provider = _make_provider()

    def _fake_create(**kwargs: Any) -> Any:
        raise openai.APIStatusError(
            message="bad request",
            response=MagicMock(status_code=400, headers={}),
            body={},
        )

    with patch.object(provider._client.chat.completions, "create", side_effect=_fake_create):
        with pytest.raises(RuntimeError, match="HTTP 400"):
            provider.simple_complete([{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# complete() also uses retry
# ---------------------------------------------------------------------------

def test_complete_retries_on_timeout() -> None:
    """complete() (with tools) also retries on transient errors."""
    provider = _make_provider()
    call_count = 0

    def _fake_create(**kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise openai.APITimeoutError(request=MagicMock())
        return _make_success_response("done")

    tools = [{"name": "foo", "description": "d", "input_schema": {"type": "object", "properties": {}}}]

    with patch.object(provider._client.chat.completions, "create", side_effect=_fake_create):
        with patch("holmes.kb.agent.provider.openai_provider.time.sleep"):
            stop, tool_calls, msgs, usage = provider.complete(
                messages=[{"role": "user", "content": "hi"}],
                system="sys",
                model="test-model",
                max_tokens=100,
                tools=tools,
            )

    assert stop is True
    assert call_count == 2
