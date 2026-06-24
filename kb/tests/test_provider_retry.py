"""Tests for LLM provider retry logic (US3 perf optimisation)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from holmes.kb.agent.provider.base import _call_with_retry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeError(Exception):
    """Generic retryable error for testing."""


class _FakeAuthError(Exception):
    """Non-retryable authentication error for testing."""


# ---------------------------------------------------------------------------
# _call_with_retry core behaviour
# ---------------------------------------------------------------------------

def test_retry_succeeds_on_second_attempt() -> None:
    """fn that fails once then succeeds should return the success value."""
    attempts = []

    def fn():
        attempts.append(1)
        if len(attempts) < 2:
            raise _FakeError("transient")
        return "ok"

    with patch("time.sleep"):
        result = _call_with_retry(fn, max_attempts=3, base_delay=0.0, max_delay=1.0,
                                   retryable_types=(_FakeError,))

    assert result == "ok"
    assert len(attempts) == 2


def test_retry_exhausted_raises_runtime_error() -> None:
    """When all attempts fail, RuntimeError must be raised."""
    def fn():
        raise _FakeError("always fails")

    with patch("time.sleep"):
        with pytest.raises(RuntimeError, match="not resolved after 3 attempt"):
            _call_with_retry(fn, max_attempts=3, base_delay=0.0, max_delay=1.0,
                             retryable_types=(_FakeError,))


def test_non_retryable_error_propagates_immediately() -> None:
    """Errors not in retryable_types must propagate without retrying."""
    call_count = 0

    def fn():
        nonlocal call_count
        call_count += 1
        raise _FakeAuthError("auth failed")

    with pytest.raises(_FakeAuthError):
        _call_with_retry(fn, max_attempts=5, base_delay=0.0, max_delay=1.0,
                         retryable_types=(_FakeError,))  # _FakeAuthError not included

    assert call_count == 1, "Non-retryable error must not be retried"


def test_retry_delay_is_bounded_by_max_delay() -> None:
    """Backoff delay must never exceed max_delay (before jitter)."""
    sleep_calls = []

    def fn():
        raise _FakeError("rate limit")

    with patch("time.sleep", side_effect=lambda d: sleep_calls.append(d)):
        with patch("random.uniform", return_value=0.0):
            with pytest.raises(RuntimeError):
                _call_with_retry(fn, max_attempts=6, base_delay=1.0, max_delay=5.0,
                                 retryable_types=(_FakeError,))

    # Each delay should be <= max_delay + jitter (jitter patched to 0)
    for d in sleep_calls:
        assert d <= 5.0, f"Delay {d} exceeds max_delay=5.0"


def test_retry_delay_increases_exponentially() -> None:
    """Delays should grow: base, 2*base, 4*base, ... up to max_delay."""
    sleep_calls = []

    def fn():
        raise _FakeError("rate limit")

    with patch("time.sleep", side_effect=lambda d: sleep_calls.append(d)):
        with patch("random.uniform", return_value=0.0):
            with pytest.raises(RuntimeError):
                _call_with_retry(fn, max_attempts=4, base_delay=1.0, max_delay=100.0,
                                 retryable_types=(_FakeError,))

    # 3 sleeps for 4 attempts (no sleep after last attempt)
    assert sleep_calls == pytest.approx([1.0, 2.0, 4.0], abs=0.01)


def test_no_retry_on_success() -> None:
    """A successful first call must not trigger any sleep."""
    with patch("time.sleep") as mock_sleep:
        result = _call_with_retry(lambda: 42, max_attempts=3, retryable_types=(_FakeError,))

    assert result == 42
    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# AnthropicProvider retry integration
# ---------------------------------------------------------------------------

def test_anthropic_provider_retries_rate_limit(tmp_path: Any) -> None:
    """AnthropicProvider.complete() should retry on RateLimitError."""
    import anthropic
    from holmes.config import HolmesConfig
    from holmes.kb.agent.provider.anthropic_provider import AnthropicProvider

    cfg = HolmesConfig(api_key="test", retry_max_attempts=3, retry_base_delay=0.0)
    provider = AnthropicProvider(cfg)

    call_count = 0

    def _fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise anthropic.RateLimitError(
                message="rate limit", response=MagicMock(status_code=429, headers={}), body={}
            )
        # Return a minimal valid response on the 3rd attempt.
        resp = MagicMock()
        resp.content = []
        resp.stop_reason = "end_turn"
        return resp

    with patch.object(provider._client.messages, "create", side_effect=_fake_create):
        with patch("time.sleep"):
            stop, tool_calls, msgs = provider.complete(
                messages=[{"role": "user", "content": "hi"}],
                system="",
                model="claude-3",
                max_tokens=100,
                tools=[],
            )

    assert call_count == 3
    assert stop is True


def test_anthropic_provider_auth_error_not_retried() -> None:
    """AnthropicProvider must raise RuntimeError immediately on AuthenticationError."""
    import anthropic
    from holmes.config import HolmesConfig
    from holmes.kb.agent.provider.anthropic_provider import AnthropicProvider

    cfg = HolmesConfig(api_key="bad-key", retry_max_attempts=5, retry_base_delay=0.0)
    provider = AnthropicProvider(cfg)

    call_count = 0

    def _fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        raise anthropic.AuthenticationError(
            message="auth error", response=MagicMock(status_code=401, headers={}), body={}
        )

    with patch.object(provider._client.messages, "create", side_effect=_fake_create):
        with pytest.raises(RuntimeError, match="Authentication failed"):
            provider.complete(
                messages=[{"role": "user", "content": "hi"}],
                system="",
                model="claude-3",
                max_tokens=100,
                tools=[],
            )

    assert call_count == 1, "Auth error must not be retried"


# ---------------------------------------------------------------------------
# OpenAIProvider retry integration
# ---------------------------------------------------------------------------

def test_openai_provider_retries_rate_limit() -> None:
    """OpenAIProvider.complete() should retry on RateLimitError."""
    import openai
    from holmes.config import HolmesConfig
    from holmes.kb.agent.provider.openai_provider import OpenAIProvider

    cfg = HolmesConfig(api_key="test", retry_max_attempts=3, retry_base_delay=0.0)
    provider = OpenAIProvider(cfg)

    call_count = 0

    def _fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise openai.RateLimitError(
                message="rate limit",
                response=MagicMock(status_code=429, headers={}),
                body={},
            )
        msg = MagicMock()
        msg.content = "hello"
        msg.tool_calls = None
        choice = MagicMock()
        choice.message = msg
        choice.finish_reason = "stop"
        resp = MagicMock()
        resp.choices = [choice]
        return resp

    with patch.object(provider._client.chat.completions, "create", side_effect=_fake_create):
        with patch("time.sleep"):
            stop, tool_calls, msgs = provider.complete(
                messages=[{"role": "user", "content": "hi"}],
                system="",
                model="gpt-4o",
                max_tokens=100,
                tools=[],
            )

    assert call_count == 3
