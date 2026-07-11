"""OpenAI-compatible SDK implementation of LLMProvider.

Compatible with OpenAI, Azure OpenAI, Ollama, and any other
OpenAI-compatible endpoint.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import openai

from holmes.config import HolmesConfig
from holmes.kb.agent.provider.base import LLMProvider, ToolCall

logger = logging.getLogger(__name__)

# Timeout & retry defaults
_REQUEST_TIMEOUT = 120          # seconds per API call
_MAX_RETRIES = 2                # retries on transient errors (timeout / connection)
_RETRY_BACKOFF_BASE = 2.0       # exponential backoff base


def _to_openai_tools(anthropic_tools: list[dict]) -> list[dict]:
    """Convert Anthropic tool definitions to OpenAI function-call format.

    Anthropic format:
        {"name": ..., "description": ..., "input_schema": {...}}

    OpenAI format:
        {"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}
    """
    result = []
    for t in anthropic_tools:
        result.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return result


class OpenAIProvider(LLMProvider):
    """LLMProvider backed by the OpenAI-compatible SDK.

    Converts Anthropic tool definitions to OpenAI format on each call.
    Tool results are appended as separate tool-role messages.
    """

    def __init__(self, cfg: HolmesConfig) -> None:
        self._client = openai.OpenAI(
            api_key=cfg.api_key or None,
            base_url=cfg.api_base_url or None,
            timeout=_REQUEST_TIMEOUT,
        )
        self._model = cfg.model

    def complete(
        self,
        messages: list[Any],
        system: str,
        model: str,
        max_tokens: int,
        tools: list[dict],
    ) -> tuple[bool, list[ToolCall], list[Any], dict[str, int]]:
        """Run one step of the OpenAI tool-use loop."""
        # Prepend system message.
        openai_messages = [{"role": "system", "content": system}] + list(messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "max_completion_tokens": max_tokens,
            "messages": openai_messages,
            "temperature": 0,
        }
        # Only pass tools when non-empty — some providers (e.g. deepseek)
        # return empty content when tools=[] is passed.
        if tools:
            kwargs["tools"] = _to_openai_tools(tools)

        response = self._call_with_retry(**kwargs)

        message = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        # Append assistant turn (without the prepended system message).
        updated = list(messages)
        # Reconstruct assistant message in a dict form compatible with future calls.
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
        if message.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in message.tool_calls
            ]
        updated.append(assistant_msg)

        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    parsed_input = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, ValueError):
                    parsed_input = {}
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    input=parsed_input,
                ))

        usage_obj = getattr(response, "usage", None)
        usage = {
            "input_tokens": getattr(usage_obj, "prompt_tokens", 0),
            "output_tokens": getattr(usage_obj, "completion_tokens", 0),
        }
        stop = (finish_reason in {"stop", None}) and not tool_calls
        return stop, tool_calls, updated, usage

    def simple_complete(
        self,
        messages: list[dict],
        system: str = "",
        max_tokens: int = 512,
    ) -> str:
        """Single-turn OpenAI completion without tools."""
        all_messages: list[dict] = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)
        response = self._call_with_retry(
            model=self._model,
            max_completion_tokens=max_tokens,
            messages=all_messages,
        )
        return response.choices[0].message.content or ""

    def _call_with_retry(self, **kwargs: Any) -> Any:
        """Call chat.completions.create with timeout and retry on transient errors."""
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                return self._client.chat.completions.create(**kwargs)
            except openai.APITimeoutError as exc:
                last_exc = exc
                logger.warning("API timeout (attempt %d/%d)", attempt + 1, _MAX_RETRIES + 1)
            except openai.APIConnectionError as exc:
                last_exc = exc
                logger.warning("API connection error (attempt %d/%d)", attempt + 1, _MAX_RETRIES + 1)
            except openai.AuthenticationError:
                raise RuntimeError(
                    "Authentication failed — API key rejected. "
                    "Check your key with: holmes config set api_key <KEY>"
                ) from None
            except openai.RateLimitError:
                raise RuntimeError(
                    "Rate limit reached. Wait a moment and retry, or check your plan quota."
                ) from None
            except openai.APIStatusError as exc:
                if exc.status_code >= 500:
                    last_exc = exc
                    logger.warning("Server error %d (attempt %d/%d)", exc.status_code, attempt + 1, _MAX_RETRIES + 1)
                else:
                    raise RuntimeError(
                        f"LLM provider returned HTTP {exc.status_code}. "
                        "Check provider status or retry."
                    ) from None
            if attempt < _MAX_RETRIES:
                wait = _RETRY_BACKOFF_BASE ** attempt
                logger.info("Retrying in %.1fs …", wait)
                time.sleep(wait)
        raise RuntimeError(
            f"LLM API call failed after {_MAX_RETRIES + 1} attempts: {last_exc}"
        ) from last_exc

    def append_tool_results(
        self,
        messages: list[Any],
        results: list[tuple[str, str]],
    ) -> list[Any]:
        """Append tool results as separate tool-role messages (OpenAI format)."""
        updated = list(messages)
        for tool_call_id, content in results:
            updated.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": content,
            })
        return updated
