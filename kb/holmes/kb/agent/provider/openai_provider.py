"""OpenAI-compatible SDK implementation of LLMProvider.

Compatible with OpenAI, Azure OpenAI, Ollama, and any other
OpenAI-compatible endpoint.
"""

from __future__ import annotations

import json
from typing import Any

import openai

from holmes.config import HolmesConfig
from holmes.kb.agent.provider.base import LLMProvider, ToolCall


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
        )
        self._model = cfg.model

    def complete(
        self,
        messages: list[Any],
        system: str,
        model: str,
        max_tokens: int,
        tools: list[dict],
    ) -> tuple[bool, list[ToolCall], list[Any]]:
        """Run one step of the OpenAI tool-use loop."""
        # Prepend system message.
        openai_messages = [{"role": "system", "content": system}] + list(messages)
        openai_tools = _to_openai_tools(tools)

        try:
            response = self._client.chat.completions.create(
                model=model,
                max_completion_tokens=max_tokens,
                tools=openai_tools,
                messages=openai_messages,
            )
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
            raise RuntimeError(
                f"LLM provider returned a server error (HTTP {exc.status_code}). "
                "Check provider status or retry."
            ) from None

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

        stop = (finish_reason in {"stop", None}) and not tool_calls
        return stop, tool_calls, updated

    def simple_complete(self, messages: list[dict]) -> str:
        """Single-turn OpenAI completion without tools."""
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                max_completion_tokens=512,
                messages=messages,
            )
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
            raise RuntimeError(
                f"LLM provider returned a server error (HTTP {exc.status_code}). "
                "Check provider status or retry."
            ) from None
        return response.choices[0].message.content or ""

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
